#!/usr/bin/env python3
"""bench_demo6_intra CLI — Test 6 in the thesis evaluation.

Intra-agent fan-out: one planner agent issues N parallel Bash tool calls in a
single LLM turn. Verifies the framework captures all N as separate tool_calls
in one interaction record (no collapse), all ids unique, and that the SDK +
harness actually parallelize (wall-time math).

Usage:
    bench.py smoke              # one N=1 smoke run, show JSON, exit
    bench.py s                  # full sweep N=[1,4,10] x n=3 = 9 runs
    bench.py runone <N>         # one run at the given N (smoke for N=4 / N=10)
    bench.py analyze            # write SUMMARY_INTRA.md from runs.jsonl

Reads config from env (see intra_runner.py docstring).

Safeguards (per spec):
  - 60 s flat pacing between runs (less than star — only 2 LLM calls per run).
  - $3 hard budget cap (estimated, abort BEFORE next run if would exceed).
  - N=1 abort tripwire: if the first N=1 run has wall_time > 30 s, abort the
    sweep (means agent is doing way more turns than expected).
  - Graph fetch soft-fail: 60 s timeout + 1 retry with 30 s wait, then mark
    soft-fail (not hard) and surface separately in summary.
  - dt_demo_server restart mid-sweep → ABORT.
  - runs.jsonl is line-buffered (flush after every run).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Reuse demo-6 health-check primitives (same as bench_demo6_star/bench.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bench_demo6"))
import urllib.request as _urllib_request
from runner import (  # noqa: E402
    server_restarted,
    _ssh_dt_pid,
)

from intra_runner import (  # noqa: E402
    IntraRunConfig,
    IntraRunResult,
    is_soft_fail,
    one_intra_run,
)


def health_snapshot() -> dict:
    """Same shape as star bench's health_snapshot. /api/conversations may take
    >10 s under Werkzeug's single thread; allow 30 s per try with one retry."""
    pid = _ssh_dt_pid()
    flask_ok = False
    base = f"http://{os.environ.get('LEADER_HOST','')}:{os.environ.get('LEADER_PORT','5050')}"
    for i in range(2):
        try:
            with _urllib_request.urlopen(f"{base}/api/conversations", timeout=30.0) as resp:
                if resp.status == 200:
                    flask_ok = True
                    break
        except Exception:
            pass
        if i == 0:
            time.sleep(2)
    # Lightweight fallback: if /api/conversations is slow but /api/scenarios
    # works, treat Flask as up. The bench primarily uses /api/scenarios/.../graph
    # and /_interceptor/interactions, neither of which routes through the
    # heavier conversations adapter.
    if not flask_ok:
        try:
            with _urllib_request.urlopen(f"{base}/api/scenarios", timeout=10.0) as resp:
                if resp.status == 200:
                    flask_ok = True
        except Exception:
            pass
    return {
        "ok": flask_ok and pid is not None,
        "dt_pid": pid,
        "flask_ok": flask_ok,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


PACE_S = int(os.environ.get("BENCH_PACE_S", "60"))
BUDGET_CAP_USD = float(os.environ.get("BENCH_BUDGET_USD", "3.0"))
BUDGET_HEADROOM_USD = 0.30
PER_RUN_COST_GUESS_USD = 0.08    # 2 LLM turns, small token spend
N1_ABORT_WALL_S = 30.0           # tripwire: if N=1 takes longer, agent is misbehaving

RC_OK = 0
RC_HAD_FAILURES = 1
RC_LEADER_DOWN = 3
RC_BUDGET_EXCEEDED = 4
RC_CHAIN_ABORT = 2
RC_N1_TRIPWIRE = 5

RESULTS_DIR = Path(
    os.environ.get(
        "BENCH_OUT_DIR",
        str(Path(__file__).resolve().parent / "results_intra"),
    )
)
RUNS_JSONL = RESULTS_DIR / "runs.jsonl"
ABORT_FILE = RESULTS_DIR / "ABORTED.txt"


# ─── env loading ─────────────────────────────────────────────────────────────


def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def _build_cfg(scenario_id: str, n: int) -> IntraRunConfig:
    if n not in (1, 4, 10):
        raise ValueError(f"unsupported N: {n} (allowed: 1, 4, 10)")
    return IntraRunConfig(
        scenario_id=scenario_id,
        n_tools=n,
        leader_host=_require("LEADER_HOST"),
        leader_port=_require("LEADER_PORT"),
        leader_job=_require("LEADER_JOB"),
        planner_host=_require("PLANNER_HOST"),
        planner_job=_require("PLANNER_JOB"),
    )


# ─── output helpers ─────────────────────────────────────────────────────────


def _open_runs_jsonl():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return open(RUNS_JSONL, "a", buffering=1)


def _abort(reason: str, affected: list[str]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    body = [
        f"aborted_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"reason: {reason}",
        "affected_scenario_ids:",
        *(f"  - {sid}" for sid in affected),
    ]
    ABORT_FILE.write_text("\n".join(body) + "\n")
    print(f"\n  ABORT: {reason}", file=sys.stderr)


def _emit_run_line(label: str, idx: int, total: int, res: IntraRunResult,
                   cumulative_usd: float) -> None:
    header = f"[{label} | run {idx + 1}/{total} | {res.scenario_id}]"
    if is_soft_fail(res):
        print(f"{header} SOFT-FAIL ({res.fail_reason[:80]})", flush=True)
    elif res.success:
        print(f"{header} OK", flush=True)
    else:
        print(f"{header} FAIL {res.fail_reason[:160]}", flush=True)
    print(
        f"    N={res.n_tools}  wall={res.wall_time_s:.1f}s  "
        f"interactions={res.interaction_count}  "
        f"bash_calls={res.bash_tool_calls_total}/{res.n_tools}  "
        f"ids_unique={res.tool_call_ids_unique}  "
        f"contained={res.single_interaction_containment}  "
        f"verdict={res.parallelism_verdict}",
        flush=True,
    )
    print(
        f"    cost_this_run=${res.estimated_cost_usd:.4f}  "
        f"cumulative=${cumulative_usd:.3f}/${BUDGET_CAP_USD:.2f}",
        flush=True,
    )


# ─── single-run driver ──────────────────────────────────────────────────────


def _run_one(scenario_id: str, n: int, cumulative_usd: float, out_fp) -> IntraRunResult:
    cfg = _build_cfg(scenario_id, n)
    res = one_intra_run(cfg, RESULTS_DIR)
    res.cumulative_cost_usd_after = cumulative_usd + res.estimated_cost_usd
    out_fp.write(res.to_jsonl_line())
    return res


# ─── sweep driver ───────────────────────────────────────────────────────────


def _sweep(label: str, plan: list[tuple[str, int]]) -> int:
    """plan: list of (scenario_id, N) tuples."""
    print(f"=== Sweep {label} — {len(plan)} runs ===", flush=True)

    health0 = health_snapshot()
    if not health0["ok"]:
        print(f"  FATAL: leader unhealthy — {health0}", flush=True)
        return RC_LEADER_DOWN
    print(f"  health: dt_pid={health0['dt_pid']} flask_ok={health0['flask_ok']}",
          flush=True)

    out_fp = _open_runs_jsonl()
    failures: list[str] = []
    soft_fails: list[str] = []
    completed: list[str] = []
    cumulative_usd = 0.0
    n1_tripwire_armed = True

    try:
        for idx, (sid, n) in enumerate(plan):
            curr_health = health_snapshot()
            if server_restarted(health0, curr_health):
                _abort(
                    "dt_demo_server restart detected mid-sweep — Path A "
                    "interactions on prior runs are wiped. Re-run with fresh ids.",
                    completed,
                )
                return RC_CHAIN_ABORT
            if cumulative_usd + PER_RUN_COST_GUESS_USD + BUDGET_HEADROOM_USD > BUDGET_CAP_USD:
                _abort(
                    f"budget cap reached: cumulative=${cumulative_usd:.3f}, "
                    f"projected_next=${PER_RUN_COST_GUESS_USD:.2f}, "
                    f"cap=${BUDGET_CAP_USD:.2f}",
                    completed,
                )
                return RC_BUDGET_EXCEEDED

            res = _run_one(sid, n, cumulative_usd, out_fp)
            cumulative_usd += res.estimated_cost_usd
            res.cumulative_cost_usd_after = cumulative_usd
            completed.append(res.scenario_id)

            if is_soft_fail(res):
                soft_fails.append(res.scenario_id)
            elif not res.success:
                failures.append(res.scenario_id)

            _emit_run_line(label, idx, len(plan), res, cumulative_usd)

            # N=1 tripwire: if the FIRST N=1 run blew past 30s, the agent is
            # misbehaving (extra turns / runaway tool loops). Abort early.
            if n1_tripwire_armed and n == 1 and res.drive_ok:
                if res.wall_time_s > N1_ABORT_WALL_S:
                    _abort(
                        f"N=1 wall_time {res.wall_time_s:.1f}s > {N1_ABORT_WALL_S}s "
                        f"— planner is doing more LLM turns than expected, would "
                        f"blow the budget on N=10 runs.",
                        completed,
                    )
                    return RC_N1_TRIPWIRE
                n1_tripwire_armed = False  # only check on the first N=1

            if idx < len(plan) - 1:
                print(f"  pacing {PACE_S}s…", flush=True)
                time.sleep(PACE_S)
    finally:
        out_fp.close()

    print(
        f"=== {label} done — {len(failures)} hard failures, "
        f"{len(soft_fails)} soft-fails — "
        f"cumulative cost ${cumulative_usd:.3f} ===",
        flush=True,
    )
    for sid in failures:
        print(f"  FAILED: {sid}", flush=True)
    for sid in soft_fails:
        print(f"  SOFT-FAILED: {sid}", flush=True)
    return RC_HAD_FAILURES if failures else RC_OK


# ─── plans ──────────────────────────────────────────────────────────────────


def plan_smoke() -> list[tuple[str, int]]:
    return [(f"intra-smoke-{int(time.time())}", 1)]


def plan_runone(n: int) -> list[tuple[str, int]]:
    return [(f"intra-runone-n{n}-{int(time.time())}", n)]


def plan_s() -> list[tuple[str, int]]:
    """Full sweep: N=[1,4,10] x n=3 = 9 runs.

    Order intentionally interleaves: N=1 first (tripwire), then ramp.
    Group by N to keep the sweep readable in runs.jsonl."""
    out: list[tuple[str, int]] = []
    for n in (1, 4, 10):
        for i in range(1, 4):
            out.append((f"intra-n{n}-{i:03d}", n))
    return out


# ─── single-run smoke entry (for showing per-run JSON to user) ──────────────


def _do_smoke(plan: list[tuple[str, int]]) -> int:
    n = plan[0][1]
    print(f"=== Smoke (N={n}, single run) ===", flush=True)
    health0 = health_snapshot()
    if not health0["ok"]:
        print(f"  FATAL: leader unhealthy — {health0}", flush=True)
        return RC_LEADER_DOWN
    print(f"  health: dt_pid={health0['dt_pid']} flask_ok={health0['flask_ok']}",
          flush=True)
    out_fp = _open_runs_jsonl()
    try:
        sid, n = plan[0]
        res = _run_one(sid, n, 0.0, out_fp)
        _emit_run_line("SMOKE", 0, 1, res, res.estimated_cost_usd)
    finally:
        out_fp.close()
    print("\n--- per-run JSON ---", flush=True)
    print(json.dumps({k: v for k, v in res.__dict__.items()}, indent=2,
                     default=str), flush=True)
    return RC_OK if (res.success or is_soft_fail(res)) else RC_HAD_FAILURES


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="bench_demo6_intra")
    p.add_argument("cmd", choices=["smoke", "s", "runone", "analyze"])
    p.add_argument("n", nargs="?", type=int,
                   help="N for `runone`; ignored otherwise")
    args = p.parse_args(argv)

    if args.cmd == "analyze":
        from intra_analysis import write_summary
        return write_summary(RESULTS_DIR)
    if args.cmd == "smoke":
        return _do_smoke(plan_smoke())
    if args.cmd == "runone":
        if args.n is None:
            print("runone requires N argument", file=sys.stderr)
            return 2
        return _do_smoke(plan_runone(args.n))
    if args.cmd == "s":
        return _sweep("s", plan_s())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
