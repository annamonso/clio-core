"""Parity tests: the conversation adapter vs. ``compute_workflow_graph``.

``docs/workspace.md`` defines a manual smoke check: after running a real
multi-agent scenario, node/edge/interaction counts from the adapter
(``/api/conversations/<cid>/agent-graph``) must agree with the numbers
``compute_workflow_graph`` produces for the same session tree.

That manual check cannot run without a live Chimaera runtime, so this file
encodes the *structural* version of the same assertions: fed identical
fixture data, the adapter's ``AgentGraph`` must be internally consistent
with the aggregate-call-graph view and with the raw interaction totals.
Any regression that drifts one representation from the other (e.g. the
adapter starts swallowing a session, or miscounts handoffs) trips these
tests before shipping.
"""

from __future__ import annotations

import json
import unittest

from context_visualizer.adapters.conversation_adapter import build_agent_graph
from context_visualizer.analysis.call_graph import compute_workflow_graph


def _body(tool_name: str | None = None) -> str:
    content = [{"type": "text", "text": "ok"}]
    if tool_name:
        content.append({
            "type": "tool_use",
            "id": f"tu_{tool_name}",
            "name": tool_name,
            "input": {"x": 1},
        })
    return json.dumps({
        "content": content,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


def _interaction(seq: int, ts: str, tool_name: str | None = None) -> dict:
    return {
        "sequence_id": seq,
        "timestamp": ts,
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
        "request": {
            "method": "POST",
            "path": "/v1/messages",
            "headers": {},
            "body": json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
        },
        "response": {
            "status_code": 200,
            "body": _body(tool_name=tool_name),
            "headers": {},
        },
    }


def _ctx(seq: int, latency_ms: float = 120.0, tokens: int = 15, cost: float = 0.01) -> dict:
    return {
        "sequence_id": seq,
        "latency_ms": latency_ms,
        "delta_input_tokens": max(0, tokens - 5),
        "delta_output_tokens": min(5, tokens),
        "delta_cost_usd": cost,
        "model": "claude-3-5-sonnet",
    }


def _adapter_fixture() -> tuple[str, list[dict]]:
    """Return ``(parent_id, sessions)`` in the shape the adapter expects."""
    parent = {
        "session_id": "abc",
        "interactions": [
            _interaction(0, "2026-04-20T12:00:00Z", tool_name="search"),
            _interaction(2, "2026-04-20T12:00:20Z"),
        ],
        "context_nodes": [_ctx(0), _ctx(2)],
    }
    child = {
        "session_id": "abc.2",
        "interactions": [
            _interaction(0, "2026-04-20T12:00:05Z"),
            _interaction(1, "2026-04-20T12:00:25Z"),
        ],
        "context_nodes": [_ctx(0), _ctx(1)],
    }
    grandchild = {
        "session_id": "abc.2.1",
        "interactions": [
            _interaction(0, "2026-04-20T12:00:10Z"),
        ],
        "context_nodes": [_ctx(0)],
    }
    return "abc", [parent, child, grandchild]


def _to_workflow_fixture(sessions: list[dict]) -> list[dict]:
    """Tag the adapter fixture with ``is_subagent`` for ``compute_workflow_graph``.

    The first session is treated as the orchestrator (matches the adapter's
    parent-is-first convention).
    """
    out = []
    for idx, sess in enumerate(sessions):
        out.append({
            **sess,
            "is_subagent": idx != 0,
        })
    return out


class TestAdapterParity(unittest.TestCase):
    """Structural parity between the adapter and ``compute_workflow_graph``."""

    def setUp(self):
        self.parent_id, self.sessions = _adapter_fixture()
        self.workflow_sessions = _to_workflow_fixture(self.sessions)

    def test_unique_sessions_match_workflow_agent_nodes(self):
        """Adapter nodes (one per session) == workflow agent/subagent nodes.

        ``compute_workflow_graph`` emits agent/subagent nodes plus a shared
        proxy + provider + model + tool fan-out; only the agent/subagent
        nodes represent distinct sessions. Both representations must see the
        same set of session identities.
        """
        graph = build_agent_graph(self.parent_id, self.sessions)
        adapter_sessions = {n["session_id"] for n in graph["nodes"]}

        wf = compute_workflow_graph(self.workflow_sessions)
        # Workflow agent node id is the literal "agent" for the parent; for
        # subagents it is ``subagent/<session_id>``. Invert that to recover
        # session ids.
        wf_sessions: set[str] = set()
        for node in wf["nodes"]:
            if node["type"] == "agent":
                wf_sessions.add(self.parent_id)
            elif node["type"] == "subagent":
                # id shape: "subagent/<session_id>"
                wf_sessions.add(node["id"].split("/", 1)[1])

        self.assertEqual(adapter_sessions, wf_sessions)

    def test_total_interaction_count_matches_input(self):
        """Sum of AgentNode.interaction_count == total interactions across sessions."""
        graph = build_agent_graph(self.parent_id, self.sessions)
        adapter_total = sum(n["interaction_count"] for n in graph["nodes"])
        input_total = sum(len(s["interactions"]) for s in self.sessions)
        self.assertEqual(adapter_total, input_total)

    def test_edge_count_equals_session_transitions(self):
        """Handoff edges == count of session transitions in the chronological stream.

        This is the structural analog of the "edge count matches handoffs"
        requirement in ``docs/workspace.md``. Computed independently from the
        input fixtures so the assertion fails loudly if the adapter stops
        treating session boundaries as handoff points.
        """
        # Build the expected chronological sequence of session ids from the
        # raw fixtures.
        events: list[tuple[str, str, int]] = []
        for sess in self.sessions:
            for inter in sess["interactions"]:
                events.append((
                    inter["timestamp"],
                    sess["session_id"],
                    inter["sequence_id"],
                ))
        events.sort()
        expected_transitions = sum(
            1 for a, b in zip(events, events[1:]) if a[1] != b[1]
        )

        graph = build_agent_graph(self.parent_id, self.sessions)
        self.assertEqual(len(graph["edges"]), expected_transitions)

    def test_workflow_graph_reports_same_aggregate_token_total(self):
        """Total tokens on the adapter nodes match the workflow's aggregate.

        The workflow graph aggregates tokens on each entity (agent, subagent,
        proxy, provider, model). The *per-agent* sum (agent + all subagents)
        equals the workflow's proxy node's total, which equals the adapter's
        summed per-session totals. If token accounting diverges, these
        representations fall out of sync and the UI starts lying.
        """
        graph = build_agent_graph(self.parent_id, self.sessions)
        adapter_tokens = sum(n["total_tokens"] for n in graph["nodes"])

        wf = compute_workflow_graph(self.workflow_sessions)
        # Proxy node sees every interaction exactly once, so its totalTokens
        # is the authoritative sum across all sessions.
        proxy_nodes = [n for n in wf["nodes"] if n["id"] == "proxy"]
        self.assertEqual(len(proxy_nodes), 1)
        proxy_tokens = proxy_nodes[0]["metrics"]["totalTokens"]

        self.assertEqual(adapter_tokens, proxy_tokens)


if __name__ == "__main__":
    unittest.main()
