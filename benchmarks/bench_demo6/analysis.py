"""Read benchmarks/bench_demo6/results/runs.jsonl + per-run JSON,
write SUMMARY.md with three tables and a Sweep A ASCII histogram.

Numbers only — no interpretation. Caveats are stated in plain English where
the framework's measurement model creates an ambiguity (edge latency_ms
is caller-reported by the framework; this harness substitutes a measured
cross-host RTT — that distinction matters).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Iterable


# ─── stats helpers ──────────────────────────────────────────────────────────

def _percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile, Numpy-default behavior."""
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def _stats(values: Iterable[float]) -> dict:
    vs = [float(v) for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
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


def _fmt(stats: dict, unit: str = "") -> str:
    if stats["n"] == 0:
        return "—"
    suf = f" {unit}" if unit else ""
    return (
        f"{stats['p50']:.2f}{suf} / {stats['p90']:.2f}{suf} / "
        f"{stats['max']:.2f}{suf} / {stats['stdev']:.2f}{suf}"
    )


# ─── ASCII histogram ────────────────────────────────────────────────────────

def ascii_histogram(values: list[float], bins: int = 20, width: int = 50,
                    label: str = "ms") -> str:
    if not values:
        return "(no data)"
    lo, hi = min(values), max(values)
    if hi == lo:
        return f"all {len(values)} samples == {lo:.2f} {label}"
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / (hi - lo) * bins), bins - 1)
        counts[idx] += 1
    peak = max(counts) or 1
    lines = []
    for i in range(bins):
        bar = "#" * int(counts[i] / peak * width)
        lines.append(
            f"  [{edges[i]:>8.2f} - {edges[i+1]:>8.2f}] "
            f"{counts[i]:>3} | {bar}"
        )
    return "\n".join(lines)


# ─── data loading ───────────────────────────────────────────────────────────

def _load_runs(results_dir: Path) -> list[dict]:
    jsonl = results_dir / "runs.jsonl"
    if not jsonl.exists():
        return []
    out = []
    for line in jsonl.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _successful(runs: list[dict]) -> list[dict]:
    return [r for r in runs if r.get("success")]


# ─── per-sweep tables ───────────────────────────────────────────────────────

def _sweep_a_table(runs: list[dict]) -> str:
    sub = _successful([r for r in runs if r.get("sweep") == "a"])
    n = len(sub)
    if n == 0:
        return "## Sweep A — Variance (baseline)\n\n_No successful Sweep A runs._\n"

    edge = _stats(r["edge_latency_ms"] for r in sub)
    wall = _stats(r["wall_time_s"] for r in sub)
    plan_int = _stats(r["planner_interactions"] for r in sub)
    exec_int = _stats(r["executor_interactions"] for r in sub)
    plan_tok = _stats(r["planner_tokens"] for r in sub)
    exec_tok = _stats(r["executor_tokens"] for r in sub)

    body = [
        f"## Sweep A — Variance (baseline, N={n} successful)",
        "",
        "| metric | P50 / P90 / max / stdev |",
        "|---|---|",
        f"| edge_latency_ms (cross-host start POST RTT) | {_fmt(edge, 'ms')} |",
        f"| wall_time_s (full scenario) | {_fmt(wall, 's')} |",
        f"| planner.interaction_count | {_fmt(plan_int)} |",
        f"| executor.interaction_count | {_fmt(exec_int)} |",
        f"| planner.total_tokens | {_fmt(plan_tok)} |",
        f"| executor.total_tokens | {_fmt(exec_tok)} |",
        "",
        "### Sweep A — edge_latency_ms distribution",
        "",
        "```",
        ascii_histogram([r["edge_latency_ms"] for r in sub], bins=20, width=50),
        "```",
        "",
    ]
    return "\n".join(body)


