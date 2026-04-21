"""Unit tests for the conversation adapter.

No Chimaera runtime is required: the adapter is pure Python operating on
plain dicts, so these tests use hand-built fixtures that mirror the shape
``chimaera_client.get_session_interactions`` and ``.get_context_graph``
return after flattening.

Scenarios covered:
  - parent session only
  - parent + one child
  - parent + two children
  - parent + child + grandchild  (``abc / abc.2 / abc.2.1``)

The grandchild test is the important one: it asserts role inference stays
flat (only the literal parent is ``orchestrator``; every descendant is
``subagent``) so the limitation is loud if anyone changes the heuristic.
"""

from __future__ import annotations

import json
import unittest

from context_visualizer.adapters.conversation_adapter import (
    base_session_id,
    build_agent_graph,
    build_conversation_summary,
    build_conversation_turns,
    build_interaction_detail,
    flatten_monitor_result,
    infer_role,
)


# ─────────────────────────────── fixture helpers ──────────────────────────────


def _anthropic_body(text: str = "hello", tool_name: str | None = None) -> str:
    """Build a tiny Anthropic-shaped response body as a JSON string."""
    content = [{"type": "text", "text": text}]
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


def _anthropic_request(tool_result_for: str | None = None) -> str:
    """Anthropic-shaped request body; optionally carrying a tool_result back."""
    messages = [{"role": "user", "content": "hi"}]
    if tool_result_for:
        messages = [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_result_for,
                "content": "result",
            }],
        }]
    return json.dumps({"messages": messages})


def _interaction(
    seq: int,
    *,
    timestamp: str,
    provider: str = "anthropic",
    model: str = "claude-3-5-sonnet",
    tool_name: str | None = None,
    tool_result_for: str | None = None,
) -> dict:
    return {
        "sequence_id": seq,
        "timestamp": timestamp,
        "provider": provider,
        "model": model,
        "request": {
            "method": "POST",
            "path": "/v1/messages",
            "headers": {},
            "body": _anthropic_request(tool_result_for=tool_result_for),
        },
        "response": {
            "status_code": 200,
            "body": _anthropic_body(tool_name=tool_name),
            "headers": {},
        },
    }


def _context_node(seq: int, *, latency_ms: float = 123.4, tokens: int = 15, cost: float = 0.01) -> dict:
    # Split the token total across input/output in a deterministic way so tests
    # that read back individual fields stay valid.
    return {
        "sequence_id": seq,
        "latency_ms": latency_ms,
        "delta_input_tokens": max(0, tokens - 5),
        "delta_output_tokens": min(5, tokens),
        "delta_cost_usd": cost,
        "model": "claude-3-5-sonnet",
    }


def _session(session_id: str, interactions: list[dict], context_nodes: list[dict]) -> dict:
    return {
        "session_id": session_id,
        "interactions": interactions,
        "context_nodes": context_nodes,
    }


# ───────────────────────────── pure helpers tests ─────────────────────────────


class TestSmallHelpers(unittest.TestCase):
    def test_base_session_id_strips_suffixes(self):
        self.assertEqual(base_session_id("abc"), "abc")
        self.assertEqual(base_session_id("abc.2"), "abc")
        self.assertEqual(base_session_id("abc.2.1"), "abc")
        self.assertEqual(base_session_id(""), "")

    def test_infer_role_flat_rule(self):
        self.assertEqual(infer_role("abc", "abc"), "orchestrator")
        self.assertEqual(infer_role("abc.2", "abc"), "subagent")
        # Grandchild must not be collapsed into orchestrator.
        self.assertEqual(infer_role("abc.2.1", "abc"), "subagent")

    def test_flatten_monitor_result_dict_and_strings(self):
        payload = {
            "c1": [json.dumps({"session_id": "a"}), {"session_id": "b"}],
            "c2": {"session_id": "c"},
        }
        out = flatten_monitor_result(payload)
        ids = sorted(o["session_id"] for o in out)
        self.assertEqual(ids, ["a", "b", "c"])


# ───────────────────────────── parent-only tests ──────────────────────────────


