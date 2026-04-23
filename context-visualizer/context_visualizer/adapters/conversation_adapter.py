"""Map clio-core sessions/interactions onto the workspace view's TypeScript shapes.

The workspace view (see ``docs/workspace.md``) expects conversation-centric shapes
borrowed from the agent-interception reference project:

    - ConversationSummary  { conversationId, turnCount, firstTurn, lastTurn }
    - ConversationTurn     { id, session_id, turn_number, turn_type, timestamp,
                             provider, model, parent_interaction_id,
                             context_metrics, response_text_preview, tool_calls,
                             total_latency_ms }
    - AgentGraph           { conversation_id, nodes, edges }
    - AgentNode            { session_id, agent_role, interaction_count,
                             total_tokens, total_cost_usd }
    - AgentEdge            { from_session_id, to_session_id, interaction_id,
                             turn_number, latency_ms }
    - Interaction          (full detail, see source/frontend/src/types.ts)

clio-core does not write an explicit ``conversation_id`` onto interactions. The
grouping key is the **base session id** — the prefix of a ``sid.N`` or
``sid.N.M`` identifier up to the first dot. Role inference follows one rule:
the base session is ``orchestrator``, any descendant is ``subagent``. Tool calls
are inspected from request/response bodies and stay inside the DetailPanel —
they are never promoted to graph nodes.

The pure-logic functions here take plain Python dicts so they can be unit-tested
without a live Chimaera runtime. ``api/conversations.py`` owns the I/O.
"""

from __future__ import annotations

import json
from typing import Any


# ───────────────────────────── small helpers ──────────────────────────────────


def _parse_body(body: Any) -> dict:
    """Return a dict view of a request/response body regardless of storage form.

    clio-core may store bodies as JSON strings or pre-parsed dicts; everything
    else degrades to an empty dict so downstream code never has to branch.
    """
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
    return body if isinstance(body, dict) else {}


def base_session_id(session_id: str) -> str:
    """Return the conversation-grouping key for a session id.

    The base id is the segment before the first ``.`` in clio-core's dot
    notation (``parent.N.M`` → ``parent``). Used everywhere the view needs a
    ``conversation_id`` that clio-core does not natively store.
    """
    if not session_id:
        return ""
    return session_id.split(".", 1)[0]


def infer_role(session_id: str, parent_id: str) -> str:
    """Classify a session as ``orchestrator`` or ``subagent``.

    The rule is deliberately flat: exactly one orchestrator per conversation
    (the base session), everything deeper is a subagent regardless of depth.
    The grandchild unit-test exists to make this flatness loud if anyone
    changes the heuristic to be depth-sensitive.
    """
    return "orchestrator" if session_id == parent_id else "subagent"


# ───────────────────────── tool-call & tool-result parsing ────────────────────


def _is_anthropic(provider: str) -> bool:
    return "anthropic" in (provider or "").lower()


def _is_openai_like(provider: str) -> bool:
    p = (provider or "").lower()
    return "openai" in p or "ollama" in p


def _extract_tool_calls(interaction: dict, response_body: dict, provider: str) -> list[dict]:
    """Pull tool-call blocks from a response body, falling back to pre-extracted lists.

    Anthropic stores tool calls as ``tool_use`` content blocks; OpenAI/Ollama
    use ``choices[0].message.tool_calls``. For streaming interactions the raw
    body may be empty, so we also accept the pre-extracted list stored under
    ``response.tool_calls``.
    """
    calls: list[dict] = []
    if _is_anthropic(provider):
        for block in response_body.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({
                    "id": block.get("id"),
                    "name": block.get("name", "?"),
                    "input": block.get("input", {}),
                })
    elif _is_openai_like(provider):
        choices = response_body.get("choices", []) or []
        if choices:
            tcs = (choices[0].get("message", {}) or {}).get("tool_calls") or []
            for tc in tcs:
                fn = tc.get("function", {}) or {}
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        args = {}
                calls.append({
                    "id": tc.get("id"),
                    "name": fn.get("name", "?"),
                    "input": args,
                })

    if not calls:
        pre = ((interaction.get("response") or {}).get("tool_calls") or [])
        calls = [
            {"id": tc.get("id"), "name": tc.get("name", "?"), "input": tc.get("input", {})}
            for tc in pre
        ]
    return calls


