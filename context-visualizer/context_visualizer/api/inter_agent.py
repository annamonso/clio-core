"""Flask blueprint: inter-agent message ingest + read API.

The capture path is:
    MCP relay (or any wrapper) --POST--> /api/_inter-agent/ingest
                                            ├── start (at call initiation)
                                            └── done  (at call completion)

Reads go through /api/scenarios/<sid>/inter-agent which returns stitched events.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from flask import Blueprint, Response, request

from ..inter_agent import InterAgentMessage, get_store
from ..inter_agent.store import new_message

bp = Blueprint("inter_agent", __name__)


# ──────────────────────────────────────────────────────────────────────────
# Ingest (write)
# ──────────────────────────────────────────────────────────────────────────


def _required(data: dict, key: str) -> Any:
    v = data.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise ValueError(f"missing required field: {key}")
    return v


def _digest_payload(payload: Any) -> tuple[str, str]:
    """Return (sha256-digest, short-preview) for an arbitrary payload.

    Preview is truncated to 512 chars so we don't smuggle huge strings into
    the event store. Full payloads remain in the LLM InteractionRecord blobs.
    """
    if payload is None:
        return "", ""
    text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    preview = text[:512]
    return digest, preview


@bp.route("/_inter-agent/ingest", methods=["POST"])
def ingest():
    """Record an inter-agent event.

    Body (JSON):
      {
        "scenario_id": "expt-1",                     # required
        "phase": "start" | "done",                   # required
        "correlation_id": "...",                     # optional (auto-generated if missing)
        "from_host": "ares-comp-11",                 # required
        "from_session": "planner-a",                 # required
        "to_host": "ares-comp-12",                   # required
        "to_session": "fetcher-b",                   # required
        "kind": "mcp_call",                          # optional (default)
        "tool_name": "call_remote_agent",            # optional
        "payload": {...} | "raw string",             # optional — hashed + truncated
        "status": "ok" | "error:<msg>",              # only on phase=done
        "latency_ms": 1234.0                         # only on phase=done
      }

    Returns the authoritative ``event_id`` and ``correlation_id`` so the
    caller can stitch start/done pairs.
    """
    data = request.get_json(silent=True) or {}
    try:
        scenario_id = str(_required(data, "scenario_id")).strip()
        phase = str(_required(data, "phase")).strip()
        if phase not in ("start", "done"):
            raise ValueError("phase must be 'start' or 'done'")
        from_host = str(_required(data, "from_host")).strip()
        from_session = str(_required(data, "from_session")).strip()
        to_host = str(_required(data, "to_host")).strip()
        to_session = str(_required(data, "to_session")).strip()
    except ValueError as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=400,
            content_type="application/json",
        )

    correlation_id = str(data.get("correlation_id") or uuid.uuid4().hex)
    kind = str(data.get("kind") or "mcp_call")
    tool_name = str(data.get("tool_name") or "")
    digest, preview = _digest_payload(data.get("payload"))

    status = str(data.get("status") or "") if phase == "done" else ""
    try:
        latency_ms = float(data.get("latency_ms") or 0.0) if phase == "done" else 0.0
    except (TypeError, ValueError):
        latency_ms = 0.0

    msg = new_message(
        scenario_id=scenario_id,
        from_host=from_host,
        from_session=from_session,
        to_host=to_host,
        to_session=to_session,
        phase=phase,
        correlation_id=correlation_id,
        kind=kind,
        tool_name=tool_name,
        payload_preview=preview,
        payload_digest=digest,
        status=status,
        latency_ms=latency_ms,
    )
    try:
        get_store().append(msg)
    except Exception as exc:
        return Response(
            json.dumps({"error": f"ingest failed: {exc}"}),
            status=500,
            content_type="application/json",
        )

    return Response(
        json.dumps({
            "event_id": msg.event_id,
            "correlation_id": msg.correlation_id,
            "ts": msg.ts,
        }),
        content_type="application/json",
    )


# ──────────────────────────────────────────────────────────────────────────
# Read
# ──────────────────────────────────────────────────────────────────────────


@bp.route("/scenarios/<scenario_id>/inter-agent", methods=["GET"])
def list_inter_agent(scenario_id):
    """Return the stitched inter-agent edges for a scenario."""
    try:
        events = get_store().read_stitched(scenario_id)
    except Exception as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=500,
            content_type="application/json",
        )
    return Response(
        json.dumps({"scenario_id": scenario_id, "events": events}),
        content_type="application/json",
    )


@bp.route("/scenarios/<scenario_id>/inter-agent/raw", methods=["GET"])
def list_inter_agent_raw(scenario_id):
    """Return every start/done event as stored (no stitching) — debugging aid."""
    try:
        events = get_store().read(scenario_id)
    except Exception as exc:
        return Response(
            json.dumps({"error": str(exc)}),
            status=500,
            content_type="application/json",
        )
    return Response(
        json.dumps({
            "scenario_id": scenario_id,
            "events": [ev.to_dict() for ev in events],
        }),
        content_type="application/json",
    )
