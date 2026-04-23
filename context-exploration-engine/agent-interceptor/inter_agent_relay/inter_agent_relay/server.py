"""FastMCP server that logs inter-agent calls and proxies them over HTTP.

Configuration — all optional, read from env at startup so tool calls don't have
to repeat them:

    DTP_LEADER_URL        http://leader-host:5000   (required for ingest)
    DTP_SCENARIO_ID       expt-1                    (default scenario)
    DTP_FROM_HOST         ares-comp-11              (default caller host)
    DTP_FROM_SESSION      planner-a                 (default caller session)
    DTP_DEFAULT_PEER_PORT 5000
    DTP_HTTP_TIMEOUT      60                        (seconds)

The ``call_remote_agent`` tool uses Anthropic-format ``/v1/messages`` as the
wire protocol: it POSTs a one-shot user message to the peer's
``/_scenario/<sid>/_session/<to_session>/v1/messages`` URL on the peer's
leader Flask. That route is handled by the context-visualizer's llm_dispatch
and will record the interaction just like any normal claude CLI traffic.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional

import requests
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("inter-agent-relay")


# ──────────────────────────────────────────────────────────────────────────
# Environment defaults
# ──────────────────────────────────────────────────────────────────────────


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else default


def _leader_url() -> str:
    return _env("DTP_LEADER_URL").rstrip("/")


def _http_timeout() -> float:
    try:
        return float(_env("DTP_HTTP_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _default_peer_port() -> int:
    try:
        return int(_env("DTP_DEFAULT_PEER_PORT", "5000"))
    except ValueError:
        return 5000


# ──────────────────────────────────────────────────────────────────────────
# Ingest helpers
# ──────────────────────────────────────────────────────────────────────────


def _ingest(payload: dict) -> dict:
    """POST an event to the leader's inter-agent ingest endpoint.

    Failures are logged (returned as a dict) but never raise so the tool call
    still succeeds from the agent's perspective.
    """
    leader = _leader_url()
    if not leader:
        return {"ingest_error": "DTP_LEADER_URL not set"}
    try:
        r = requests.post(
            f"{leader}/api/_inter-agent/ingest",
            json=payload,
            timeout=_http_timeout(),
        )
        if not r.ok:
            return {"ingest_error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json() if r.text else {}
    except Exception as exc:
        return {"ingest_error": str(exc)}


def _resolve_defaults(
    scenario_id: Optional[str],
    from_host: Optional[str],
    from_session: Optional[str],
) -> tuple[str, str, str]:
    return (
        (scenario_id or _env("DTP_SCENARIO_ID")).strip(),
        (from_host or _env("DTP_FROM_HOST")).strip(),
        (from_session or _env("DTP_FROM_SESSION")).strip(),
    )


# ──────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────


@mcp.tool()
def log_remote_call_start(
    to_host: str,
    to_session: str,
    payload: Optional[str] = None,
    tool_name: str = "",
    scenario_id: Optional[str] = None,
    from_host: Optional[str] = None,
    from_session: Optional[str] = None,
) -> dict:
    """Record the start of an inter-agent call.

    Use when the remote transport is NOT HTTP (SSH, SLURM, shared filesystem,
    queue) — for plain HTTP use ``call_remote_agent`` instead.

    Returns ``{"correlation_id": "...", "event_id": "..."}``. Pass
    ``correlation_id`` to ``log_remote_call_done`` when the call completes.
    """
    sid, fh, fs = _resolve_defaults(scenario_id, from_host, from_session)
    corr = uuid.uuid4().hex
    body = {
        "scenario_id": sid,
        "phase": "start",
        "correlation_id": corr,
        "from_host": fh,
        "from_session": fs,
        "to_host": to_host,
        "to_session": to_session,
        "kind": "mcp_call",
        "tool_name": tool_name or "log_remote_call_start",
        "payload": payload,
    }
    result = _ingest(body)
    return {"correlation_id": corr, **result}


@mcp.tool()
def log_remote_call_done(
    correlation_id: str,
    status: str = "ok",
    latency_ms: float = 0.0,
    payload: Optional[str] = None,
    to_host: str = "",
    to_session: str = "",
    scenario_id: Optional[str] = None,
    from_host: Optional[str] = None,
    from_session: Optional[str] = None,
) -> dict:
    """Close out a previous start event.

    ``correlation_id`` must match the one returned by ``log_remote_call_start``.
    ``to_host`` / ``to_session`` are optional here — the store stitches them
    from the matching start event — but passing them makes the done event
    self-describing for audit trails.
    """
    sid, fh, fs = _resolve_defaults(scenario_id, from_host, from_session)
    body = {
        "scenario_id": sid,
        "phase": "done",
        "correlation_id": correlation_id,
        "from_host": fh,
        "from_session": fs,
        "to_host": to_host,
        "to_session": to_session,
        "kind": "mcp_call",
        "status": status,
        "latency_ms": latency_ms,
        "payload": payload,
    }
    return _ingest(body)


@mcp.tool()
def call_remote_agent(
    to_host: str,
    to_session: str,
    prompt: str,
    model: str = "claude-sonnet-4-5",
    max_tokens: int = 1024,
    api_key: Optional[str] = None,
    peer_port: Optional[int] = None,
    scenario_id: Optional[str] = None,
    from_host: Optional[str] = None,
    from_session: Optional[str] = None,
) -> dict:
    """Invoke a peer agent on another node and return its reply.

    Routing is through the peer's context-visualizer Flask at
    ``http://{to_host}:{peer_port}/_scenario/{scenario_id}/_session/{to_session}/v1/messages``.
    That route transparently captures the request (so the peer's LLM traffic
    is visible in the workspace view) and forwards to Anthropic.

    The same event is logged twice to the leader's inter-agent ingest: once
    at start, once at done (with latency + status).
    """
    sid, fh, fs = _resolve_defaults(scenario_id, from_host, from_session)
    port = peer_port or _default_peer_port()
    corr = uuid.uuid4().hex

    # 1) Emit start
    _ingest({
        "scenario_id": sid,
        "phase": "start",
        "correlation_id": corr,
        "from_host": fh,
        "from_session": fs,
        "to_host": to_host,
        "to_session": to_session,
        "kind": "mcp_call",
        "tool_name": "call_remote_agent",
        "payload": prompt,
    })

    # 2) Make the call
    url = f"http://{to_host}:{port}/_scenario/{sid}/_session/{to_session}/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        # Stamp caller host so the peer's InteractionRecord reflects "sent by fh".
        "X-Agent-Host": fh or "",
    }
    key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
    if key:
        headers["x-api-key"] = key
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    t0 = time.monotonic()
    status = "ok"
    reply_text: str = ""
    reply_json: Any = None
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=_http_timeout())
        if not resp.ok:
            status = f"error:HTTP {resp.status_code}"
            reply_text = resp.text[:1000]
        else:
            try:
                reply_json = resp.json()
                # Pull the first text block as a concise preview
                content = reply_json.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            reply_text = block.get("text", "")
                            break
                if not reply_text:
                    reply_text = resp.text[:1000]
            except Exception:
                reply_text = resp.text[:1000]
    except Exception as exc:
        status = f"error:{exc}"
    latency_ms = (time.monotonic() - t0) * 1000.0

    # 3) Emit done
    _ingest({
        "scenario_id": sid,
        "phase": "done",
        "correlation_id": corr,
        "from_host": fh,
        "from_session": fs,
        "to_host": to_host,
        "to_session": to_session,
        "kind": "mcp_call",
        "tool_name": "call_remote_agent",
        "status": status,
        "latency_ms": latency_ms,
        "payload": reply_text,
    })

    return {
        "status": status,
        "latency_ms": latency_ms,
        "correlation_id": corr,
        "reply_text": reply_text,
        "reply_json": reply_json,
    }


def main() -> None:
    """Entry point used by pyproject.toml's [project.scripts]."""
    mcp.run()


if __name__ == "__main__":
    main()