def _has_tool_result(request_body: dict, provider: str) -> bool:
    """Detect whether a request is carrying a prior tool's result back to the model.

    Used to mark a turn as ``tool_result`` rather than ``continuation``.
    """
    if _is_anthropic(provider):
        for msg in request_body.get("messages", []) or []:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
        return False
    if _is_openai_like(provider):
        for msg in request_body.get("messages", []) or []:
            if msg.get("role") == "tool":
                return True
    return False


def _response_text(response_body: dict, response: dict, provider: str) -> str | None:
    """Best-effort extraction of the assistant's textual reply.

    Prefers the pre-extracted ``response.text`` written by the Chimaera side,
    falling back to provider-specific body parsing.
    """
    text = (response or {}).get("text")
    if text:
        return text
    if _is_anthropic(provider):
        parts = [
            b.get("text", "") for b in (response_body.get("content", []) or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(p for p in parts if p) or None
    if _is_openai_like(provider):
        choices = response_body.get("choices", []) or []
        if choices:
            content = (choices[0].get("message", {}) or {}).get("content")
            return content or None
    return None


# ─────────────────────────── merged-turn construction ─────────────────────────


def _merge_chronological(sessions: list[dict]) -> list[dict]:
    """Interleave interactions from multiple sessions into one timestamp-ordered stream.

    Each ``sessions`` entry is ``{session_id, interactions, context_nodes}``.
    The returned list uses the source ``ConversationTurn`` shape, with
    ``turn_number`` set to the zero-based position in the merged stream and
    ``turn_type`` derived from neighbouring session transitions and tool-result
    blocks in the request.
    """
    entries: list[dict] = []
    for sess in sessions:
        sid = sess.get("session_id", "")
        ctxs = sess.get("context_nodes", []) or []
        ctx_by_seq = {n.get("sequence_id", -1): n for n in ctxs if isinstance(n, dict)}
        for inter in sess.get("interactions", []) or []:
            if not isinstance(inter, dict):
                continue
            seq = inter.get("sequence_id", 0)
            entries.append({
                "session_id": sid,
                "sequence_id": seq,
                "timestamp": inter.get("timestamp", ""),
                "interaction": inter,
                "ctx": ctx_by_seq.get(seq, {}) or {},
            })

    # Timestamp is the primary sort key; session id + sequence id break ties
    # deterministically so the playhead has a stable order.
    entries.sort(
        key=lambda e: (e["timestamp"], e["session_id"], e["sequence_id"])
    )

    merged: list[dict] = []
    prev_sid: str | None = None
    prev_id: str | None = None
    for idx, e in enumerate(entries):
        inter = e["interaction"]
        ctx = e["ctx"]
        provider = inter.get("provider", "unknown")
        request_body = _parse_body((inter.get("request") or {}).get("body"))
        response = inter.get("response") or {}
        response_body = _parse_body(response.get("body"))

        if prev_sid is None:
            turn_type = "initial"
        elif prev_sid != e["session_id"]:
            turn_type = "handoff"
        elif _has_tool_result(request_body, provider):
            turn_type = "tool_result"
        else:
            turn_type = "continuation"

        interaction_id = f"{e['session_id']}:{e['sequence_id']}"
        response_text = _response_text(response_body, response, provider)

        tool_calls = _extract_tool_calls(inter, response_body, provider)

        input_tokens = ctx.get("delta_input_tokens")
        output_tokens = ctx.get("delta_output_tokens")
        context_metrics = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": (input_tokens or 0) + (output_tokens or 0)
                if (input_tokens is not None or output_tokens is not None) else None,
            "cost_usd": ctx.get("delta_cost_usd"),
        }

        preview = None
        if response_text:
            preview = response_text[:240] + ("…" if len(response_text) > 240 else "")

        # Flat fields that the ported reference frontend reads directly on
        # ConversationTurn (in addition to the nested ``context_metrics``).
        # Keeping both so older consumers that already read context_metrics
        # don't break.
        status_code = (inter.get("response") or {}).get("status_code")
        resp = inter.get("response") or {}
        error_text: str | None = None
        if isinstance(resp.get("error"), str) and resp["error"]:
            error_text = resp["error"]
        elif isinstance(status_code, int) and status_code >= 400:
            # Surface the response text as the error blurb when we have no
            # explicit error field — most providers put the message there.
            error_text = response_text or None

        total_tokens_flat = context_metrics.get("total_tokens")

        merged.append({
            "id": interaction_id,
            "session_id": e["session_id"],
            "turn_number": idx,
            "turn_type": turn_type,
            "timestamp": e["timestamp"],
            "provider": provider,
            "model": ctx.get("model") or inter.get("model"),
            "parent_interaction_id": prev_id,
            "context_metrics": context_metrics,
            "response_text_preview": preview,
            "tool_calls": tool_calls,
            "total_latency_ms": ctx.get("latency_ms"),
            "status_code": status_code,
            "error": error_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens_flat,
            "total_cost_usd": ctx.get("delta_cost_usd"),
        })

        prev_sid = e["session_id"]
        prev_id = interaction_id

    return merged


# ───────────────────────────── public builders ────────────────────────────────


def build_conversation_summary(parent_id: str, sessions: list[dict]) -> dict:
    """Return a ``ConversationSummary`` for a parent + children session tree.

    ``turnCount`` is the total number of interactions across the tree;
    ``firstTurn`` / ``lastTurn`` are the earliest and latest interaction
    timestamps across that tree, as ISO strings (or ``""`` if none).
    """
    merged = _merge_chronological(sessions)
    timestamps = [m["timestamp"] for m in merged if m.get("timestamp")]
    return {
        "conversationId": parent_id,
        "turnCount": len(merged),
        "firstTurn": min(timestamps) if timestamps else "",
        "lastTurn": max(timestamps) if timestamps else "",
    }


def build_conversation_turns(parent_id: str, sessions: list[dict]) -> list[dict]:
    """Return the chronologically ordered list of ``ConversationTurn`` entries.

    ``parent_id`` is accepted for symmetry with the other builders but is not
    required for turn construction — turns are keyed by session id only.
    """
    del parent_id  # unused; kept for call-site symmetry
    return _merge_chronological(sessions)


def build_agent_graph(parent_id: str, sessions: list[dict]) -> dict:
    """Return an ``AgentGraph`` (nodes + edges) for the conversation.

    One node per unique session id with aggregated interaction/token/cost
    metrics; one edge per handoff turn (an edge from the previous session to
    the new one at the moment control transfers). The edge keeps the id and
    number of the turn that caused the handoff so the UI can seek to it.
    """
    nodes: list[dict] = []
    seen: set[str] = set()
    for sess in sessions:
        sid = sess.get("session_id", "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        inters = [i for i in (sess.get("interactions") or []) if isinstance(i, dict)]
        ctxs = [n for n in (sess.get("context_nodes") or []) if isinstance(n, dict)]
        ctx_by_seq = {n.get("sequence_id", -1): n for n in ctxs}

        total_tokens = 0
        total_cost = 0.0
        host_votes: dict[str, int] = {}
        scenario_votes: dict[str, int] = {}
        for inter in inters:
            ctx = ctx_by_seq.get(inter.get("sequence_id", -1), {})
            total_tokens += (ctx.get("delta_input_tokens") or 0)
            total_tokens += (ctx.get("delta_output_tokens") or 0)
            total_cost += ctx.get("delta_cost_usd") or 0.0
            h = inter.get("host")
            if isinstance(h, str) and h:
                host_votes[h] = host_votes.get(h, 0) + 1
            s = inter.get("scenario_id")
            if isinstance(s, str) and s:
                scenario_votes[s] = scenario_votes.get(s, 0) + 1

        host = max(host_votes.items(), key=lambda kv: kv[1])[0] if host_votes else ""
        scenario_id = (
            max(scenario_votes.items(), key=lambda kv: kv[1])[0]
            if scenario_votes else ""
        )

        nodes.append({
            "session_id": sid,
            "agent_role": infer_role(sid, parent_id),
            "interaction_count": len(inters),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "host": host,
            "scenario_id": scenario_id,
        })

    edges: list[dict] = []
    prev_sid: str | None = None
    for turn in _merge_chronological(sessions):
        sid = turn["session_id"]
        if prev_sid is not None and prev_sid != sid:
            edges.append({
                "kind": "handoff",
                "from_session_id": prev_sid,
                "to_session_id": sid,
                "interaction_id": turn["id"],
                "turn_number": turn["turn_number"],
                "latency_ms": turn.get("total_latency_ms"),
            })
        prev_sid = sid

    return {
        "conversation_id": parent_id,
        "nodes": nodes,
        "edges": edges,
    }


def build_interaction_detail(session_id: str, interaction: dict, context_node: dict | None) -> dict:
    """Build a full source ``Interaction`` record from one clio-core interaction.

    Fields that clio-core does not natively persist (per-chunk stream data,
    explicit cost estimate, time-to-first-token) are returned as ``None`` or
    empty lists; the UI tabs that consume them degrade gracefully when missing.
    Cost is *not* computed here — the client-side ``lib/cost.ts`` table owns
    that so prices can be updated without a Python release.
    """
    ctx = context_node or {}
    req = interaction.get("request") or {}
    resp = interaction.get("response") or {}
    request_body = _parse_body(req.get("body"))
    response_body = _parse_body(resp.get("body"))
    provider = interaction.get("provider", "unknown")

    # System prompt has different homes per provider.
    system_prompt: str | None = None
    if _is_anthropic(provider):
        system = request_body.get("system", "")
        if isinstance(system, list):
            parts = [b.get("text", "") for b in system if isinstance(b, dict)]
            system_prompt = " ".join(p for p in parts if p) or None
        elif isinstance(system, str) and system:
            system_prompt = system
    else:
        for msg in request_body.get("messages", []) or []:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    system_prompt = content
                    break

    token_usage: dict[str, Any] | None = None
    usage = response_body.get("usage") if isinstance(response_body, dict) else None
    delta_in = ctx.get("delta_input_tokens")
    delta_out = ctx.get("delta_output_tokens")
    if delta_in is not None or delta_out is not None or usage:
        token_usage = {
            "input_tokens": delta_in if delta_in is not None else (
                (usage or {}).get("input_tokens")
                or (usage or {}).get("prompt_tokens")
            ),
            "output_tokens": delta_out if delta_out is not None else (
                (usage or {}).get("output_tokens")
                or (usage or {}).get("completion_tokens")
            ),
            "cache_creation_tokens": (usage or {}).get("cache_creation_input_tokens"),
            "cache_read_tokens": (usage or {}).get("cache_read_input_tokens"),
            "total_tokens": (usage or {}).get("total_tokens"),
        }

    tool_calls = _extract_tool_calls(interaction, response_body, provider)

    return {
        "id": f"{session_id}:{interaction.get('sequence_id', 0)}",
        "session_id": session_id,
        "timestamp": interaction.get("timestamp", ""),
        "method": req.get("method", "POST"),
        "path": req.get("path", ""),
        "request_headers": req.get("headers", {}) or {},
        "request_body": request_body or None,
        "raw_request_body": (
            req.get("body") if isinstance(req.get("body"), str) else None
        ),
        "provider": provider,
        "model": ctx.get("model") or interaction.get("model"),
        "system_prompt": system_prompt,
        "messages": request_body.get("messages") if isinstance(request_body, dict) else None,
        "tools": request_body.get("tools") if isinstance(request_body, dict) else None,
        "image_metadata": None,
        "status_code": resp.get("status_code"),
        "response_headers": resp.get("headers", {}) or {},
        "response_body": response_body or None,
        "raw_response_body": (
            resp.get("body") if isinstance(resp.get("body"), str) else None
        ),
        "is_streaming": bool(interaction.get("is_streaming") or resp.get("is_streaming")),
        "stream_chunks": [],
        "response_text": _response_text(response_body, resp, provider),
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "cost_estimate": None,
        "time_to_first_token_ms": None,
        "total_latency_ms": ctx.get("latency_ms"),
        "error": resp.get("error"),
    }


# ─────────────── raw-shape normalization (I/O layer helper) ───────────────────


def flatten_monitor_result(raw: Any) -> list:
    """Turn a chimaera monitor result into a plain Python list of parsed items.

    clio-core's monitor returns ``{container_id: payload}``; ``payload`` is a
    list of dicts, a single dict, or a JSON string. This helper collapses the
    container layer and deserializes any JSON strings so the adapter only sees
    dicts.
    """
    if raw is None:
        return []

    def _parse_items(items: Any) -> list:
        if isinstance(items, list):
            out = []
            for item in items:
                if isinstance(item, str):
                    try:
                        out.append(json.loads(item))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                elif isinstance(item, dict):
                    out.append(item)
            return out
        if isinstance(items, dict):
            return [items]
        if isinstance(items, str):
            try:
                parsed = json.loads(items)
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
            return _parse_items(parsed)
        return []

    if isinstance(raw, dict):
        combined: list = []
        for _cid, payload in raw.items():
            combined.extend(_parse_items(payload))
        return combined
    return _parse_items(raw)
