"""Flask blueprint: HTTP bridge from agent requests to Chimaera Monitor dispatch.

Translates agent HTTP requests into pool_stats://800.0:local:<json> Monitor
queries that land in the proxy ChiMod's Monitor handler on a Chimaera worker.
"""

import concurrent.futures as _futures
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime

from flask import Blueprint, Response, request

from .. import chimaera_client

bp = Blueprint("llm_dispatch", __name__)

# Maps session_id → {fingerprint → resolved_session_id}
_session_conv_map: dict = {}
# Maps session_id → next sub-session counter (starts at 2)
_session_counter: dict = {}
_session_lock = threading.Lock()

# Thread pool for background checkpoint work
_checkpoint_executor = _futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="dtp-ckpt")


def _conversation_fingerprint(body_text: str) -> str:
    """Stable fingerprint for the start of a conversation from a raw request body."""
    try:
        body = json.loads(body_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""

    system = body.get("system", "")
    if isinstance(system, list):
        system = "\x00".join(
            b.get("text", "") for b in system if isinstance(b, dict)
        )

    messages = body.get("messages", [])
    first_content = ""
    if messages:
        c = messages[0].get("content", "")
        if isinstance(c, str):
            first_content = c
        elif isinstance(c, list):
            first_content = "\x00".join(
                b.get("text", "") for b in c if isinstance(b, dict)
            )

    raw = system + "\x00" + first_content
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _resolve_session(session_id: str, body_text: str) -> str:
    """
    Return the actual session ID to use for this request.
    The first conversation on a session keeps the original ID.
    Each new conversation fingerprint gets session_id.N (N=2,3,...).
    """
    fp = _conversation_fingerprint(body_text)
    if not fp:
        return session_id

    with _session_lock:
        conv_map = _session_conv_map.setdefault(session_id, {})
        if fp in conv_map:
            return conv_map[fp]

        if not conv_map:
            resolved = session_id
        else:
            n = _session_counter.get(session_id, 2)
            resolved = f"{session_id}.{n}"
            _session_counter[session_id] = n + 1

        conv_map[fp] = resolved
        return resolved


def _extract_token_count(response_body: str, provider: str) -> int:
    """Extract token count from LLM response body."""
    try:
        body = json.loads(response_body)
    except Exception:
        return 0
    if provider == "anthropic":
        usage = body.get("usage", {})
        return usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    usage = body.get("usage", {})
    return usage.get("total_tokens", 0) or (
        usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    )


def _auto_checkpoint(session_id: str, response_body: str, provider: str, latency_ms: float):
    """Run in background: detect natural breakpoint and create checkpoint."""
    try:
        from ..checkpointing.checkpoint_manager import manager
        from .. import chimaera_client as _cc
        import time as _time
        _time.sleep(0.15)  # let tracker finish writing
        seq_id = _cc.get_latest_sequence_id(session_id)
        if seq_id > 0:
            token_count = _extract_token_count(response_body, provider)
            manager.detect_and_create(session_id, seq_id, response_body, provider, token_count, latency_ms)
    except Exception:
        pass


def _run_semantic_checks(session_id: str, request_body: str, response_body: str, provider: str):
    """Run in background: execute per_query semantic checks and emit recovery events.

    Skips silently if no checks are configured or the Anthropic client is unavailable.
    For every check that fails with severity='error' a recovery event is stored in CTE
    so that the agent is notified on its next request.
    """
    try:
        from ..semantic.checker import get_checker
        from .. import chimaera_client as _cc
        import time as _time

        checker = get_checker()
        if not checker._config.checks:
            return

        # Give the tracker a moment to record the interaction before we fetch seq_id
        _time.sleep(0.20)
        seq_id = _cc.get_latest_sequence_id(session_id)

        # Extract text from request and response bodies
        request_text = _messages_text(request_body)
        response_text = _response_text(response_body, provider)

        batch = checker.run_checks(
            session_id, seq_id, request_text, response_text, trigger="per_query"
        )

        for failure in batch.error_failures:
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": "semantic_check_failure",
                "source_session_id": session_id,
                "source_sequence_id": seq_id,
                "target_session_id": session_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "acknowledged": False,
                "payload": {
                    "error_type": "semantic_check",
                    "check_name": failure.check_name,
                    "description": failure.explanation,
                    "confidence": failure.confidence,
                    "error_introduced_at_sequence": failure.error_introduced_at_sequence,
                },
            }
            try:
                _cc.store_recovery_event(event)
            except Exception:
                pass
    except Exception:
        pass


