"""Unit tests for the inter-agent store, Flask ingest blueprint, and scenario adapter.

No Chimaera runtime is required: the store is file-backed (JSONL under a
tempdir) and the adapter is pure Python on plain dicts.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from context_visualizer.inter_agent.store import (
    InterAgentStore,
    new_message,
)
from context_visualizer.adapters.scenario_adapter import (
    build_scenario_graph,
    build_scenario_summary,
    participants,
)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = InterAgentStore(root=Path(self._tmp.name))

    def _start(self, scenario, corr, **kw):
        return new_message(
            scenario_id=scenario,
            from_host=kw.get("from_host", "h1"),
            from_session=kw.get("from_session", "a"),
            to_host=kw.get("to_host", "h2"),
            to_session=kw.get("to_session", "b"),
            phase="start",
            correlation_id=corr,
            tool_name="call_remote_agent",
            payload_preview=kw.get("payload_preview", ""),
        )

    def _done(self, scenario, corr, **kw):
        return new_message(
            scenario_id=scenario,
            from_host=kw.get("from_host", "h1"),
            from_session=kw.get("from_session", "a"),
            to_host=kw.get("to_host", "h2"),
            to_session=kw.get("to_session", "b"),
            phase="done",
            correlation_id=corr,
            tool_name="call_remote_agent",
            status=kw.get("status", "ok"),
            latency_ms=kw.get("latency_ms", 42.0),
        )

    def test_append_and_list_scenarios(self):
        self.store.append(self._start("expt-1", "c1"))
        self.store.append(self._done("expt-1", "c1"))
        self.store.append(self._start("expt-2", "c2"))
        self.assertEqual(self.store.list_scenarios(), ["expt-1", "expt-2"])

    def test_stitch_start_and_done(self):
        self.store.append(self._start("expt", "corr-a", payload_preview="hello"))
        self.store.append(self._done("expt", "corr-a", latency_ms=123.5))
        merged = self.store.read_stitched("expt")
        self.assertEqual(len(merged), 1)
        ev = merged[0]
        self.assertEqual(ev["correlation_id"], "corr-a")
        self.assertEqual(ev["from_session"], "a")
        self.assertEqual(ev["to_session"], "b")
        self.assertIsNotNone(ev["ts_start"])
        self.assertIsNotNone(ev["ts_done"])
        self.assertEqual(ev["status"], "ok")
        self.assertAlmostEqual(ev["latency_ms"], 123.5)

    def test_stitch_inflight_kept(self):
        # Start with no matching done: still shows up with ts_done=None
        self.store.append(self._start("expt", "corr-b"))
        merged = self.store.read_stitched("expt")
        self.assertEqual(len(merged), 1)
        self.assertIsNone(merged[0]["ts_done"])

    def test_missing_scenario_id_rejected(self):
        msg = new_message(
            scenario_id="",
            from_host="h", from_session="a",
            to_host="h", to_session="b",
            phase="start", correlation_id="x",
        )
        with self.assertRaises(ValueError):
            self.store.append(msg)


class AdapterTests(unittest.TestCase):
    def test_participants_dedups_base_sessions(self):
        events = [
            {"from_session": "planner-a",   "to_session": "fetcher-b"},
            {"from_session": "planner-a.1", "to_session": "fetcher-b.2"},
        ]
        self.assertEqual(participants(events), ["fetcher-b", "planner-a"])

    def test_scenario_graph_aggregates_peer_metrics_and_host(self):
        bundles = [
            {
                "session_id": "planner-a",
                "interactions": [
                    {"sequence_id": 1, "host": "ares-11"},
                    {"sequence_id": 2, "host": "ares-11"},
                ],
                "context_nodes": [
                    {"sequence_id": 1, "delta_input_tokens": 100, "delta_output_tokens": 50},
                    {"sequence_id": 2, "delta_input_tokens": 40,  "delta_output_tokens": 10, "delta_cost_usd": 0.01},
                ],
            },
            {
                "session_id": "planner-a.1",
                "interactions": [{"sequence_id": 1, "host": "ares-11"}],
                "context_nodes": [{"sequence_id": 1, "delta_output_tokens": 5}],
            },
            {
                "session_id": "fetcher-b",
                "interactions": [{"sequence_id": 1, "host": "ares-12"}],
                "context_nodes": [{"sequence_id": 1, "delta_input_tokens": 70}],
            },
        ]
        events = [
            {
                "correlation_id": "c1", "scenario_id": "expt",
                "from_session": "planner-a", "to_session": "fetcher-b",
                "from_host": "ares-11", "to_host": "ares-12",
                "ts_start": "2026-04-22T10:00:00Z",
                "ts_done":  "2026-04-22T10:00:01Z",
                "status": "ok", "latency_ms": 123, "tool_name": "call_remote_agent",
                "payload_preview": "hi",
            },
        ]
        graph = build_scenario_graph("expt", bundles, events)

        self.assertEqual(graph["scenario_id"], "expt")
        self.assertEqual({a["agent_id"] for a in graph["agents"]}, {"planner-a", "fetcher-b"})

        planner = next(a for a in graph["agents"] if a["agent_id"] == "planner-a")
        fetcher = next(a for a in graph["agents"] if a["agent_id"] == "fetcher-b")

        # planner-a aggregates planner-a + planner-a.1
        self.assertEqual(planner["interaction_count"], 3)
        self.assertEqual(planner["total_tokens"], 100 + 50 + 40 + 10 + 5)
        self.assertAlmostEqual(planner["total_cost_usd"], 0.01)
        self.assertEqual(planner["host"], "ares-11")
        self.assertEqual(sorted(planner["sub_sessions"]), ["planner-a", "planner-a.1"])

        self.assertEqual(fetcher["host"], "ares-12")
        self.assertEqual(fetcher["interaction_count"], 1)

        # One inter-agent edge, correctly typed.
        self.assertEqual(len(graph["edges"]), 1)
        e = graph["edges"][0]
        self.assertEqual(e["kind"], "inter_agent_msg")
        self.assertEqual(e["from_session_id"], "planner-a")
        self.assertEqual(e["to_session_id"], "fetcher-b")
        self.assertEqual(e["from_host"], "ares-11")
        self.assertEqual(e["to_host"], "ares-12")

    def test_summary_counts_hosts_and_events(self):
        events = [
            {
                "from_host": "a", "to_host": "b",
                "from_session": "x", "to_session": "y",
                "ts_start": "2026-04-22T10:00:00Z", "ts_done": "2026-04-22T10:00:01Z",
            },
            {
                "from_host": "c", "to_host": "b",
                "from_session": "z", "to_session": "y",
                "ts_start": "2026-04-22T10:05:00Z", "ts_done": "2026-04-22T10:05:02Z",
            },
        ]
        s = build_scenario_summary("expt", events)
        self.assertEqual(s["agent_count"], 3)
        self.assertEqual(sorted(s["agents"]), ["x", "y", "z"])
        self.assertEqual(sorted(s["hosts"]), ["a", "b", "c"])
        self.assertEqual(s["event_count"], 2)
        self.assertEqual(s["firstEvent"], "2026-04-22T10:00:00Z")
        self.assertEqual(s["lastEvent"], "2026-04-22T10:05:02Z")


class IngestBlueprintTests(unittest.TestCase):
    """End-to-end: POST /api/_inter-agent/ingest then GET the stitched list."""

    def setUp(self):
        # Redirect the default store root to a tempdir for the duration of this test.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patcher = mock.patch.dict(os.environ, {"DTP_STATE_DIR": self._tmp.name})
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        # Reset the module-level singleton before the app is imported so it
        # picks up the patched env.
        from context_visualizer.inter_agent import store as store_mod
        store_mod._DEFAULT_STORE = None

        # Import the app lazily so the store singleton is built with our env.
        from context_visualizer.api.inter_agent import bp as inter_agent_bp
        from context_visualizer.api.scenarios import bp as scenarios_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(inter_agent_bp, url_prefix="/api")
        app.register_blueprint(scenarios_bp, url_prefix="/api")

        # Stub out chimaera fetches — we don't need the C++ runtime for this test.
        from context_visualizer.api import scenarios as scenarios_mod
        scenarios_mod.chimaera_client = mock.MagicMock()
        scenarios_mod.chimaera_client.get_sessions.return_value = {}
        scenarios_mod.chimaera_client.get_session_interactions.return_value = {}
        scenarios_mod.chimaera_client.get_context_graph.return_value = {}

        self.app = app
        self.client = app.test_client()

    def _post(self, **fields):
        return self.client.post(
            "/api/_inter-agent/ingest",
            data=json.dumps(fields),
            content_type="application/json",
        )

    def test_ingest_and_list(self):
        r1 = self._post(
            scenario_id="expt-x", phase="start",
            correlation_id="c-42",
            from_host="h1", from_session="a",
            to_host="h2", to_session="b",
            tool_name="call_remote_agent", payload="hi",
        )
        self.assertEqual(r1.status_code, 200, r1.data)
        body = r1.get_json()
        self.assertEqual(body["correlation_id"], "c-42")

        r2 = self._post(
            scenario_id="expt-x", phase="done",
            correlation_id="c-42",
            from_host="h1", from_session="a",
            to_host="h2", to_session="b",
            status="ok", latency_ms=57.0, payload="reply",
        )
        self.assertEqual(r2.status_code, 200, r2.data)

        r3 = self.client.get("/api/scenarios/expt-x/inter-agent")
        self.assertEqual(r3.status_code, 200)
        events = r3.get_json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "ok")
        self.assertAlmostEqual(events[0]["latency_ms"], 57.0)

    def test_missing_fields_rejected(self):
        r = self._post(scenario_id="expt", phase="start")
        self.assertEqual(r.status_code, 400)
        self.assertIn("missing", r.get_json()["error"].lower())

    def test_invalid_phase_rejected(self):
        r = self._post(
            scenario_id="expt", phase="bogus",
            from_host="h", from_session="a",
            to_host="h", to_session="b",
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
