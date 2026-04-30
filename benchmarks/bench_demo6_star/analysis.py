"""Read benchmarks/bench_demo6_star/results_star/runs.jsonl,
write SUMMARY_STAR.md comparing star1 vs star3.

Numbers only — no interpretation. Caveats stated where the framework's model
creates an ambiguity (edge latency_ms is caller-reported by the framework;
this harness substitutes a measured RTT — that distinction matters).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Iterable


# ─── stats ─────────────────────────────────────────────────────────────────


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def _stats(values: Iterable[float]) -> dict:
    vs = [float(v) for v in values
          if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vs:
        return {"n": 0, "p50": float("nan"), "p90": float("nan"),
                "max": float("nan"), "stdev": float("nan")}
    return {
        "n": len(vs),
        "p50": _percentile(vs, 0.50),
        "p90": _percentile(vs, 0.90),
        "max": max(vs),
        "stdev": statistics.stdev(vs) if len(vs) > 1 else 0.0,
    }


def _fmt(s: dict, unit: str = "") -> str:
    if s["n"] == 0:
        return "—"
    suf = f" {unit}" if unit else ""
    return (
        f"{s['p50']:.2f}{suf} / {s['p90']:.2f}{suf} / "
        f"{s['max']:.2f}{suf} / {s['stdev']:.2f}{suf}"
    )


# ─── load ──────────────────────────────────────────────────────────────────


def _load(results_dir: Path) -> list[dict]:
    jsonl = results_dir / "runs.jsonl"
    if not jsonl.exists():
        return []
    out: list[dict] = []
    for line in jsonl.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _ok(runs: list[dict]) -> list[dict]:
    return [r for r in runs if r.get("success")]


# ─── per-config tables ─────────────────────────────────────────────────────


def _per_edge_values(runs: list[dict]) -> list[float]:
    """Flatten per-worker edge_latency_ms across all runs."""
    out: list[float] = []
    for r in runs:
        for w in r.get("workers", []):
            if w.get("edge_ok") and w.get("edge_latency_ms", 0) > 0:
                out.append(float(w["edge_latency_ms"]))
    return out


def _config_block(label: str, runs: list[dict]) -> str:
    sub = _ok([r for r in runs if r.get("config") == label])
    n = len(sub)
    if n == 0:
        return f"### {label}\n\n_No successful runs._\n"

    wall = _stats(r["wall_time_s"] for r in sub)
    work_max = _stats(r["workers_wall_s_max"] for r in sub)
    work_sum = _stats(r["workers_wall_s_sum"] for r in sub)
    edge_max = _stats(r["edges_latency_ms_max"] for r in sub)
    per_edge = _stats(_per_edge_values(sub))
    cost = _stats(r["estimated_cost_usd"] for r in sub)

    # Total tokens summed across all workers per run, then aggregated.
    per_run_tokens: list[float] = []
    for r in sub:
        per_run_tokens.append(sum(w.get("total_tokens", 0) for w in r.get("workers", [])))
    tok = _stats(per_run_tokens)

    # Per-run interaction_count summed across workers.
    per_run_int: list[float] = []
    for r in sub:
        per_run_int.append(sum(w.get("interaction_count", 0) for w in r.get("workers", [])))
    int_total = _stats(per_run_int)

    # Host attribution: fraction of (run × worker) pairs where observed == assigned.
    pairs_total = sum(len(r.get("workers", [])) for r in sub)
    pairs_match = sum(
        1 for r in sub for w in r.get("workers", []) if w.get("host_match")
    )
    pct = (pairs_match / pairs_total * 100.0) if pairs_total else float("nan")

    body = [
        f"### {label} (N={n} successful runs)",
        "",
        "| metric | P50 / P90 / max / stdev |",
        "|---|---|",
        f"| wall_time_s (full run) | {_fmt(wall, 's')} |",
        f"| workers_wall_s_max (critical-path fan-out) | {_fmt(work_max, 's')} |",
        f"| workers_wall_s_sum (would-be-serial baseline) | {_fmt(work_sum, 's')} |",
        f"| edges_latency_ms_max (slowest of {1 if label=='star1' else 3}) | {_fmt(edge_max, 'ms')} |",
        f"| per-edge edge_latency_ms (across all workers × runs, n={per_edge['n']}) | {_fmt(per_edge, 'ms')} |",
        f"| total tokens per run (sum across workers) | {_fmt(tok)} |",
        f"| total interaction_count per run (sum across workers) | {_fmt(int_total)} |",
        f"| estimated cost per run (USD) | {_fmt(cost)} |",
        "",
        f"**Host-attribution accuracy:** {pairs_match}/{pairs_total} worker→host "
        f"pairs matched ({pct:.1f}%).",
        "",
    ]
    return "\n".join(body)


# ─── comparison ────────────────────────────────────────────────────────────


def _comparison(runs: list[dict]) -> str:
    s1 = _ok([r for r in runs if r.get("config") == "star1"])
    s3 = _ok([r for r in runs if r.get("config") == "star3"])
    if not s1 or not s3:
        return "## star1 vs star3 comparison\n\n_Need successful runs in both configs._\n"

    def _p50(values: list[float]) -> float:
        s = _stats(values)
        return s["p50"]

    s1_wall = _p50([r["wall_time_s"] for r in s1])
    s3_wall = _p50([r["wall_time_s"] for r in s3])
    s1_workers_max = _p50([r["workers_wall_s_max"] for r in s1])
    s3_workers_max = _p50([r["workers_wall_s_max"] for r in s3])
    s1_per_edge = _p50(_per_edge_values(s1))
    s3_per_edge = _p50(_per_edge_values(s3))
    s1_tokens = _p50([sum(w.get("total_tokens", 0) for w in r.get("workers", [])) for r in s1])
    s3_tokens = _p50([sum(w.get("total_tokens", 0) for w in r.get("workers", [])) for r in s3])
    s1_cost = _p50([r["estimated_cost_usd"] for r in s1])
    s3_cost = _p50([r["estimated_cost_usd"] for r in s3])

    def _ratio(num: float, den: float) -> str:
        if den == 0 or math.isnan(num) or math.isnan(den):
            return "—"
        return f"{num / den:.2f}×"

    body = [
        "## star1 vs star3 — head-to-head (P50 medians)",
        "",
        "| metric | star1 | star3 | star3/star1 |",
        "|---|---|---|---|",
        f"| wall_time_s (full run) | {s1_wall:.2f} s | {s3_wall:.2f} s | {_ratio(s3_wall, s1_wall)} |",
        f"| workers_wall_s_max (critical path) | {s1_workers_max:.2f} s | {s3_workers_max:.2f} s | {_ratio(s3_workers_max, s1_workers_max)} |",
        f"| per-edge latency | {s1_per_edge:.2f} ms | {s3_per_edge:.2f} ms | {_ratio(s3_per_edge, s1_per_edge)} |",
        f"| total tokens per run | {s1_tokens:.0f} | {s3_tokens:.0f} | {_ratio(s3_tokens, s1_tokens)} |",
        f"| estimated cost per run | ${s1_cost:.4f} | ${s3_cost:.4f} | {_ratio(s3_cost, s1_cost)} |",
        "",
        "**Interpretation guide (numbers above, not commentary):**",
        "- A `star3/star1` ratio < 3.0× on wall_time_s indicates the parallel "
        "fan-out amortized would-be-serial work.",
        "- A `star3/star1` ratio > 1.0× on per-edge latency indicates the "
        "leader's `/api/_inter-agent/ingest` path serialized 3 concurrent "
        "POSTs (Werkzeug single-threaded handler bottleneck).",
        "- A `star3/star1` ratio ≈ 3.0× on total tokens reflects the 3× more "
        "claude `-p` invocations in star3.",
        "",
    ]
    return "\n".join(body)


# ─── per-run host-attribution audit ─────────────────────────────────────────


def _attribution_audit(runs: list[dict]) -> str:
    rows = ["| scenario_id | config | worker | assigned | observed | status |",
            "|---|---|---|---|---|---|"]
    drift_count = 0     # observed != assigned, run was successful
    missing_count = 0   # no observed (graph_fetch_failed etc.)
    success_pairs = 0
    match_pairs = 0
    for r in runs:
        run_ok = bool(r.get("success"))
        for w in r.get("workers", []):
            ok = w.get("host_match", False)
            obs = w.get("observed_host") or ""
            if run_ok:
                success_pairs += 1
                if ok:
                    match_pairs += 1
                    status = "✓"
                else:
                    drift_count += 1
                    status = "✗ DRIFT"
            else:
                if not obs:
                    missing_count += 1
                    status = "— (run failed, no graph data)"
                elif ok:
                    status = "✓ (run failed, observed before fail)"
                else:
                    drift_count += 1
                    status = "✗ DRIFT (run failed)"
            rows.append(
                f"| {r['scenario_id']} | {r['config']} | {w['label']} | "
                f"{w['assigned_host']} | {obs or '—'} | {status} |"
            )
    pct = (match_pairs / success_pairs * 100.0) if success_pairs else float("nan")
    body = [
        "## Host-attribution audit (Pitfall #1 stress under fan-out)",
        "",
        "Demo-6 docs §8 pitfall #1: `_host/<H>` URL prefix must be present from "
        "interaction #1 or `scenario_adapter._peer_bundle` pins the agent to "
        "the wrong host permanently. star3 runs 3 concurrent edge POSTs from "
        "a single controller node — this audit checks each worker landed on "
        "its assigned host in the resulting graph.",
        "",
        f"**On successful runs:** {match_pairs}/{success_pairs} worker→host "
        f"pairs matched ({pct:.1f}%) — **{drift_count} real drift events.**",
        f"**On failed runs:** {missing_count} (worker × run) pair(s) had no "
        f"observed host (graph fetch failed before attribution could be made). "
        f"These are missing-data, NOT drift.",
        "",
        *rows,
        "",
    ]
    return "\n".join(body)


# ─── header ────────────────────────────────────────────────────────────────


def _header(runs: list[dict]) -> str:
    total = len(runs)
    ok = len(_ok(runs))
    soft = sum(1 for r in runs
               if str(r.get("fail_reason", "")).startswith("rate_limited_soft_fail"))
    failed_hard = total - ok - soft
    by_cfg: dict[str, int] = {}
    for r in runs:
        by_cfg[r.get("config", "?")] = by_cfg.get(r.get("config", "?"), 0) + 1
    cumulative_cost = 0.0
    for r in runs:
        cumulative_cost = max(cumulative_cost, r.get("cumulative_cost_usd_after", 0.0))
    cfg_str = ", ".join(f"{k}={v}" for k, v in sorted(by_cfg.items()))
    return "\n".join([
        "# bench_demo6_star — Test 5 (distributed star topology)",
        "",
        f"- Total runs in `runs.jsonl`: **{total}** "
        f"(success={ok}, hard-failed={failed_hard}, rate-limit soft-failed={soft})",
        f"- Per-config counts: {cfg_str or 'none'}",
        f"- Cumulative estimated cost: **${cumulative_cost:.3f}**",
        "",
        "## Topology",
        "",
        "- **star1**: 1 controller (harness-driven, no `claude -p`) → 1 worker "
        "(`claude -p` running demo-6's executor prompt).",
        "- **star3**: 1 controller → 3 workers in parallel (`ThreadPoolExecutor` "
        "fan-out). Each worker is on its own SLURM-allocated compute node.",
        "",
        "## Methodology notes",
        "",
        "- **Parallel fan-out.** Workers are dispatched concurrently via "
        "`concurrent.futures.ThreadPoolExecutor(max_workers=N)`; each thread "
        "issues a blocking `srun --jobid=… -w <worker_host> claude -p`. After "
        "all workers return, edge `start` POSTs are fired in parallel from the "
        "controller node (`srun -w <controller_host> curl …`) — that's what "
        "the per-edge latency rows measure.",
        "- **Edge latency.** Same caveat as bench_demo6: `/api/_inter-agent/ingest` "
        "stores caller-supplied `latency_ms`, it does not measure. This harness "
        "substitutes the measured curl RTT, then closes the pair with an "
        "untimed `done` POST.",
        "- **Session-id discipline.** Per multi-agent-visualization.md §8 "
        "pitfall #1, every worker uses a session id of the form "
        "`worker{N}-{scenario_id}` — unique across runs (avoids `_peer_bundle` "
        "collapse) AND unique among the 3 workers within a single run "
        "(avoids fan-out merge).",
        "- **Host attribution.** `_host/<H>` URL prefix is set from the worker's "
        "assigned node. The audit below checks the graph's `agent.host` field "
        "matches expectation.",
        "- **Rate-limit soft fail.** Any worker with `interaction_count ≤ 2` "
        "marks the run as soft-fail (run not counted, no retry, +60 s pacing).",
        "- **Cost estimate.** `total_tokens` from the graph multiplied by "
        "Sonnet 4-6 list rates, assuming an 80/20 input/output split (graph "
        "doesn't expose direction breakdown). Real billing is in the console.",
        "",
    ])


# ─── entrypoint ────────────────────────────────────────────────────────────


def write_summary(results_dir: Path) -> int:
    runs = _load(results_dir)
    if not runs:
        print(f"no runs in {results_dir / 'runs.jsonl'}")
        return 1
    parts = [
        _header(runs),
        "## Per-config tables",
        "",
        _config_block("star1", runs),
        _config_block("star3", runs),
        _comparison(runs),
        _attribution_audit(runs),
    ]
    out = results_dir / "SUMMARY_STAR.md"
    out.write_text("\n".join(parts))
    print(f"wrote {out}")
    return 0