def _messages_text(body_text: str) -> str:
    """Extract the last few messages from a request body as plain text."""
    try:
        body = json.loads(body_text)
        messages = body.get("messages", [])
        parts = []
        for msg in messages[-3:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            parts.append(f"{role}: {content}")
        return "\n".join(parts)
    except Exception:
        return ""


def _response_text(body_text: str, provider: str) -> str:
    """Extract the assistant's text from a response body."""
    try:
        body = json.loads(body_text)
        if provider == "anthropic":
            for block in body.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    return block.get("text", "")
        else:
            choices = body.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "")
    except Exception:
        pass
    return ""


def _inject_recovery_context(session_id: str, body_text: str, provider: str) -> str:
    """Inject pending recovery signals and replay context into the system prompt.

    Returns the (possibly modified) body JSON string.
    Skips injection silently on any error or timeout.
    """
    from ..checkpointing.checkpoint_manager import manager

    # Check for pending replay first
    replay = manager.consume_replay(session_id)
    preambles = []

    if replay is not None:
        preambles.append(manager.build_replay_injection(replay))

    # Then check for recovery events
    try:
        events = chimaera_client.get_recovery_events(session_id)
    except Exception:
        events = []

    pending = [e for e in events if not e.get("acknowledged", False)]
    if pending:
        lines = [
            "[DTProvenance Recovery Context]",
            f"Your session ID: {session_id}",
            "Pending errors reported about your output:",
        ]
        for ev in pending:
            payload = ev.get("payload", {})
            src = ev.get("source_session_id", "?")
            seq = ev.get("source_sequence_id", "?")
            desc = payload.get("description", ev.get("event_type", ""))
            lines.append(f"- [{ev.get('event_type', 'event')} from {src} @ seq {seq}]: {desc}")

        lines += [
            "",
            "To propagate an error to another agent, include in your response:",
            '<recovery_signal>{"type":"error_report","target_session":"<sid>","error_type":"code_error|incorrect_information|logical_error|tool_failure","description":"<description>"}</recovery_signal>',
        ]
        preambles.append("\n".join(lines))

    if not preambles:
        return body_text

    preamble = "\n\n".join(preambles)

    try:
        body = json.loads(body_text)
    except Exception:
        return body_text

    if provider == "anthropic":
        system = body.get("system", "")
        if isinstance(system, list):
            # Append as final text block.  Anthropic requires blocks with
            # cache_control to precede uncached blocks; prepending an uncached
            # preamble block before a cached original block violates that rule
            # and causes a 400 invalid_request_error.
            body["system"] = system + [{"type": "text", "text": preamble}]
        else:
            body["system"] = preamble + ("\n\n" + system if system else "")
    elif provider in ("openai", "ollama"):
        messages = body.get("messages", [])
        # Prepend system message (or insert before first non-system)
        body["messages"] = [{"role": "system", "content": preamble}] + messages

    return json.dumps(body)


def _extract_recovery_signals(
    body_str: str, session_id: str, provider: str, content_type: str
) -> tuple[str, list]:
    """Extract <recovery_signal> tags from response body.

    Returns (cleaned_body_str, list_of_event_dicts).
    Skips streaming responses.
    """
    if "text/event-stream" in content_type:
        return body_str, []

    pattern = re.compile(r"<recovery_signal>(.*?)</recovery_signal>", re.DOTALL)

    # Find the text field(s) based on provider
    try:
        body = json.loads(body_str)
    except Exception:
        return body_str, []

    signals = []
    modified = False

    def _process_text(text: str) -> str:
        nonlocal modified
        found = pattern.findall(text)
        if not found:
            return text
        for raw in found:
            try:
                sig_data = json.loads(raw.strip())
            except Exception:
                sig_data = {"description": raw.strip()}
            event = {
                "event_id": str(uuid.uuid4()),
                "event_type": sig_data.get("type", "error_report"),
                "source_session_id": session_id,
                "source_sequence_id": 0,
                "target_session_id": sig_data.get("target_session", ""),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "acknowledged": False,
                "payload": {
                    "error_type": sig_data.get("error_type", "code_error"),
                    "description": sig_data.get("description", ""),
                    "suggest_restore_to_sequence": sig_data.get("suggest_restore_to_sequence"),
                },
            }
            signals.append(event)
        cleaned = pattern.sub("", text).strip()
        modified = True
        return cleaned

    if provider == "anthropic":
        content = body.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = _process_text(block.get("text", ""))
    elif provider in ("openai", "ollama"):
        choices = body.get("choices", [])
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message", {})
            if isinstance(msg.get("content"), str):
                msg["content"] = _process_text(msg["content"])

    if modified:
        return json.dumps(body), signals
    return body_str, signals


# Hop-by-hop headers to strip (must not be forwarded)
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "te", "trailers",
    "transfer-encoding", "upgrade", "host",
    "content-length", "accept-encoding", "content-encoding",
    # Custom CEE headers — consumed by the bridge, not meaningful upstream
    "x-agent-host",
})

