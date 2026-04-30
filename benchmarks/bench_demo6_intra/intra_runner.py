"""One end-to-end intra-agent fan-out run for Test 6.

Workload: a single planner agent on PLANNER_HOST is asked to issue N Bash
tool calls in a SINGLE LLM turn, then summarize. This stresses the framework's
ability to capture concurrent tool_calls cleanly under within-agent fan-out
(no LLM call per tool — Claude Code's harness dispatches the N tool_use blocks
concurrently against Bash on the host).

The framework exposes interactions with nested `response.tool_calls: ToolCall[]`
(see context-exploration-engine/agent-interceptor/protocol/include/dt_provenance/
protocol/interaction.h). There are no first-class spans / parent_id; this
runner enumerates per-interaction tool_calls and counts them, checks id
uniqueness, and checks single-interaction containment.

Required env (no defaults — caller must export):
    LEADER_HOST       e.g. "ares-comp-12"
    LEADER_PORT       e.g. "5050"
    LEADER_JOB        SLURM jobid for the leader allocation
    PLANNER_HOST      e.g. "ares-comp-13"
    PLANNER_JOB       SLURM jobid (same allocation here)
    ANTHROPIC_API_KEY
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

# Reuse demo-6 primitives unchanged.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench_demo6"))
from runner import (  # noqa: E402
    drive_agent,
    fetch_scenario_graph,
    leader_url,
)


# Per-MTok cost estimates (Sonnet 4-6 list rates as of 2026-04). Used only
# for the budget cap.
USD_PER_MTOK_IN = 3.0
USD_PER_MTOK_OUT = 15.0

# Sleep duration injected into each parallel Bash tool. Picked to make the
# wall-time math obvious: parallel ~1s, serial ~Ns.
TOOL_SLEEP_S = 1.0


# ─── prompt template ────────────────────────────────────────────────────────


def build_planner_prompt(n: int) -> str:
    """Prompt the planner to issue exactly N parallel Bash tool calls in one turn.

    Critical phrasing: 'in a SINGLE message' is what triggers Claude Code's
    harness to dispatch the N tool_use blocks concurrently. Without this, the
    model defaults to one-at-a-time, which would silently serialize the test.
    """
    return (
        f"Planner agent. You MUST do this in exactly two LLM turns:\n"
        f"\n"
        f"TURN 1: In a SINGLE message, issue exactly {n} Bash tool calls "
        f"AT THE SAME TIME — do NOT wait for any result before issuing the "
        f"next. Each call must be:\n"
        f"  Bash command='sleep {TOOL_SLEEP_S:.1f}; echo tool_<i>_done' "
        f"where <i> is 1..{n}.\n"
        f"All {n} Bash calls must appear in the same assistant message as "
        f"parallel tool_use blocks.\n"
        f"\n"
        f"TURN 2: After all {n} tool results return, write ONE short "
        f"sentence confirming completion. Do not issue any more tool calls.\n"
        f"\n"
        f"Do not use any other tool. Do not split the {n} Bash calls across "
        f"multiple turns. Failure to issue all {n} in a single message "
        f"invalidates the experiment."
    )


# ─── data model ─────────────────────────────────────────────────────────────


@dataclass
class IntraRunConfig:
    scenario_id: str
    n_tools: int                  # 1, 4, or 10
    leader_host: str
    leader_port: str
    leader_job: str
    planner_host: str
    planner_job: str
    run_timeout_s: int = 300


@dataclass
class IntraRunResult:
    scenario_id: str
    n_tools: int                  # configured N
    success: bool = False
    fail_reason: str = ""
    soft_fail: bool = False       # graph_fetch couldn't read after retry
    wall_time_s: float = 0.0      # full run wall (drive_agent)
    drive_ok: bool = False
    drive_err: str = ""

    # From graph endpoint (post-run aggregate):
    interaction_count: int = 0    # planner-session interactions
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cumulative_cost_usd_after: float = 0.0

    # Tool-call integrity (computed by enumerating per-interaction tool_calls):
    tool_calls_total: int = 0     # sum across all interactions
    tool_calls_per_interaction: list[int] = field(default_factory=list)
    bash_tool_calls_total: int = 0
    tool_call_ids: list[str] = field(default_factory=list)
    tool_call_ids_unique: bool = False
    single_interaction_containment: bool = False  # all bash tool_calls in 1 interaction
    parallel_interaction_index: int = -1          # which interaction held them all

    # Per-tool-call commands captured (for human inspection, smoke runs):
    bash_commands: list[str] = field(default_factory=list)

    # Wall-time parallelism check:
    # Claude Code's harness emits tool results in the next user-turn message.
    # We approximate "did parallel happen" by comparing wall time against
    # the serial-baseline expectation: 2 * llm_turn + N * TOOL_SLEEP_S.
    # If wall is closer to (2 * llm_turn + max(tool_sleeps)), tools ran parallel.
    expected_serial_s: float = 0.0
    expected_parallel_s: float = 0.0
    parallelism_verdict: str = ""  # "parallel" | "serialized" | "ambiguous" | "n_a"

    ts_start: str = ""
    ts_done: str = ""
    extra: dict = field(default_factory=dict)

    def to_jsonl_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":")) + "\n"


# ─── HTTP helpers (with bench-specific timeouts) ────────────────────────────


def _http_get_json(url: str, timeout_s: float) -> Optional[dict | list]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status != 200:
                return None
            body = resp.read()
            return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _fetch_graph_with_retry(scenario_id: str) -> Optional[dict]:
    """Per spec: bump graph timeout to 60s, one retry after 30s wait, then
    soft-fail. Returns None on both attempts failing."""
    g = fetch_scenario_graph(scenario_id, timeout_s=60)
    if g is not None:
        return g
    print("    graph fetch attempt 1 failed — waiting 30s before retry…",
          flush=True)
    time.sleep(30)
    g = fetch_scenario_graph(scenario_id, timeout_s=60)
    return g


def _fetch_session_seqs(session_id: str) -> list[int]:
    """List sequence_ids for a session via /_interceptor/interactions."""
    url = (
        f"{leader_url()}/_interceptor/interactions"
        f"?session_id={urllib.parse.quote(session_id)}&limit=500"
    )
    rows = _http_get_json(url, timeout_s=30)
    if not isinstance(rows, list):
        return []
    seqs: list[int] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = r.get("id", "")
        if isinstance(rid, str) and ":" in rid:
            try:
                seqs.append(int(rid.rsplit(":", 1)[1]))
            except ValueError:
                continue
    seqs.sort()
    return seqs


def _fetch_interaction(session_id: str, seq: int) -> Optional[dict]:
    url = f"{leader_url()}/api/interactions/{session_id}:{seq}"
    return _http_get_json(url, timeout_s=30)  # type: ignore[return-value]


# ─── tool-call extraction ───────────────────────────────────────────────────


def _extract_tool_calls(interaction_detail: dict) -> list[dict]:
    """Pull tool_calls out of an interaction detail blob.

    The Flask `/api/interactions/<id>` endpoint surfaces tool_calls as a
    top-level field (a flat list of {id, name, input}) — see the
    InteractionRecord schema in protocol/interaction.h:106 and the JSON
    flattening in conversation_adapter.build_interaction_detail.
    """
    if not isinstance(interaction_detail, dict):
        return []
    tc = interaction_detail.get("tool_calls")
    if isinstance(tc, list):
        return [t for t in tc if isinstance(t, dict)]
    # Belt-and-braces: probe nested shapes if the schema ever changes.
    resp = interaction_detail.get("response")
    if isinstance(resp, dict) and isinstance(resp.get("tool_calls"), list):
        return [t for t in resp["tool_calls"] if isinstance(t, dict)]
    return []


def _list_session_ids_for_scenario(scenario_id: str, expected_prefix: str) -> list[str]:
    """Enumerate every session_id that has at least one interaction matching
    `expected_prefix`. Uses the recent-interactions feed since `/api/scenarios`
    has been observed to lag for newly-written scenarios."""
    url = f"{leader_url()}/_interceptor/interactions?limit=500"
    rows = _http_get_json(url, timeout_s=30)
    if not isinstance(rows, list):
        return []
    sids: set[str] = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = r.get("session_id") or ""
        if not isinstance(sid, str):
            continue
        # Match the planner's base id and any sub-sessions of the form
        # `<base>.N` (Claude Code rolls subsequent calls under .2, .3, etc).
        if sid == expected_prefix or sid.startswith(expected_prefix + "."):
            sids.add(sid)
    return sorted(sids)


# ─── orchestrator ────────────────────────────────────────────────────────────


def one_intra_run(cfg: IntraRunConfig, results_dir: Path) -> IntraRunResult:
    """Execute one intra-agent fan-out cycle.

    Pipeline:
      1. Drive the planner via `claude -p` on PLANNER_HOST.
      2. Fetch scenario graph (60s timeout, 1 retry, soft-fail on second miss).
      3. Enumerate planner-session interactions, fetch each, count tool_calls.
      4. Compute integrity checks + wall-time parallelism verdict.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    res = IntraRunResult(
        scenario_id=cfg.scenario_id,
        n_tools=cfg.n_tools,
        ts_start=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    res.expected_serial_s = cfg.n_tools * TOOL_SLEEP_S
    res.expected_parallel_s = TOOL_SLEEP_S

    t0 = time.monotonic()

    # Phase 1: drive the planner. Session id is scenario-unique to avoid
    # cross-run bundle collapse (multi-agent-visualization.md §8 pitfall #1).
    session_id = f"planner-{cfg.scenario_id}"
    prompt = build_planner_prompt(cfg.n_tools)
    ok, wall, err = drive_agent(
        host=cfg.planner_host,
        job=cfg.planner_job,
        scenario_id=cfg.scenario_id,
        session=session_id,
        prompt=prompt,
        api_key=api_key,
        timeout_s=cfg.run_timeout_s,
    )
    res.drive_ok = ok
    res.drive_err = err if not ok else ""
    res.wall_time_s = wall

    if not ok:
        res.fail_reason = f"drive_agent_failed: {err[:300]}"
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # Phase 2: enumerate planner sessions via /_interceptor/interactions.
    # /api/scenarios has been observed to lag for newly-written scenarios after
    # a dt_demo_server restart; the recent-interactions feed is authoritative.
    # Wait briefly for the streaming write pipeline to flush.
    time.sleep(3)
    sub_sessions = _list_session_ids_for_scenario(cfg.scenario_id, session_id)

    if not sub_sessions:
        # One retry — give the leader a generous window before declaring dead.
        print("    no planner sessions found yet — waiting 30s and retrying…",
              flush=True)
        time.sleep(30)
        sub_sessions = _list_session_ids_for_scenario(cfg.scenario_id, session_id)

    if not sub_sessions:
        res.fail_reason = f"no_planner_sessions_in_feed: {session_id}"
        res.soft_fail = True
        res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return res

    # Persist the session list as our per-run snapshot (replaces the graph JSON
    # the star bench wrote — graph is unreliable here, the session list is what
    # downstream analysis actually needs).
    results_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = results_dir / f"{cfg.scenario_id}.json"

    all_tool_calls: list[dict] = []
    per_int_counts: list[int] = []
    sub_inter_pairs: list[tuple[str, int, list[dict]]] = []
    interaction_details: list[dict] = []  # cached for snapshot file
    total_tokens_seen = 0

    for sid in sub_sessions:
        seqs = _fetch_session_seqs(sid)
        for seq in seqs:
            detail = _fetch_interaction(sid, seq)
            if detail is None:
                continue
            interaction_details.append({
                "session_id": sid, "seq": seq,
                "model": detail.get("model"),
                "system_prompt_head": (detail.get("system_prompt") or "")[:120],
                "response_text": (detail.get("response_text") or "")[:200],
                "token_usage": detail.get("token_usage"),
                "tool_calls": detail.get("tool_calls") or [],
            })
            usage = detail.get("token_usage") or {}
            if isinstance(usage, dict):
                total_tokens_seen += (
                    int(usage.get("input_tokens") or 0)
                    + int(usage.get("output_tokens") or 0)
                )
            tc = _extract_tool_calls(detail)
            if tc:
                all_tool_calls.extend(tc)
                per_int_counts.append(len(tc))
                sub_inter_pairs.append((sid, seq, tc))

    # Snapshot file: lightweight session-feed view + per-interaction summary.
    snapshot_path.write_text(json.dumps({
        "scenario_id": cfg.scenario_id,
        "planner_session_id": session_id,
        "sub_sessions": sub_sessions,
        "interactions": interaction_details,
    }, indent=2))

    res.interaction_count = len(interaction_details)
    res.total_tokens = total_tokens_seen
    in_t = int(res.total_tokens * 0.8)
    out_t = int(res.total_tokens * 0.2)
    res.estimated_cost_usd = (
        (in_t / 1_000_000.0) * USD_PER_MTOK_IN
        + (out_t / 1_000_000.0) * USD_PER_MTOK_OUT
    )

    res.tool_calls_total = len(all_tool_calls)
    res.tool_calls_per_interaction = per_int_counts

    # Filter to Bash tools only — that's what the prompt asks for. The model
    # may also emit non-Bash calls (e.g. TodoWrite); count them separately.
    bash_calls = [t for t in all_tool_calls if t.get("name") == "Bash"]
    res.bash_tool_calls_total = len(bash_calls)
    res.tool_call_ids = [t.get("id", "") for t in bash_calls]
    res.tool_call_ids_unique = (
        len(res.tool_call_ids) > 0
        and len(set(res.tool_call_ids)) == len(res.tool_call_ids)
        and "" not in res.tool_call_ids
    )
    res.bash_commands = [
        (t.get("input") or {}).get("command", "") if isinstance(t.get("input"), dict)
        else str(t.get("input", ""))
        for t in bash_calls
    ]

    # Single-interaction containment: find the FIRST interaction whose Bash
    # tool count equals N (the planner's intended turn-1 fan-out). If found,
    # mark containment True; the rest of the interactions are turn-2+ (which
    # should have ZERO tool calls per the prompt — surfaced as "extra_turns_with_tools"
    # in the soft warning channel below).
    for idx, (_sid, _seq, tc) in enumerate(sub_inter_pairs):
        bash_in_this = [t for t in tc if t.get("name") == "Bash"]
        if len(bash_in_this) == cfg.n_tools:
            res.single_interaction_containment = True
            res.parallel_interaction_index = idx
            bash_calls_in_planner_first = bash_in_this
            break

    if not res.single_interaction_containment and bash_calls:
        # Containment failed: bash tools split across multiple interactions
        # (or count != N). Record where the bash calls landed.
        res.extra["bash_distribution"] = [
            {"sub_session": sid, "seq": seq, "bash_count": sum(
                1 for t in tc if t.get("name") == "Bash"
            )}
            for sid, seq, tc in sub_inter_pairs
            if any(t.get("name") == "Bash" for t in tc)
        ]
    else:
        del bash_calls_in_planner_first  # silence unused on the happy path

    # Phase 4: parallelism verdict from wall-time math.
    # Drive wall = startup overhead + N_LLM_turns * llm_turn + tool_phase.
    # llm_turn ≈ (wall - tool_phase - overhead) / N_turns. Without per-turn
    # timestamps we can only do a coarse comparison: is wall closer to the
    # serial-or-parallel expectation? Use the difference (serial - parallel
    # = (N-1) * TOOL_SLEEP_S) and check whether wall - parallel_baseline is
    # near 0 (parallel) or near (N-1) * TOOL_SLEEP_S (serial).
    if cfg.n_tools <= 1:
        res.parallelism_verdict = "n_a"
    else:
        # Heuristic: per-N=1 baseline establishes the LLM-overhead floor at
        # runtime; we don't have it here, so use a static threshold. If
        # wall_time is below ~30s for N=10, that's only consistent with
        # parallel (serial would add 10s on top of an already-15-25s LLM
        # overhead, pushing past 30s easily). If above 30s for N=10, ambiguous.
        # For N=4 the same logic with 4s diff.
        # This is intentionally coarse — the analyzer does the real comparison
        # against per-N=1 baselines from the sweep.
        diff_serial_parallel = (cfg.n_tools - 1) * TOOL_SLEEP_S
        if wall < 15.0 + (cfg.n_tools - 1) * TOOL_SLEEP_S * 0.3:
            res.parallelism_verdict = "parallel"
        elif wall > 15.0 + diff_serial_parallel * 0.7:
            res.parallelism_verdict = "serialized"
        else:
            res.parallelism_verdict = "ambiguous"

    # Success criteria:
    # - drive_agent ok
    # - graph fetched (covered above)
    # - exactly N Bash tool calls captured in single interaction containment
    # - all bash ids unique
    res.success = (
        res.drive_ok
        and res.bash_tool_calls_total == cfg.n_tools
        and res.tool_call_ids_unique
        and res.single_interaction_containment
    )
    if not res.success and not res.fail_reason:
        msgs = []
        if res.bash_tool_calls_total != cfg.n_tools:
            msgs.append(
                f"bash_count={res.bash_tool_calls_total} expected={cfg.n_tools}"
            )
        if not res.tool_call_ids_unique:
            msgs.append("tool_call_ids_not_unique_or_empty")
        if not res.single_interaction_containment:
            msgs.append("not_in_single_interaction")
        res.fail_reason = "integrity_check_failed: " + "; ".join(msgs)

    res.ts_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return res


# ─── helpers exported for bench.py ──────────────────────────────────────────


def is_soft_fail(res: IntraRunResult) -> bool:
    return res.soft_fail
