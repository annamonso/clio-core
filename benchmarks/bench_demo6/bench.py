#!/usr/bin/env python3
"""bench_demo6 CLI.

Usage:
    bench.py smoke                      # one end-to-end run, baseline config
    bench.py a                          # Sweep A: 15 baseline runs
    bench.py b                          # Sweep B: 5 runs × 4 payload sizes
    bench.py c                          # Sweep C: 10 single-host + 10 two-host
    bench.py analyze                    # write SUMMARY.md from runs.jsonl

Reads config from env (see runner.py docstring).

Per spec:
  - 30 s flat pacing between runs.
  - Up to 2 retries on top-level failure (planner/executor exit ≠ 0, or edge
    POST non-2xx). 60 s pause + fresh scenario_id (-r1, -r2 suffix).
  - 429s on Task subagents are NOT retryable — they surface as parent tool
    failures, the parent continues, the run is valid.
  - Mid-sweep dt_demo_server restart aborts the sweep and writes ABORTED.txt.
  - runs.jsonl is line-buffered (flush after every run).
  - Per-run <sid>.json is written inside one_run() right after graph fetch.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from runner import (
    HostConfig,
    RunConfig,
    RunResult,
    fetch_scenario_graph,
    health_snapshot,
    one_run,
    server_restarted,
)

PACE_S = int(os.environ.get("BENCH_PACE_S", "90"))   # default 90s (≈8K tok/min)
RATE_LIMIT_EXTRA_PACE_S = 60   # extra cooldown after a rate-limit soft-fail
RETRY_PAUSE_S = 60
MAX_RETRIES = 2
MAX_RETRIES_SRUN_STARTUP = 1   # cluster-side flake — don't burn 3 attempts on it
SRUN_STARTUP_WALL_THRESHOLD_S = 10.0
SOFT_FAIL_REASON = "rate_limited_soft_fail"

# Exit codes from _run_sweep / main:
RC_OK = 0
RC_HAD_FAILURES = 1     # sweep finished, but some runs failed (continue chain)
RC_CHAIN_ABORT = 2      # contamination tripwire OR 2-of-last-3 failure (stop chain)
RC_LEADER_DOWN = 3      # health_snapshot returned !ok at sweep start

# Tripwires (per spec — fail fast, don't proceed into B/C with bad data):
INT_COUNT_WARN_THRESHOLD = 30
LAST_N_WINDOW = 3
LAST_N_FAIL_LIMIT = 2

RESULTS_DIR = Path(
    os.environ.get(
        "BENCH_OUT_DIR",
        str(Path(__file__).resolve().parent / "results"),
    )
)
RUNS_JSONL = RESULTS_DIR / "runs.jsonl"
ABORT_FILE = RESULTS_DIR / "ABORTED.txt"


def _baseline_host_config() -> HostConfig:
    """Two-host baseline: planner on LEADER_HOST, executor on PEER_HOST."""
    return HostConfig(
        planner_host=os.environ["LEADER_HOST"],
        executor_host=os.environ["PEER_HOST"],
        planner_job=os.environ["LEADER_JOB"],
        executor_job=os.environ["PEER_JOB"],
    )


def _single_host_config() -> HostConfig:
    """Both peers on LEADER_HOST. Used by Sweep C."""
    return HostConfig(
        planner_host=os.environ["LEADER_HOST"],
        executor_host=os.environ["LEADER_HOST"],
        planner_job=os.environ["LEADER_JOB"],
        executor_job=os.environ["LEADER_JOB"],
    )


def _open_runs_jsonl():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # buffering=1 → line-buffered in text mode. Each write+\n is flushed.
    return open(RUNS_JSONL, "a", buffering=1)


def _abort(reason: str, affected: list[str]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    body = [
        f"aborted_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"reason: {reason}",
        f"affected_scenario_ids:",
        *(f"  - {sid}" for sid in affected),
    ]
    ABORT_FILE.write_text("\n".join(body) + "\n")
    print(f"\n  ABORT: {reason}", file=sys.stderr)
    print(f"  Affected runs: {len(affected)}", file=sys.stderr)
    print(f"  See: {ABORT_FILE}", file=sys.stderr)


def _execute_with_retries(
    base_sid: str,
    sweep: str,
    payload_size_bytes: int,
    host_config: HostConfig,
    out_fp,
) -> RunResult:
    """Run with up to MAX_RETRIES retries. Each retry uses a fresh scenario_id
    (suffixed -r1, -r2) per Pitfall #1: never reuse a poisoned scenario_id.

    Inner retry print is minimal — the per-run summary line is emitted by
    _run_sweep after this returns, so the live stream reads cleanly.
    """
    attempt = 0
    while True:
        sid = base_sid if attempt == 0 else f"{base_sid}-r{attempt}"
        cfg = RunConfig(
            scenario_id=sid,
            sweep=sweep,
            payload_size_bytes=payload_size_bytes,
            host_config=host_config,
        )
        if attempt > 0:
            print(f"    retry attempt {attempt} as {sid}", flush=True)
        result = one_run(cfg, RESULTS_DIR)
        result.retry_count = attempt
        out_fp.write(result.to_jsonl_line())
        # Don't retry rate-limit soft fails — retrying immediately won't help.
        if result.success or result.fail_reason == SOFT_FAIL_REASON:
            return result
        # Distinguish srun-startup errors (cluster-side flake; ~few-second
        # wall, no LLM call ever made) from genuine workload failures.
        # Per spec: cap srun-startup at 1 retry (2 attempts total) instead of
        # 2 retries (3 attempts total).
        is_srun_startup = (
            result.fail_reason.startswith(
                ("planner_exit_nonzero", "executor_exit_nonzero")
            )
            and result.wall_time_s < SRUN_STARTUP_WALL_THRESHOLD_S
            and result.planner_interactions == 0
            and result.executor_interactions == 0
        )
        retry_cap = MAX_RETRIES_SRUN_STARTUP if is_srun_startup else MAX_RETRIES
        if attempt >= retry_cap:
            return result
        attempt += 1
        kind = "srun-startup flake" if is_srun_startup else "fail"
        print(
            f"    {kind}: {result.fail_reason[:120]} — pausing "
            f"{RETRY_PAUSE_S}s before retry (cap={retry_cap})",
            flush=True,
        )
        time.sleep(RETRY_PAUSE_S)


def _emit_run_line(
    sweep_label: str,
    idx: int,
    total: int,
    res: RunResult,
    recent_window: list[bool],
) -> None:
    """Per-run summary in the format requested by the spec."""
    header = f"[sweep {sweep_label} | run {idx + 1}/{total} | {res.scenario_id}]"
    is_soft_fail = res.fail_reason == SOFT_FAIL_REASON
    if is_soft_fail:
        print(f"{header} RATE_LIMITED (soft-fail, NOT counted in sweep)", flush=True)
    elif res.success:
        print(f"{header} OK", flush=True)
    else:
        print(f"{header} FAIL {res.fail_reason[:80]}", flush=True)
    print(
        f"    edge={res.edge_latency_ms:.1f}ms wall={res.wall_time_s:.0f}s "
        f"plan_int={res.planner_interactions} exec_int={res.executor_interactions}",
        flush=True,
    )
    # Bundle-contamination tripwire warning (genuine per-run count is 6–20;
    # >30 means cross-scenario merging has come back somehow).
    if (res.planner_interactions > INT_COUNT_WARN_THRESHOLD
            or res.executor_interactions > INT_COUNT_WARN_THRESHOLD):
        print(
            f"    ⚠ WARN interaction_count > {INT_COUNT_WARN_THRESHOLD} "
            f"(plan={res.planner_interactions} exec={res.executor_interactions}) "
            f"— possible bundle contamination",
            flush=True,
        )
    # Hard-failure window status (informational; soft-fails don't contribute).
    if not is_soft_fail and not res.success:
        recent_fails = sum(1 for ok in recent_window if not ok)
        print(
            f"    ⚠ {recent_fails} failure(s) in last {len(recent_window)} run(s)",
            flush=True,
        )


def _is_clean_run(res: RunResult) -> bool:
    """True iff this run produced usable per-agent data.

    A "success" with both agents at interaction_count=0 is the bundle-
    contamination signature (graph fetched OK but contained no per-scenario
    bundle for our unique session ids). Treat as not-clean for window-counting
    purposes AND tripwire the chain.
    """
    if not res.success:
        return False
    return res.planner_interactions > 0 or res.executor_interactions > 0


def _run_sweep(
    sweep_name: str,
    plan: list[tuple[str, int, HostConfig]],
) -> int:
    """plan: list of (scenario_id, payload_size_bytes, host_config) tuples.
    Returns RC_* per spec."""
    sweep_label = sweep_name.upper()
    print(f"=== Sweep {sweep_label} — {len(plan)} runs ===", flush=True)
    health0 = health_snapshot()
    if not health0["ok"]:
        print(
            f"  FATAL: leader unhealthy — flask_ok={health0.get('flask_ok')} "
            f"dt_pid={health0.get('dt_pid')}",
            flush=True,
        )
        return RC_LEADER_DOWN
    print(
        f"  health: dt_pid={health0['dt_pid']} flask_ok={health0['flask_ok']}",
        flush=True,
    )

    out_fp = _open_runs_jsonl()
    failures: list[str] = []
    soft_fails: list[str] = []      # rate-limited; not counted but surfaced
    completed: list[str] = []
    recent_window: list[bool] = []   # True == clean run; sliding 3-element window

    try:
        for idx, (sid, payload_size, hc) in enumerate(plan):
            curr_health = health_snapshot()
            if server_restarted(health0, curr_health):
                _abort(
                    "dt_demo_server restart detected mid-sweep — interaction "
                    "counts on prior runs are wiped (edges survive). "
                    "Re-run the affected scenarios with fresh ids.",
                    completed,
                )
                return RC_CHAIN_ABORT

            res = _execute_with_retries(sid, sweep_name, payload_size, hc, out_fp)
            completed.append(res.scenario_id)
            is_soft_fail = res.fail_reason == SOFT_FAIL_REASON

            # Soft-fails (rate-limit) don't contribute to the failure window
            # or to the per-sweep failure list — they're noise, not a defect.
            if not is_soft_fail:
                clean = _is_clean_run(res)
                recent_window.append(clean)
                if len(recent_window) > LAST_N_WINDOW:
                    recent_window.pop(0)
                if not res.success:
                    failures.append(res.scenario_id)
            else:
                soft_fails.append(res.scenario_id)

            _emit_run_line(sweep_label, idx, len(plan), res, recent_window)

            # Tripwires only consider hard failures.
            if not is_soft_fail:
                # Tripwire 1: contamination signature (success but both at 0).
                if (res.success
                        and res.planner_interactions == 0
                        and res.executor_interactions == 0):
                    print(
                        "    ⚠ ABORTING CHAIN — run completed with both agents at "
                        "interaction_count=0 (bundle-contamination signature). "
                        "Don't continue into B/C with bad data.",
                        flush=True,
                    )
                    return RC_CHAIN_ABORT
                # Tripwire 2: 2 of last 3 runs failed.
                recent_fails = sum(1 for ok in recent_window if not ok)
                if (len(recent_window) >= LAST_N_WINDOW
                        and recent_fails >= LAST_N_FAIL_LIMIT):
                    print(
                        f"    ⚠ ABORTING CHAIN — {recent_fails} of last "
                        f"{len(recent_window)} runs failed",
                        flush=True,
                    )
                    return RC_CHAIN_ABORT

            if idx < len(plan) - 1:
                pace = PACE_S + (RATE_LIMIT_EXTRA_PACE_S if is_soft_fail else 0)
                if is_soft_fail:
                    print(
                        f"  rate-limit cooldown — pacing {pace}s "
                        f"({PACE_S} + {RATE_LIMIT_EXTRA_PACE_S} extra)…",
                        flush=True,
                    )
                else:
                    print(f"  pacing {pace}s…", flush=True)
                time.sleep(pace)
    finally:
        out_fp.close()

    print(
        f"=== Sweep {sweep_label} done — {len(failures)} hard failures, "
        f"{len(soft_fails)} rate-limit soft-fails ===",
        flush=True,
    )
    if failures:
        for sid in failures:
            print(f"  FAILED: {sid}", flush=True)
    if soft_fails:
        for sid in soft_fails:
            print(f"  RATE_LIMITED: {sid}", flush=True)
    return RC_HAD_FAILURES if failures else RC_OK


# ─── sweep plans ────────────────────────────────────────────────────────────

def plan_smoke() -> list[tuple[str, int, HostConfig]]:
    return [(f"demo-6-smoke-{int(time.time())}", 0, _baseline_host_config())]


def plan_a() -> list[tuple[str, int, HostConfig]]:
    """Sweep A — variance baseline. 3 NEW runs (var-004..006), continuing from
    the 3 already on disk (var-001..003). Final n=6 in analysis."""
    hc = _baseline_host_config()
    return [(f"demo-6-var-{i:03d}", 0, hc) for i in range(4, 7)]


def plan_b() -> list[tuple[str, int, HostConfig]]:
    """Sweep B — payload size. 3 runs × 4 sizes = 12 total."""
    hc = _baseline_host_config()
    sizes = [
        ("100b", 100),
        ("1kb", 1_000),
        ("10kb", 10_000),
        ("100kb", 100_000),
    ]
    out: list[tuple[str, int, HostConfig]] = []
    for label, size in sizes:
        for i in range(1, 4):
            out.append((f"demo-6-pay-{label}-{i:03d}", size, hc))
    return out


def plan_c() -> list[tuple[str, int, HostConfig]]:
    """Sweep C — single-host vs two-host. 3 runs × 2 configs = 6 total."""
    out: list[tuple[str, int, HostConfig]] = []
    hc1 = _single_host_config()
    hc2 = _baseline_host_config()
    for i in range(1, 4):
        out.append((f"demo-6-1h-{i:03d}", 0, hc1))
    for i in range(1, 4):
        out.append((f"demo-6-2h-{i:03d}", 0, hc2))
    return out


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="bench_demo6")
    p.add_argument("cmd", choices=["smoke", "a", "b", "c", "analyze"])
    args = p.parse_args(argv)

    if args.cmd == "analyze":
        from analysis import write_summary
        return write_summary(RESULTS_DIR)

    plans = {"smoke": plan_smoke, "a": plan_a, "b": plan_b, "c": plan_c}
    plan = plans[args.cmd]()
    return _run_sweep(args.cmd, plan)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
