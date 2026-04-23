"""Flask blueprint: scenario listing + per-scenario peer-agent graph.

Reads from two sources:
  - ``inter_agent.InterAgentStore`` — the set of scenarios and their edges.
  - The existing proxy ``list_sessions`` + ``query_session`` pipeline for
    per-peer interaction aggregation.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from .. import chimaera_client
from ..adapters.conversation_adapter import (
    base_session_id,
    flatten_monitor_result,
)
from ..adapters.scenario_adapter import (
    build_scenario_graph,
    build_scenario_summary,
    participants,
)
from ..inter_agent import get_store


bp = Blueprint("scenarios", __name__)


# ─────────────────────────── chimaera fetch helpers ───────────────────────────


def _fetch_all_sessions() -> list[dict]:
    try:
        raw = chimaera_client.get_sessions()
    except Exception:
        return []
    return flatten_monitor_result(raw)


def _fetch_session_bundle(session_id: str) -> dict:
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


def _fetch_peer_subtrees(peer_roots: list[str]) -> list[dict]:
    """For each peer root, fetch its full orchestrator+subagent session subtree."""
    if not peer_roots:
        return []
    all_sessions = _fetch_all_sessions()
    known_ids = {
        s.get("session_id") for s in all_sessions
        if isinstance(s, dict) and isinstance(s.get("session_id"), str)
    }
    targets: set[str] = set()
    for root in peer_roots:
        targets.add(root)
        prefix = root + "."
        for sid in known_ids:
            if isinstance(sid, str) and sid.startswith(prefix):
                targets.add(sid)

    bundles: list[dict] = []
    for sid in sorted(targets):
        bundles.append(_fetch_session_bundle(sid))
    return bundles


# ─────────────────────────────── route handlers ───────────────────────────────


@bp.route("/scenarios", methods=["GET"])
def list_scenarios():
    """``GET /api/scenarios`` — summary per scenario seen in the inter-agent store."""
    store = get_store()
    ids = store.list_scenarios()
    out = []
    for sid in ids:
        events = store.read_stitched(sid)
        out.append(build_scenario_summary(sid, events))
    # Most-recently-active scenario first.
    out.sort(key=lambda s: s.get("lastEvent", ""), reverse=True)
    return jsonify(out)


@bp.route("/scenarios/<scenario_id>", methods=["GET"])
def get_scenario(scenario_id):
    """``GET /api/scenarios/<sid>`` — scenario summary (same shape as list entry)."""
    store = get_store()
    events = store.read_stitched(scenario_id)
    return jsonify(build_scenario_summary(scenario_id, events))


@bp.route("/scenarios/<scenario_id>/graph", methods=["GET"])
def get_scenario_graph(scenario_id):
    """``GET /api/scenarios/<sid>/graph`` — peer-agent graph + inter-agent edges."""
    store = get_store()
    events = store.read_stitched(scenario_id)
    peer_roots = participants(events)
    bundles = _fetch_peer_subtrees(peer_roots)
    graph = build_scenario_graph(scenario_id, bundles, events)
    return jsonify(graph)