def _sweep_b_table(runs: list[dict]) -> str:
    sub = _successful([r for r in runs if r.get("sweep") == "b"])
    n = len(sub)
    if n == 0:
        return "## Sweep B — Payload size\n\n_No successful Sweep B runs._\n"

    by_size: dict[int, list[dict]] = {}
    for r in sub:
        size = int(r.get("config", {}).get("payload_size_bytes", 0))
        by_size.setdefault(size, []).append(r)

    rows = ["| payload_bytes | N | edge_latency P50 / P90 / max / stdev (ms) | wall_time P50 (s) |",
            "|---:|---:|---|---:|"]
    for size in sorted(by_size):
        rs = by_size[size]
        edge = _stats(r["edge_latency_ms"] for r in rs)
        wall = _stats(r["wall_time_s"] for r in rs)
        rows.append(
            f"| {size} | {len(rs)} | {_fmt(edge, 'ms')} | {wall['p50']:.2f} |"
        )

    body = [
        f"## Sweep B — Payload size (N={n} successful, B1 measurement)",
        "",
        "**Measurement note (B1):** edge_latency_ms is the harness's measured "
        "round-trip time of the `start` POST issued from the executor host to "
        "the leader's `/api/_inter-agent/ingest` endpoint, with the padded "
        "payload in the request body. This is **not** the production MCP relay "
        "path — it characterizes payload-size sensitivity of the cross-host "
        "ingest path under controlled conditions.",
        "",
        "**Limitation of the framework as observed:** "
        "`/api/_inter-agent/ingest` accepts `latency_ms` as a caller-supplied "
        "field (`inter_agent.py:99`). The framework does not measure edge "
        "latency itself; whatever the caller posts is what shows up in "
        "`/api/scenarios/<sid>/graph`. This harness substitutes a measured "
        "RTT, but in production deployments the field's reliability depends "
        "on the caller's instrumentation.",
        "",
        *rows,
        "",
    ]
    return "\n".join(body)


def _sweep_c_table(runs: list[dict]) -> str:
    sub = _successful([r for r in runs if r.get("sweep") == "c"])
    n = len(sub)
    if n == 0:
        return "## Sweep C — Single-host vs two-host\n\n_No successful Sweep C runs._\n"

    def _bucket(r: dict) -> str:
        cfg = r.get("config", {})
        return "1h" if cfg.get("planner_host") == cfg.get("executor_host") else "2h"

    one = [r for r in sub if _bucket(r) == "1h"]
    two = [r for r in sub if _bucket(r) == "2h"]

    def _row(label: str, rs: list[dict]) -> str:
        if not rs:
            return f"| {label} | 0 | — | — | — | — |"
        wall = _stats(r["wall_time_s"] for r in rs)
        edge = _stats(r["edge_latency_ms"] for r in rs)
        plan_int = _stats(r["planner_interactions"] for r in rs)
        exec_int = _stats(r["executor_interactions"] for r in rs)
        return (
            f"| {label} | {len(rs)} | "
            f"{wall['p50']:.2f} / {wall['p90']:.2f} | "
            f"{edge['p50']:.2f} / {edge['p90']:.2f} | "
            f"{plan_int['p50']:.0f} | {exec_int['p50']:.0f} |"
        )

    body = [
        f"## Sweep C — Single-host vs two-host (N={n} successful)",
        "",
        "**Configurations.** `1h` = both planner and executor on `LEADER_HOST`; "
        "`2h` = planner on `LEADER_HOST`, executor on `PEER_HOST`. Same demo-6 "
        "workload in both. `edge_latency_ms` for `1h` is a localhost POST RTT "
        "and serves as the same-host control.",
        "",
        "**What the 1h vs 2h delta isolates.** Both arms incur identical "
        "subprocess fork, `srun` setup, and Flask ingest-handler overhead — "
        "the only systematic difference between them is whether the POST "
        "traverses the cluster network or stays on loopback. The "
        "`edge_latency_ms` delta is therefore a measurement of the cluster "
        "network channel cost specifically, not a measurement of the broader "
        "cost of \"running both agents on the same machine\" (which would "
        "additionally entail CPU/memory contention effects that are not "
        "isolated by this design).",
        "",
        "| config | N | wall_time P50/P90 (s) | edge_latency P50/P90 (ms) | planner.int_count P50 | executor.int_count P50 |",
        "|---|---:|---|---|---:|---:|",
        _row("1h (single-host)", one),
        _row("2h (two-host)", two),
        "",
    ]
    return "\n".join(body)