# Session requirement message for agents without /_session/ prefix
_SESSION_MSG = (
    "DTProvenance proxy requires a session ID. "
    "Set ANTHROPIC_BASE_URL to http://<host>:<port>/_session/<your-session-id>"
)


def _detect_provider(path, headers):
    """Detect LLM provider from request path and headers (mirrors C++ DetectProvider)."""
    if path.startswith("/_interceptor"):
        return "unknown"
    if path.startswith("/api/"):
        return "ollama"
    if path == "/v1/messages" or path.startswith("/v1/messages?"):
        return "anthropic"
    if path.startswith("/v1/"):
        if "anthropic-version" in headers:
            return "anthropic"
        return "openai"
    return "unknown"


def _build_session_rejection(provider):
    """Build a provider-appropriate rejection response for missing session."""
    if provider == "anthropic":
        return json.dumps({
            "id": "msg_session_required",
            "type": "message",
            "role": "assistant",
            "model": "dt-provenance-proxy",
            "content": [{"type": "text", "text": _SESSION_MSG}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })
    elif provider == "openai":
        return json.dumps({
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": _SESSION_MSG},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })
    elif provider == "ollama":
        return json.dumps({
            "message": {"role": "assistant", "content": _SESSION_MSG},
            "done": True,
        })
    else:
        return json.dumps({
            "error": {"code": -32000, "message": _SESSION_MSG},
        })


# ── URL form reference ──────────────────────────────────────────────────────
#
# Optional prefixes, in this order, all independent:
#
#   /_host/<agent_host>/            ← stamps host on the InteractionRecord
#   /_scenario/<scenario_id>/       ← stamps scenario_id
#   /_session/<session_id>/         ← required; everything below is session
#
# Examples:
#   /_session/my-sid/v1/messages                                            (legacy)
#   /_scenario/expt-1/_session/planner-a/v1/messages                        (scenario only)
#   /_host/ares-comp-12/_session/fetcher-b/v1/messages                      (host only)
#   /_host/ares-comp-12/_scenario/expt-1/_session/fetcher-b/v1/messages    (both)
#
# The host prefix exists because the claude CLI cannot set custom headers
# per-request. On HPC we want agents on different compute nodes to self-identify.
# A wrapper script setting ANTHROPIC_BASE_URL to include `/_host/$(hostname)/`
# is the cleanest way.


@bp.route("/_host/<agent_host>/_scenario/<scenario_id>/_session/<session_id>/", defaults={"subpath": ""}, methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
@bp.route("/_host/<agent_host>/_scenario/<scenario_id>/_session/<session_id>/<path:subpath>", methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
def forward_request_with_host_and_scenario(agent_host, scenario_id, session_id, subpath):
    return _forward_request_impl(session_id, subpath,
                                 scenario_id=scenario_id, agent_host=agent_host)


@bp.route("/_host/<agent_host>/_session/<session_id>/", defaults={"subpath": ""}, methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
@bp.route("/_host/<agent_host>/_session/<session_id>/<path:subpath>", methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
def forward_request_with_host(agent_host, session_id, subpath):
    return _forward_request_impl(session_id, subpath,
                                 scenario_id="", agent_host=agent_host)


@bp.route("/_scenario/<scenario_id>/_session/<session_id>/", defaults={"subpath": ""}, methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
@bp.route("/_scenario/<scenario_id>/_session/<session_id>/<path:subpath>", methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
def forward_request_with_scenario(scenario_id, session_id, subpath):
    """Scenario-aware variant: stamps scenario_id on every InteractionRecord."""
    return _forward_request_impl(session_id, subpath, scenario_id=scenario_id)


@bp.route("/_session/<session_id>/", defaults={"subpath": ""}, methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
@bp.route("/_session/<session_id>/<path:subpath>", methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"])
def forward_request(session_id, subpath):
    """Translate agent HTTP request into Chimaera Monitor query."""
    return _forward_request_impl(session_id, subpath, scenario_id="")


def _forward_request_impl(session_id, subpath, scenario_id="", agent_host=""):
    path = "/" + subpath if subpath else "/"

    # Detect provider from path/headers
    headers_dict = {k.lower(): v for k, v in request.headers}
    provider = _detect_provider(path, headers_dict)

    if provider == "unknown":
        # Default to anthropic for unrecognized paths (agent SDK uses /v1/messages
        # but may send probes to the base URL)
        provider = "anthropic"

    # Filter hop-by-hop headers
    clean_headers = {
        k: v for k, v in request.headers
        if k.lower() not in _HOP_BY_HOP
    }

    # Resolve session ID (splits subagent conversations into child sessions)
    body_text = request.get_data(as_text=True)
    original_body_text = body_text  # preserve pre-injection copy for semantic checks
    actual_session_id = _resolve_session(session_id, body_text)

    # Inject pending recovery signals into system prompt.
    # Use the base session_id (pre-resolution) so that events targeting the
    # logical agent identity are injected into all its sub-conversations.
    body_text = _inject_recovery_context(session_id, body_text, provider)

    # Record start time for latency measurement
    start_time = time.monotonic()

    # Agent-reported host (optional; falls back to interceptor's own host on C++ side).
    # URL prefix /_host/<h>/ wins; X-Agent-Host header (useful to the MCP relay)
    # is the fallback.
    if not agent_host:
        agent_host = headers_dict.get("x-agent-host", "")

    # Submit to proxy ChiMod via pool_stats:// Monitor query
    try:
        result = chimaera_client.forward_llm_request(
            session_id=actual_session_id,
            provider=provider,
            path=path,
            headers=clean_headers,
            body=body_text,
            timeout=300,
            scenario_id=scenario_id,
            agent_host=agent_host,
        )
    except Exception as exc:
        return Response(
            json.dumps({"error": f"Chimaera dispatch failed: {exc}"}),
            status=502,
            content_type="application/json",
        )

    # Extract response from container results
    resp = None
    for _cid, data in result.items():
        resp = data
        break

    if resp is None or not isinstance(resp, dict):
        return Response(
            json.dumps({"error": "empty response from proxy ChiMod"}),
            status=502,
            content_type="application/json",
        )

    status = resp.get("status", 502)
    body = resp.get("body", "")

    # Parse response headers from the upstream
    content_type = "application/json"
    resp_headers = {}
    headers_str = resp.get("headers", "{}")
    if isinstance(headers_str, str):
        try:
            resp_headers = json.loads(headers_str)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(headers_str, dict):
        resp_headers = headers_str

    # Extract content-type, strip hop-by-hop
    for k, v in resp_headers.items():
        if k.lower() == "content-type":
            content_type = v
        elif k.lower() not in _HOP_BY_HOP:
            pass  # Could add to response headers if needed

    # Extract and store recovery signals from response body
    if status >= 200 and status < 300:
        body, signals = _extract_recovery_signals(body, actual_session_id, provider, content_type)
        for sig in signals:
            try:
                chimaera_client.store_recovery_event(sig)
            except Exception:
                pass

        # Submit background checkpoint detection
        latency_ms = (time.monotonic() - start_time) * 1000
        _checkpoint_executor.submit(_auto_checkpoint, actual_session_id, body, provider, latency_ms)

        # Submit background semantic checks (no-op if no config or no API key)
        _checkpoint_executor.submit(
            _run_semantic_checks, actual_session_id, original_body_text, body, provider
        )

    return Response(body, status=status, content_type=content_type)


@bp.route("/_test/process_llm_event", methods=["POST"])
def test_process_llm_event():
    """Test-only endpoint: run injection + extraction without a real upstream.

    Accepts JSON body:
      {
        "session_id":    str,
        "provider":      "anthropic" | "openai" | "ollama",  (default: anthropic)
        "request_body":  str  (JSON string sent to the LLM),
        "response_body": str  (JSON string the LLM would have returned)
      }

    Returns:
      {
        "injected_request":  str,   # request body after injection
        "cleaned_response":  str,   # response body after signal stripping
        "signals":           list,  # extracted recovery event dicts
        "stored_blobs":      list   # blob names written to CTE (or error strings)
      }
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "test-session")
    provider = data.get("provider", "anthropic")
    req_body = data.get("request_body", "{}")
    resp_body = data.get("response_body", "{}")

    injected_req = _inject_recovery_context(session_id, req_body, provider)

    cleaned_resp, signals = _extract_recovery_signals(
        resp_body, session_id, provider, "application/json"
    )

    stored_blobs = []
    for sig in signals:
        try:
            blob_name = chimaera_client.store_recovery_event(sig)
            stored_blobs.append(blob_name)
        except Exception as exc:
            stored_blobs.append(f"error: {exc}")

    return Response(
        json.dumps({
            "injected_request": injected_req,
            "cleaned_response": cleaned_resp,
            "signals": signals,
            "stored_blobs": stored_blobs,
        }),
        content_type="application/json",
    )


@bp.route("/v1/messages", methods=["POST"])
@bp.route("/v1/chat/completions", methods=["POST"])
def no_session_api():
    """API calls without /_session/ prefix get a fake rejection."""
    headers_dict = {k.lower(): v for k, v in request.headers}
    provider = _detect_provider(request.path, headers_dict)
    return Response(
        _build_session_rejection(provider),
        status=200,
        content_type="application/json",
    )
