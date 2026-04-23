"""Flask blueprint: recent-interactions feed for the new Interactions tab.

The reference project (JaimeCernuda/agent-interception @ ed04e49) exposes
``/_interceptor/interactions`` returning a flat list of ``InteractionSummary``
rows across every session, most-recent first. The React ``useLiveInteractions``
hook polls this every 5 s (and, when SSE is available, subscribes to
``/_interceptor/live`` for push updates — not yet implemented on this Flask
side; the hook degrades to polling on its own).

This blueprint stitches the same shape on top of the existing per-session
Chimaera IPC. It's pull-only by design — a streaming broadcaster is a Phase 2
enhancement.
"""

from __future__ import annotations

import json
import time
from threading import Lock

from flask import Blueprint, Response, request

from .. import chimaera_client
from ..adapters.conversation_adapter import flatten_monitor_result


bp = Blueprint("interactions", __name__)

# Cheap cache: computing the flat feed is O(sessions * avg_interactions) and
# we don't want a 5 s poll from every open tab hammering Chimaera. Bounded
# by wall-clock staleness, not by count — the underlying list changes by at
# most one row per forward, so a 1 s TTL is plenty live.
_CACHE_TTL_SECONDS = 1.0
_cache_lock = Lock()
_cache: dict[str, tuple[float, list[dict]]] = {}


def _interaction_summary(session_id: str, record: dict) -> dict | None:
    """Flatten a raw tracker record into the InteractionSummary shape.

    Returns ``None`` when the record can't be coerced (skip it rather than
    crash the whole feed).
    """
    if not isinstance(record, dict):
        return None
    try:
        seq = int(record.get("sequence_id", 0))
    except (TypeError, ValueError):
        return None

    req = record.get("request") or {}
    resp = record.get("response") or {}

    response_text = resp.get("text") if isinstance(resp.get("text"), str) else None
    preview = None
    if response_text:
        preview = response_text[:200] + ("…" if len(response_text) > 200 else "")

    return {
        "id": f"{session_id}:{seq}",
        "session_id": session_id,
        "timestamp": record.get("timestamp") or "",
        "provider": record.get("provider") or "unknown",
        "model": record.get("model"),
        "method": req.get("method", "POST"),
        "path": req.get("path", "/"),
        "status_code": resp.get("status_code"),
        "is_streaming": bool(resp.get("is_streaming", False)),
        "total_latency_ms": (record.get("metrics") or {}).get("total_latency_ms"),
        "response_text_preview": preview,
    }


def _compute_feed(
    limit: int,
    provider_filter: str | None,
    model_filter: str | None,
    session_filter: str | None,
) -> list[dict]:
    """Build the interaction feed by fanning out over known sessions."""
    # 1. Enumerate sessions via the existing proxy handler.
    try:
        raw_sessions = chimaera_client.get_sessions()
    except Exception:
        return []

    session_ids: list[str] = []
    for _cid, payload in raw_sessions.items():
        if isinstance(payload, list):
            for s in payload:
                if isinstance(s, dict):
                    sid = s.get("session_id")
                    if isinstance(sid, str) and sid:
                        session_ids.append(sid)
        elif isinstance(payload, dict):
            sid = payload.get("session_id")
            if isinstance(sid, str) and sid:
                session_ids.append(sid)

    if session_filter:
        session_ids = [s for s in session_ids if s == session_filter]

    # 2. For each session, pull its interactions. Cap per-session fetches to
    # keep latency bounded on very chatty sessions; we only need the most
    # recent ``limit`` rows globally.
    rows: list[dict] = []
    for sid in session_ids:
        try:
            raw = chimaera_client.get_session_interactions(sid)
        except Exception:
            continue
        for record in flatten_monitor_result(raw):
            summary = _interaction_summary(sid, record)
            if summary is None:
                continue
            if provider_filter and summary["provider"] != provider_filter:
                continue
            if model_filter and summary["model"] != model_filter:
                continue
            rows.append(summary)

    # 3. Sort most-recent first; ties broken by session + sequence so the
    # order stays stable across polls.
    rows.sort(
        key=lambda r: (r.get("timestamp") or "", r.get("session_id") or "", r.get("id") or ""),
        reverse=True,
    )
    return rows[:limit]


@bp.route("/_interceptor/interactions", methods=["GET"])
def list_interactions():
    """Reference-compatible ``InteractionSummary[]`` over the last N records."""
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))

    provider_filter = request.args.get("provider") or None
    model_filter = request.args.get("model") or None
    session_filter = request.args.get("session_id") or None

    cache_key = f"{limit}|{provider_filter or ''}|{model_filter or ''}|{session_filter or ''}"
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
            return Response(json.dumps(hit[1]), content_type="application/json")

    rows = _compute_feed(limit, provider_filter, model_filter, session_filter)

    with _cache_lock:
        _cache[cache_key] = (now, rows)

    return Response(json.dumps(rows), content_type="application/json")