class TestParentOnly(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            _session(
                "abc",
                interactions=[
                    _interaction(0, timestamp="2026-04-20T12:00:00Z"),
                    _interaction(1, timestamp="2026-04-20T12:00:05Z"),
                ],
                context_nodes=[
                    _context_node(0, tokens=10, cost=0.01),
                    _context_node(1, tokens=20, cost=0.02),
                ],
            )
        ]

    def test_summary_counts_turns_and_bounds(self):
        summary = build_conversation_summary("abc", self.sessions)
        self.assertEqual(summary["conversationId"], "abc")
        self.assertEqual(summary["turnCount"], 2)
        self.assertEqual(summary["firstTurn"], "2026-04-20T12:00:00Z")
        self.assertEqual(summary["lastTurn"], "2026-04-20T12:00:05Z")

    def test_turns_are_initial_then_continuation(self):
        turns = build_conversation_turns("abc", self.sessions)
        self.assertEqual([t["turn_type"] for t in turns], ["initial", "continuation"])
        self.assertEqual([t["turn_number"] for t in turns], [0, 1])
        self.assertEqual(turns[1]["parent_interaction_id"], turns[0]["id"])

    def test_graph_single_node_no_edges(self):
        graph = build_agent_graph("abc", self.sessions)
        self.assertEqual(graph["conversation_id"], "abc")
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["session_id"], "abc")
        self.assertEqual(graph["nodes"][0]["agent_role"], "orchestrator")
        self.assertEqual(graph["nodes"][0]["interaction_count"], 2)
        self.assertEqual(graph["nodes"][0]["total_tokens"], 30)
        self.assertAlmostEqual(graph["nodes"][0]["total_cost_usd"], 0.03)
        self.assertEqual(graph["edges"], [])


# ──────────────────────────── parent + one child ──────────────────────────────


class TestParentPlusOneChild(unittest.TestCase):
    def setUp(self):
        parent = _session(
            "abc",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:00Z", tool_name="search"),
                _interaction(2, timestamp="2026-04-20T12:00:10Z"),
            ],
            context_nodes=[
                _context_node(0, tokens=10, cost=0.01),
                _context_node(2, tokens=15, cost=0.015),
            ],
        )
        child = _session(
            "abc.2",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:05Z"),
            ],
            context_nodes=[
                _context_node(0, tokens=8, cost=0.008),
            ],
        )
        self.sessions = [parent, child]

    def test_turns_mark_handoff_on_session_change(self):
        turns = build_conversation_turns("abc", self.sessions)
        types = [t["turn_type"] for t in turns]
        # abc(0) → abc.2(0) → abc(2)
        self.assertEqual(types, ["initial", "handoff", "handoff"])
        self.assertEqual([t["session_id"] for t in turns], ["abc", "abc.2", "abc"])

    def test_graph_has_two_nodes_two_edges(self):
        graph = build_agent_graph("abc", self.sessions)
        self.assertEqual({n["session_id"] for n in graph["nodes"]}, {"abc", "abc.2"})
        roles = {n["session_id"]: n["agent_role"] for n in graph["nodes"]}
        self.assertEqual(roles, {"abc": "orchestrator", "abc.2": "subagent"})

        # Two handoffs: abc → abc.2, then abc.2 → abc.
        self.assertEqual(len(graph["edges"]), 2)
        self.assertEqual(graph["edges"][0]["from_session_id"], "abc")
        self.assertEqual(graph["edges"][0]["to_session_id"], "abc.2")
        self.assertEqual(graph["edges"][1]["from_session_id"], "abc.2")
        self.assertEqual(graph["edges"][1]["to_session_id"], "abc")

    def test_summary_turn_count_spans_all_sessions(self):
        summary = build_conversation_summary("abc", self.sessions)
        self.assertEqual(summary["turnCount"], 3)


# ──────────────────────────── parent + two children ───────────────────────────


