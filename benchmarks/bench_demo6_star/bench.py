#!/usr/bin/env python3
"""bench_demo6_star CLI — Test 5 in the thesis evaluation.

Star topology, two configurations:
  star1: 1 controller + 1 worker      (baseline; comparable shape to demo-6 executor)
  star3: 1 controller + 3 workers     (parallel fan-out)

Usage:
    bench.py smoke1                # one star1 run, show JSON, exit
    bench.py smoke3                # one star3 run, show JSON, exit
    bench.py s1                    # star1 sweep (N=3)
    bench.py s3                    # star3 sweep (N=3)
    bench.py analyze               # write SUMMARY_STAR.md from runs.jsonl

Reads config from env (see runner.py docstring).

Safeguards (per spec):
  - 90 s flat pacing between runs.
  - $5 hard budget cap (estimated, abort BEFORE next run if would exceed).
  - Rate-limit soft fail (any worker int ≤ 2): no retry, +60 s pacing, surface in summary.
  - Host-attribution drift: warn-only, do NOT abort (it's a methodological finding).
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

# Reuse demo-6 health-check primitives. Append (not prepend) so our local
# `analysis.py` and `star_runner.py` win over any same-named modules in
# bench_demo6/ — bench_demo6/analysis.py would otherwise shadow ours.
sys.path.append(str(Path(__file__).resolve().parent.parent / "bench_demo6"))
import urllib.request as _urllib_request
from runner import (  # noqa: E402
    pad_payload,
    server_restarted,
    _ssh_dt_pid,
)

from star_runner import (  # noqa: E402
    StarRunConfig,
    StarRunResult,
    is_soft_fail,
    one_star_run,
)


# Local health snapshot — demo-6's _flask_reachable hardcodes a 10 s per-try
# timeout, but the dt_demo_server + Werkzeug single-thread pairing makes
# /api/conversations consistently take ~11–13 s (each response, not a tail
# event). 30 s per try with 2 retries handles that without papering over a
# real outage.
def health_snapshot() -> dict:
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
    return {
        "ok": flask_ok and pid is not None,
        "dt_pid": pid,
        "flask_ok": flask_ok,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


PACE_S = int(os.environ.get("BENCH_PACE_S", "90"))
RATE_LIMIT_EXTRA_PACE_S = 60
BUDGET_CAP_USD = float(os.environ.get("BENCH_BUDGET_USD", "5.0"))
BUDGET_HEADROOM_USD = 0.50            # abort if cumulative + headroom > cap
PER_RUN_COST_GUESS_USD = 0.30         # used to project ahead of the next run

RC_OK = 0
RC_HAD_FAILURES = 1
RC_LEADER_DOWN = 3
RC_BUDGET_EXCEEDED = 4
RC_CHAIN_ABORT = 2

RESULTS_DIR = Path(
    os.environ.get(
        "BENCH_OUT_DIR",
        str(Path(__file__).resolve().parent / "results_star"),
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


def _build_cfg(scenario_id: str, config_label: str) -> StarRunConfig:
    if config_label not in ("star1", "star3"):
        raise ValueError(f"unknown config: {config_label}")
    all_workers = [h.strip() for h in _require("WORKER_HOSTS").split(",") if h.strip()]
    if len(all_workers) < 3:
        raise RuntimeError(
            f"WORKER_HOSTS must list 3 workers (got {len(all_workers)}: {all_workers})"
        )
    workers = all_workers[:1] if config_label == "star1" else all_workers[:3]
    return StarRunConfig(
        scenario_id=scenario_id,
        config=config_label,
        leader_host=_require("LEADER_HOST"),
        leader_port=_require("LEADER_PORT"),
        leader_job=_require("LEADER_JOB"),
        controller_host=_require("CONTROLLER_HOST"),
        controller_job=_require("CONTROLLER_JOB"),
        worker_hosts=workers,
        worker_job=_require("WORKER_JOB"),
        payload_text=pad_payload(0),
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


def _emit_run_line(label: str, idx: int, total: int, res: StarRunResult,
                   cumulative_usd: float) -> None:
    header = f"[{label} | run {idx + 1}/{total} | {res.scenario_id}]"
    if is_soft_fail(res):
        print(f"{header} RATE_LIMITED ({res.fail_reason[:80]})", flush=True)
    elif res.success:
        print(f"{header} OK", flush=True)
    else:
        print(f"{header} FAIL {res.fail_reason[:120]}", flush=True)
    edges_str = ", ".join(f"{w['label']}={w['edge_latency_ms']:.1f}ms"
                          for w in res.workers)
    print(
        f"    wall={res.wall_time_s:.0f}s  "
        f"workers_max={res.workers_wall_s_max:.0f}s  "
        f"edges_max={res.edges_latency_ms_max:.1f}ms  "
        f"edges=[{edges_str}]",
        flush=True,
    )
    int_str = ", ".join(f"{w['label']}={w['interaction_count']}"
                        for w in res.workers)
    tok_str = ", ".join(f"{w['label']}={w['total_tokens']}"
                        for w in res.workers)
    print(f"    int_count=[{int_str}]  tokens=[{tok_str}]", flush=True)
    if not res.host_attribution_ok and res.workers:
        print(
            f"    ⚠ HOST-ATTRIBUTION DRIFT: "
            + "; ".join(res.host_attribution_warnings),
            flush=True,
        )
    print(
        f"    cost_this_run=${res.estimated_cost_usd:.3f}  "
        f"cumulative=${cumulative_usd:.3f}/${BUDGET_CAP_USD:.2f}",
        flush=True,
    )


# ─── single-run driver ──────────────────────────────────────────────────────


def _run_one(scenario_id: str, config_label: str,
             cumulative_usd: float, out_fp) -> StarRunResult:
    cfg = _build_cfg(scenario_id, config_label)
    res = one_star_run(cfg, RESULTS_DIR)
    res.cumulative_cost_usd_after = cumulative_usd + res.estimated_cost_usd
    out_fp.write(res.to_jsonl_line())
    return res


# ─── sweep driver ───────────────────────────────────────────────────────────


def _sweep(label: str, plan: list[tuple[str, str]]) -> int:
    """plan: list of (scenario_id, config_label) tuples."""
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

    try:
        for idx, (sid, cfg_label) in enumerate(plan):
            # Restart tripwire.
            curr_health = health_snapshot()
            if server_restarted(health0, curr_health):
                _abort(
                    "dt_demo_server restart detected mid-sweep — Path A "
                    "interactions on prior runs are wiped. Re-run with fresh ids.",
                    completed,
                )
                return RC_CHAIN_ABORT
            # Budget tripwire (project the next run + headroom).
            if cumulative_usd + PER_RUN_COST_GUESS_USD + BUDGET_HEADROOM_USD > BUDGET_CAP_USD:
                _abort(
                    f"budget cap reached: cumulative=${cumulative_usd:.3f}, "
                    f"projected_next=${PER_RUN_COST_GUESS_USD:.2f}, "
                    f"cap=${BUDGET_CAP_USD:.2f}",
                    completed,
                )
                return RC_BUDGET_EXCEEDED

            res = _run_one(sid, cfg_label, cumulative_usd, out_fp)
            cumulative_usd += res.estimated_cost_usd
            res.cumulative_cost_usd_after = cumulative_usd
            completed.append(res.scenario_id)

            if is_soft_fail(res):
                soft_fails.append(res.scenario_id)
            elif not res.success:
                failures.append(res.scenario_id)

            _emit_run_line(label, idx, len(plan), res, cumulative_usd)

            if idx < len(plan) - 1:
                pace = PACE_S + (RATE_LIMIT_EXTRA_PACE_S if is_soft_fail(res) else 0)
                if is_soft_fail(res):
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
        f"=== {label} done — {len(failures)} hard failures, "
        f"{len(soft_fails)} rate-limit soft-fails — "
        f"cumulative cost ${cumulative_usd:.3f} ===",
        flush=True,
    )
    for sid in failures:
        print(f"  FAILED: {sid}", flush=True)
    for sid in soft_fails:
        print(f"  RATE_LIMITED: {sid}", flush=True)
    return RC_HAD_FAILURES if failures else RC_OK


# ─── plans ──────────────────────────────────────────────────────────────────


def plan_smoke1() -> list[tuple[str, str]]:
    return [(f"star1-smoke-{int(time.time())}", "star1")]


def plan_smoke3() -> list[tuple[str, str]]:
    return [(f"star3-smoke-{int(time.time())}", "star3")]


def plan_s1() -> list[tuple[str, str]]:
    return [(f"star1-{i:03d}", "star1") for i in range(1, 4)]


def plan_s3() -> list[tuple[str, str]]:
    return [(f"star3-{i:03d}", "star3") for i in range(1, 4)]


# ─── single-run smoke entry (for showing per-run JSON to user) ──────────────


def _do_smoke(plan: list[tuple[str, str]]) -> int:
    print(f"=== Smoke ({plan[0][1]}, single run) ===", flush=True)
    health0 = health_snapshot()
    if not health0["ok"]:
        print(f"  FATAL: leader unhealthy — {health0}", flush=True)
        return RC_LEADER_DOWN
    print(f"  health: dt_pid={health0['dt_pid']} flask_ok={health0['flask_ok']}",
          flush=True)
    out_fp = _open_runs_jsonl()
    try:
        sid, cfg_label = plan[0]
        res = _run_one(sid, cfg_label, 0.0, out_fp)
        _emit_run_line("SMOKE", 0, 1, res, res.estimated_cost_usd)
    finally:
        out_fp.close()
    print("\n--- per-run JSON ---", flush=True)
    print(json.dumps({
        k: v for k, v in res.__dict__.items() if k != "extra"
    }, indent=2), flush=True)
    return RC_OK if res.success else RC_HAD_FAILURES


# ─── CLI ────────────────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="bench_demo6_star")
    p.add_argument("cmd", choices=["smoke1", "smoke3", "s1", "s3", "analyze"])
    args = p.parse_args(argv)

    if args.cmd == "analyze":
        from analysis import write_summary
        return write_summary(RESULTS_DIR)
    if args.cmd == "smoke1":
        return _do_smoke(plan_smoke1())
    if args.cmd == "smoke3":
        return _do_smoke(plan_smoke3())
    if args.cmd == "s1":
        return _sweep("s1", plan_s1())
    if args.cmd == "s3":
        return _sweep("s3", plan_s3())
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
