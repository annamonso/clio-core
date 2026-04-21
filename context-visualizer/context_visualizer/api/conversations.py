"""Workspace-view API endpoints.

Translates clio-core's session-centric data into the conversation-centric
shapes the React workspace view expects. All business logic lives in
``adapters.conversation_adapter``; this module only handles I/O (fetching
from ``chimaera_client``, normalizing monitor payloads, HTTP responses).

The base session id (everything before the first ``.`` in ``parent.N.M``
notation) is treated as the conversation id. See ``docs/workspace.md`` for
the rationale.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from .. import chimaera_client
from ..adapters.conversation_adapter import (
    base_session_id,
    build_agent_graph,
    build_conversation_summary,
    build_conversation_turns,
    build_interaction_detail,
    flatten_monitor_result,
)


bp = Blueprint("conversations", __name__)


# ─────────────────────────── chimaera fetch helpers ───────────────────────────


def _fetch_all_sessions() -> list[dict]:
    """Return every session the proxy knows about, as a list of dicts."""
    try:
        raw = chimaera_client.get_sessions()
    except Exception:
        return []
    return flatten_monitor_result(raw)


def _fetch_session_bundle(session_id: str) -> dict:
    """Fetch interactions + context graph nodes for a single session.

    Missing data (session with no interactions, runtime blips) degrades to
    empty lists; callers should not have to distinguish "empty" from "error".
    """
    try:
        raw_i = chimaera_client.get_session_interactions(session_id)
    except Exception:
        raw_i = None
    try:
        raw_n = chimaera_client.get_context_graph(session_id)
    except Exception:
        raw_n = None
    return {
        "session_id": session_id,
        "interactions": flatten_monitor_result(raw_i),
        "context_nodes": flatten_monitor_result(raw_n),
    }


def _fetch_conversation_tree(parent_id: str) -> list[dict]:
    """Fetch the parent session and every descendant (``parent.N``, ``parent.N.M``).

    Descendants are discovered by scanning the global session list for ids that
    begin with ``parent + "."``. The parent itself is always the first entry
    in the returned list — ordering matters to the adapter so it can treat the
    first node as the orchestrator.
    """
    sessions = _fetch_all_sessions()
    prefix = parent_id + "."
    descendant_ids = sorted(
        {
            s.get("session_id")
            for s in sessions
            if isinstance(s, dict)
            and isinstance(s.get("session_id"), str)
            and s.get("session_id", "").startswith(prefix)
        }
    )
    bundles = [_fetch_session_bundle(parent_id)]
    for sid in descendant_ids:
        bundles.append(_fetch_session_bundle(sid))
    return bundles


def _locate_interaction(interaction_id: str) -> tuple[dict | None, dict | None, str | None]:
    """Resolve an ``Interaction.id`` (``<session>:<seq>``) back to its raw records.

    Returns ``(interaction, context_node, session_id)``; any of them may be
    ``None`` if lookup fails. The UI's detail panel treats ``None`` as
    "interaction not found" and renders an error banner.
    """
    if not interaction_id or ":" not in interaction_id:
        return None, None, None
    session_id, _, seq_str = interaction_id.rpartition(":")
    try:
        seq = int(seq_str)
    except (TypeError, ValueError):
        return None, None, None

    bundle = _fetch_session_bundle(session_id)
    for inter in bundle["interactions"]:
        if isinstance(inter, dict) and inter.get("sequence_id") == seq:
            ctx = None
            for node in bundle["context_nodes"]:
                if isinstance(node, dict) and node.get("sequence_id") == seq:
                    ctx = node
                    break
            return inter, ctx, session_id
    return None, None, session_id


# ─────────────────────────────── route handlers ───────────────────────────────


@bp.route("/api/conversations")
def list_conversations():
    """``GET /api/conversations`` — one ``ConversationSummary`` per base session.

    Sessions are grouped by their base id; each group becomes a conversation.
    Token/cost aggregation is left to the per-conversation ``agent-graph``
    endpoint so listing stays cheap.
    """
    sessions = _fetch_all_sessions()

    conversations: dict[str, list[dict]] = {}
    for sess in sessions:
        if not isinstance(sess, dict):
            continue
        sid = sess.get("session_id")
        if not isinstance(sid, str) or not sid:
            continue
        conversations.setdefault(base_session_id(sid), []).append(sess)

    out = []
    for parent_id in sorted(conversations.keys()):
        tree = _fetch_conversation_tree(parent_id)
        summary = build_conversation_summary(parent_id, tree)
        out.append(summary)

    # Sort by lastTurn descending so the most recent conversation is first; empty
    # timestamps sort last.
    out.sort(key=lambda c: c.get("lastTurn", ""), reverse=True)
    return jsonify(out)


@bp.route("/_interceptor/conversations/<conversation_id>")
def get_conversation_turns(conversation_id):
    """``GET /_interceptor/conversations/<cid>`` — chronological ``ConversationTurn[]``.

    Path matches the source project so the React ``api.ts`` needs no change.
    """
    tree = _fetch_conversation_tree(conversation_id)
    turns = build_conversation_turns(conversation_id, tree)
    return jsonify(turns)


@bp.route("/api/conversations/<conversation_id>/agent-graph")
def get_agent_graph(conversation_id):
    """``GET /api/conversations/<cid>/agent-graph`` — ``AgentGraph`` for the tree."""
    tree = _fetch_conversation_tree(conversation_id)
    graph = build_agent_graph(conversation_id, tree)
    return jsonify(graph)


@bp.route("/api/interactions/<path:interaction_id>")
def get_interaction(interaction_id):
    """``GET /api/interactions/<iid>`` — full ``Interaction`` detail.

    ``path:`` converter is used because the composite id contains a colon.
    Returns 404 when the id does not resolve.
    """
    inter, ctx, session_id = _locate_interaction(interaction_id)
    if inter is None or session_id is None:
        return jsonify({"error": "interaction not found"}), 404
    return jsonify(build_interaction_detail(session_id, inter, ctx))