class TestParentPlusTwoChildren(unittest.TestCase):
    def setUp(self):
        parent = _session(
            "abc",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:00Z"),
            ],
            context_nodes=[_context_node(0, tokens=12)],
        )
        child2 = _session(
            "abc.2",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:05Z"),
                _interaction(1, timestamp="2026-04-20T12:00:15Z"),
            ],
            context_nodes=[_context_node(0, tokens=10), _context_node(1, tokens=10)],
        )
        child3 = _session(
            "abc.3",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:10Z"),
            ],
            context_nodes=[_context_node(0, tokens=8)],
        )
        self.sessions = [parent, child2, child3]

    def test_three_session_nodes_with_expected_roles(self):
        graph = build_agent_graph("abc", self.sessions)
        self.assertEqual(len(graph["nodes"]), 3)
        roles = {n["session_id"]: n["agent_role"] for n in graph["nodes"]}
        self.assertEqual(roles, {
            "abc": "orchestrator",
            "abc.2": "subagent",
            "abc.3": "subagent",
        })

    def test_chronological_ordering_drives_edges(self):
        # Expected order by timestamp: abc(0), abc.2(0), abc.3(0), abc.2(1)
        # → three handoffs: abc→abc.2, abc.2→abc.3, abc.3→abc.2.
        turns = build_conversation_turns("abc", self.sessions)
        order = [t["session_id"] for t in turns]
        self.assertEqual(order, ["abc", "abc.2", "abc.3", "abc.2"])

        graph = build_agent_graph("abc", self.sessions)
        edge_pairs = [(e["from_session_id"], e["to_session_id"]) for e in graph["edges"]]
        self.assertEqual(edge_pairs, [("abc", "abc.2"), ("abc.2", "abc.3"), ("abc.3", "abc.2")])


# ───────────────────────── parent + child + grandchild ────────────────────────


class TestGrandchildKeepsHeuristicHonest(unittest.TestCase):
    """If anyone ever changes role inference to be depth-sensitive, these assertions
    break loudly — which is the point.
    """

    def setUp(self):
        parent = _session(
            "abc",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:00Z"),
            ],
            context_nodes=[_context_node(0, tokens=5)],
        )
        child = _session(
            "abc.2",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:05Z"),
            ],
            context_nodes=[_context_node(0, tokens=5)],
        )
        grandchild = _session(
            "abc.2.1",
            interactions=[
                _interaction(0, timestamp="2026-04-20T12:00:10Z"),
            ],
            context_nodes=[_context_node(0, tokens=5)],
        )
        self.sessions = [parent, child, grandchild]

    def test_graph_still_builds_with_three_nodes(self):
        graph = build_agent_graph("abc", self.sessions)
        self.assertEqual(len(graph["nodes"]), 3)
        self.assertEqual(
            sorted(n["session_id"] for n in graph["nodes"]),
            ["abc", "abc.2", "abc.2.1"],
        )

    def test_grandchild_is_subagent_not_orchestrator(self):
        graph = build_agent_graph("abc", self.sessions)
        roles = {n["session_id"]: n["agent_role"] for n in graph["nodes"]}
        self.assertEqual(roles["abc"], "orchestrator")
        self.assertEqual(roles["abc.2"], "subagent")
        # The important assertion: grandchild is not silently treated as an
        # orchestrator, and not accidentally collapsed into the parent's bucket.
        self.assertEqual(roles["abc.2.1"], "subagent")

    def test_exactly_one_orchestrator_at_any_depth(self):
        graph = build_agent_graph("abc", self.sessions)
        orchestrators = [n for n in graph["nodes"] if n["agent_role"] == "orchestrator"]
        self.assertEqual(len(orchestrators), 1)
        self.assertEqual(orchestrators[0]["session_id"], "abc")


# ──────────────────────── interaction detail smoke test ───────────────────────


class TestInteractionDetail(unittest.TestCase):
    def test_detail_shape_matches_expected_keys(self):
        inter = _interaction(0, timestamp="2026-04-20T12:00:00Z", tool_name="search")
        ctx = _context_node(0, tokens=20, cost=0.02, latency_ms=456.0)
        detail = build_interaction_detail("abc", inter, ctx)

        # Spot-check the important fields.
        self.assertEqual(detail["id"], "abc:0")
        self.assertEqual(detail["session_id"], "abc")
        self.assertEqual(detail["provider"], "anthropic")
        self.assertEqual(detail["total_latency_ms"], 456.0)
        self.assertIsNotNone(detail["token_usage"])
        self.assertEqual(len(detail["tool_calls"]), 1)
        self.assertEqual(detail["tool_calls"][0]["name"], "search")
        self.assertEqual(detail["stream_chunks"], [])
        # Cost is intentionally client-computed; adapter never fabricates one.
        self.assertIsNone(detail["cost_estimate"])


if __name__ == "__main__":
    unittest.main()