# ─── header / global notes ──────────────────────────────────────────────────

def _header(runs: list[dict]) -> str:
    total = len(runs)
    ok = len(_successful(runs))
    soft = sum(1 for r in runs if r.get("fail_reason") == "rate_limited_soft_fail")
    failed_hard = total - ok - soft
    by_sweep: dict[str, int] = {}
    for r in runs:
        by_sweep[r.get("sweep", "?")] = by_sweep.get(r.get("sweep", "?"), 0) + 1
    sweep_counts = ", ".join(f"{k}={v}" for k, v in sorted(by_sweep.items()))
    return "\n".join([
        "# bench_demo6 — characterization summary",
        "",
        f"- Total runs in `runs.jsonl`: **{total}**  "
        f"(success={ok}, hard-failed={failed_hard}, "
        f"rate-limit soft-failed={soft})",
        f"- Per-sweep counts (raw): {sweep_counts or 'none'}",
        f"- Rate-limit soft-fails are excluded from all P50/P90/max/stdev "
        f"calculations below — they reflect Anthropic's per-org token-rate "
        f"limit (10K input tok/min on the demo org), not framework behavior.",
        "",
        "## Methodology notes",
        "",
        "- **Edge latency.** The framework's `/api/_inter-agent/ingest` endpoint "
        "stores caller-supplied `latency_ms` verbatim — it does not measure the "
        "cross-host call itself. This harness measures latency on its own POST "
        "round-trip from the executor host to the leader's ingest endpoint "
        "(carrying the padded payload), and substitutes that into the `done` "
        "event. Sweep A and Sweep B's `edge_latency_ms` are therefore real "
        "measured RTTs, not the framework's reported value of an unmeasured "
        "production call. Sweep C's `1h` configuration measures a localhost RTT.",
        "- **Per-agent interaction_count and total_tokens** come from "
        "`/api/scenarios/<sid>/graph` and are sourced from the proxy's "
        "`InteractionRecord` blobs (Path A, in-memory). A `dt_demo_server` "
        "restart wipes these between runs; the harness aborts the sweep if "
        "it detects one.",
        "- **wall_time_s** is the harness's monotonic-clock measurement of the "
        "full scenario: planner srun + executor srun + cross-host edge POST + "
        "graph fetch.",
        "- **Pacing.** Flat 90 s between runs (≈8K input tok/min, under the "
        "demo org's 10K/min limit). 60 s pause + fresh `scenario_id` on retry. "
        "Rate-limited runs (`plan_int ≤ 2 AND exec_int ≤ 2`) are auto-classified "
        "as soft-fails, excluded from analysis, NOT retried, and trigger an "
        "extra 60 s cooldown before the next run. 429s on Task subagents are "
        "non-fatal per `multi-agent-visualization.md` §8 pitfall #5. Sweep B's "
        "100 KB payload runs hit `graph_fetch_failed` retries due to Werkzeug "
        "single-thread bottlenecks (large POST + concurrent graph fetch); they "
        "succeed after retry but with higher tail wall-time.",
        "- **Numbers, not interpretation.** P50 / P90 / max / stdev only.",
        "",
    ])


# ─── entrypoint ─────────────────────────────────────────────────────────────

def write_summary(results_dir: Path) -> int:
    runs = _load_runs(results_dir)
    if not runs:
        print(f"no runs in {results_dir / 'runs.jsonl'}")
        return 1

    parts = [
        _header(runs),
        _sweep_a_table(runs),
        _sweep_b_table(runs),
        _sweep_c_table(runs),
    ]
    out = results_dir / "SUMMARY.md"
    out.write_text("\n".join(parts))
    print(f"wrote {out}")
    return 0
