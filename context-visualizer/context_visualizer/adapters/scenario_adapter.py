"""Map scenario-wide state (inter-agent events + per-peer session subtrees) onto a graph.

A "scenario" is the HPC analogue of a conversation but for *peer* agents: several
independent agents (each possibly an orchestrator with its own subagents) that
talk to one another via inter-agent calls. One such peer agent is rooted at its
base session id (``planner-a`` vs. ``planner-a.1`` handled via the existing
conversation adapter).

The scenario graph returned by ``build_scenario_graph`` therefore has:

    agents : list of peer-agent nodes (one per base session id participating
             in the scenario). Each agent aggregates interaction/token/cost
             metrics across its own subtree (orchestrator + subagents).
    edges  : one per stitched inter-agent call (start+done merged into one
             event). Kind is ``inter_agent_msg``.

Scenario membership for Phase 1 is defined by "any session named as
``from_session`` or ``to_session`` in an InterAgentMessage". Sessions with a
matching ``scenario_id`` on their InteractionRecord but no inter-agent events
will appear once Phase 2 walks interaction metadata.
"""

from __future__ import annotations

from typing import Iterable

from .conversation_adapter import (
    base_session_id,
    infer_role,
)


def _peer_bundle(
    peer_root: str,
    session_bundles_by_id: dict[str, dict],
) -> tuple[dict, list[str]]:
    """Aggregate one peer agent (base session + its subagents) from session bundles.

    Returns ``(agent_node, sub_session_ids)``. Missing session bundles are
    skipped silently — a peer can have been named in an inter-agent event
    before its first LLM turn lands.
    """
    interaction_count = 0
    total_tokens = 0
    total_cost = 0.0
    host_votes: dict[str, int] = {}
    sub_sessions: list[str] = []

    for sid, bundle in session_bundles_by_id.items():
        if sid != peer_root and not sid.startswith(peer_root + "."):
            continue
        sub_sessions.append(sid)
        inters = [i for i in (bundle.get("interactions") or []) if isinstance(i, dict)]
        ctxs = [n for n in (bundle.get("context_nodes") or []) if isinstance(n, dict)]
        ctx_by_seq = {n.get("sequence_id", -1): n for n in ctxs}

        interaction_count += len(inters)
        for inter in inters:
            ctx = ctx_by_seq.get(inter.get("sequence_id", -1), {})
            total_tokens += (ctx.get("delta_input_tokens") or 0)
            total_tokens += (ctx.get("delta_output_tokens") or 0)
            total_cost += ctx.get("delta_cost_usd") or 0.0
            h = inter.get("host")
            if isinstance(h, str) and h:
                host_votes[h] = host_votes.get(h, 0) + 1

    # Most-frequent host wins; ties broken by first-seen.
    host = ""
    if host_votes:
        host = max(host_votes.items(), key=lambda kv: kv[1])[0]

    sub_sessions.sort()

    node = {
        "agent_id": peer_root,
        "session_id": peer_root,
        "agent_role": "peer",  # peer == scenario-level role (not orchestrator/subagent)
        "host": host,
        "interaction_count": interaction_count,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "sub_sessions": sub_sessions,
    }
    return node, sub_sessions


def participants(inter_agent_events: Iterable[dict]) -> list[str]:
    """Return the set of peer agent roots named in any inter-agent event, sorted."""
    roots: set[str] = set()
    for ev in inter_agent_events:
        for key in ("from_session", "to_session"):
            sid = ev.get(key) if isinstance(ev, dict) else None
            if isinstance(sid, str) and sid:
                roots.add(base_session_id(sid))
    return sorted(roots)


def build_scenario_graph(
    scenario_id: str,
    session_bundles: list[dict],
    inter_agent_events: list[dict],
) -> dict:
    """Build a ``ScenarioGraph`` dict.

    Parameters
    ----------
    scenario_id
        The scenario tag.
    session_bundles
        Pre-fetched ``{session_id, interactions, context_nodes}`` for every
        session implicated in the scenario (peers + their subagents). Callers
        can over-fetch; extra sessions are ignored.
    inter_agent_events
        Stitched events from ``InterAgentStore.read_stitched``.
    """
    bundles_by_id = {b.get("session_id", ""): b for b in session_bundles if b.get("session_id")}
    peer_roots = participants(inter_agent_events)

    agents = []
    for root in peer_roots:
        node, _subs = _peer_bundle(root, bundles_by_id)
        agents.append(node)

    edges = []
    for ev in inter_agent_events:
        from_sid = ev.get("from_session", "")
        to_sid = ev.get("to_session", "")
        edges.append({
            "kind": "inter_agent_msg",
            "event_id": ev.get("correlation_id") or "",  # correlation_id is the stable key
            "correlation_id": ev.get("correlation_id", ""),
            "from_session_id": base_session_id(from_sid) if from_sid else "",
            "from_sub_session_id": from_sid,
            "to_session_id": base_session_id(to_sid) if to_sid else "",
            "to_sub_session_id": to_sid,
            "from_host": ev.get("from_host", ""),
            "to_host": ev.get("to_host", ""),
            "ts_start": ev.get("ts_start"),
            "ts_done": ev.get("ts_done"),
            "tool_name": ev.get("tool_name", ""),
            "status": ev.get("status", ""),
            "latency_ms": ev.get("latency_ms") or 0.0,
            "payload_preview": ev.get("payload_preview", ""),
        })

    return {
        "scenario_id": scenario_id,
        "agents": agents,
        "edges": edges,
    }


def build_scenario_summary(
    scenario_id: str,
    inter_agent_events: list[dict],
) -> dict:
    """Lightweight summary for the scenario list — no session fetches needed."""
    peers = participants(inter_agent_events)
    hosts = sorted({
        h for ev in inter_agent_events
        for h in (ev.get("from_host", ""), ev.get("to_host", ""))
        if h
    })
    first_ts = ""
    last_ts = ""
    for ev in inter_agent_events:
        for key in ("ts_start", "ts_done"):
            t = ev.get(key)
            if isinstance(t, str) and t:
                if not first_ts or t < first_ts:
                    first_ts = t
                if not last_ts or t > last_ts:
                    last_ts = t
    return {
        "scenario_id": scenario_id,
        "agent_count": len(peers),
        "agents": peers,
        "hosts": hosts,
        "event_count": len(inter_agent_events),
        "firstEvent": first_ts,
        "lastEvent": last_ts,
    }
