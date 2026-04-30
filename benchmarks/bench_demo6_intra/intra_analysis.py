"""Read benchmarks/bench_demo6_intra/results_intra/runs.jsonl, write
SUMMARY_INTRA.md.

The framework has no first-class spans / parent_id. The summary reports on
what it actually does capture: per-interaction tool_calls arrays. See
intra_runner.py docstring for the data model.
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
                "max": float("nan"), "min": float("nan"),
                "stdev": float("nan")}
    return {
        "n": len(vs),
        "p50": _percentile(vs, 0.50),
        "p90": _percentile(vs, 0.90),
        "max": max(vs),
        "min": min(vs),
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


def _by_n(runs: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in runs:
        out.setdefault(int(r.get("n_tools", -1)), []).append(r)
    return out


# ─── per-N tables ──────────────────────────────────────────────────────────


def _per_n_block(n: int, runs: list[dict], n1_baseline: float | None) -> str:
    sub = _ok(runs)
    nruns = len(sub)
    if nruns == 0:
        return f"### N={n}\n\n_No successful runs._\n"

    wall = _stats(r["wall_time_s"] for r in sub)
    interactions = _stats(r["interaction_count"] for r in sub)
    bash_count = _stats(r["bash_tool_calls_total"] for r in sub)
    tokens = _stats(r["total_tokens"] for r in sub)
    cost = _stats(r["estimated_cost_usd"] for r in sub)

    contained_pct = sum(
        1 for r in sub if r.get("single_interaction_containment")
    ) / nruns * 100.0
    ids_unique_pct = sum(
        1 for r in sub if r.get("tool_call_ids_unique")
    ) / nruns * 100.0
    correct_count_pct = sum(
        1 for r in sub if r.get("bash_tool_calls_total") == n
    ) / nruns * 100.0

    verdict_breakdown: dict[str, int] = {}
    for r in sub:
        v = r.get("parallelism_verdict", "n_a")
        verdict_breakdown[v] = verdict_breakdown.get(v, 0) + 1
    verdict_str = ", ".join(f"{k}={v}" for k, v in sorted(verdict_breakdown.items()))

    # If we have an N=1 baseline, show the residual: wall(N) - wall(N=1).
    # Parallel tools: residual ≈ TOOL_SLEEP_S (1s).
    # Serialized tools: residual ≈ N * TOOL_SLEEP_S (Ns).
    residual_line = ""
    if n1_baseline is not None and n > 1:
        residual = wall["p50"] - n1_baseline
        expected_serial = float(n)  # N * 1s
        expected_parallel = 1.0      # max(1s) = 1s
        residual_line = (
            f"\n**Wall residual vs N=1 baseline (P50):** "
            f"{residual:.2f} s — parallel-baseline expects ~{expected_parallel:.1f} s, "
            f"serialized-baseline expects ~{expected_serial:.1f} s."
        )

    body = [
        f"### N={n} (n={nruns} successful runs)",
        "",
        "| metric | P50 / P90 / max / stdev |",
        "|---|---|",
        f"| wall_time_s (full run) | {_fmt(wall, 's')} |",
        f"| interactions (planner LLM turns) | {_fmt(interactions)} |",
        f"| Bash tool_calls captured | {_fmt(bash_count)} |",
        f"| total tokens | {_fmt(tokens)} |",
        f"| estimated cost (USD) | {_fmt(cost)} |",
        "",
        f"**Integrity (% of runs):** "
        f"correct count={correct_count_pct:.0f}%, "
        f"all ids unique={ids_unique_pct:.0f}%, "
        f"single-interaction containment={contained_pct:.0f}%",
        "",
        f"**Parallelism verdict breakdown:** {verdict_str}",
        residual_line,
        "",
    ]
    return "\n".join(body)


# ─── failures + integrity audit ─────────────────────────────────────────────


def _failure_audit(runs: list[dict]) -> str:
    rows = ["| scenario_id | N | bash_count | ids_unique | contained | verdict | reason |",
            "|---|---|---|---|---|---|---|"]
    bad = [r for r in runs if not r.get("success") and not r.get("soft_fail")]
    soft = [r for r in runs if r.get("soft_fail")]
    for r in bad:
        rows.append(
            f"| {r['scenario_id']} | {r['n_tools']} | "
            f"{r.get('bash_tool_calls_total', 0)} | "
            f"{r.get('tool_call_ids_unique')} | "
            f"{r.get('single_interaction_containment')} | "
            f"{r.get('parallelism_verdict', '')} | "
            f"{(r.get('fail_reason') or '')[:80]} |"
        )
    for r in soft:
        rows.append(
            f"| {r['scenario_id']} | {r['n_tools']} | — | — | — | — | "
            f"SOFT: {(r.get('fail_reason') or '')[:80]} |"
        )
    body = [
        "## Failures + soft-fails",
        "",
        f"**Hard failures:** {len(bad)}.  "
        f"**Soft-fails (graph fetch):** {len(soft)}.",
        "",
    ]
    if bad or soft:
        body.append("\n".join(rows))
    else:
        body.append("_None._")
    body.append("")
    return "\n".join(body)


def _bash_command_check(runs: list[dict]) -> str:
    """Verify the bash commands recorded match what the prompt asked for.
    Surface any divergence — could indicate the model paraphrased the command
    or substituted Read/TodoWrite/etc."""
    sub = _ok(runs)
    rows = [
        "| scenario_id | N | sample bash commands (first 3) |",
        "|---|---|---|",
    ]
    weird = 0
    for r in sub:
        cmds = (r.get("bash_commands") or [])[:3]
        cmds_str = " · ".join(c[:40] for c in cmds) or "—"
        # A "well-formed" command starts with `sleep ` per the prompt.
        if not all(c.startswith("sleep ") for c in (r.get("bash_commands") or [])):
            weird += 1
        rows.append(f"| {r['scenario_id']} | {r['n_tools']} | `{cmds_str}` |")
    body = [
        "## Bash-command shape audit",
        "",
        "Sanity-check: every captured Bash tool call should start with `sleep `. "
        f"**Runs with at least one off-shape command:** {weird} of {len(sub)}.",
        "",
    ]
    if sub:
        body.append("\n".join(rows))
    body.append("")
    return "\n".join(body)


# ─── header ────────────────────────────────────────────────────────────────


def _header(runs: list[dict]) -> str:
    total = len(runs)
    ok = len(_ok(runs))
    soft = sum(1 for r in runs if r.get("soft_fail"))
    failed_hard = total - ok - soft
    by_n: dict[int, int] = {}
    for r in runs:
        by_n[int(r.get("n_tools", -1))] = by_n.get(int(r.get("n_tools", -1)), 0) + 1
    cumulative_cost = 0.0
    for r in runs:
        cumulative_cost = max(cumulative_cost, r.get("cumulative_cost_usd_after", 0.0))
    n_str = ", ".join(f"N={k}: {v}" for k, v in sorted(by_n.items()))
    return "\n".join([
        "# bench_demo6_intra — Test 6 (intra-agent fan-out)",
        "",
        f"- Total runs in `runs.jsonl`: **{total}** "
        f"(success={ok}, hard-failed={failed_hard}, soft-failed={soft})",
        f"- Per-N counts: {n_str or 'none'}",
        f"- Cumulative estimated cost: **${cumulative_cost:.3f}**",
        "",
        "## What this measures",
        "",
        "One planner agent on a single host issues **N Bash tool calls in a "
        "single LLM turn** (parallel tool_use blocks dispatched concurrently "
        "by Claude Code's harness against a `sleep 1; echo …` shell). Vary "
        "N across {1, 4, 10}, n=3 each. The framework records each LLM turn "
        "as one `InteractionRecord` with nested `response.tool_calls: ToolCall[]` "
        "(see `protocol/include/dt_provenance/protocol/interaction.h:106`). "
        "There is no OpenTelemetry-style span tree; `parent_id` does not exist "
        "at the tool-call level. The questions answered here:",
        "",
        "1. **Is the count preserved?** Does `len(response.tool_calls) == N`?",
        "2. **Are the ids unique?** Each parallel tool emits a distinct `tool_use.id`. "
        "Verify the framework didn't dedup or overwrite under concurrency.",
        "3. **Single-interaction containment?** All N Bash calls in *one* "
        "interaction record (the planner's first response), not split across turns.",
        "4. **Did the SDK actually parallelize?** Wall-time math: parallel "
        "fan-out of N×1 s sleeps adds ~1 s to the run; serialized adds ~N s. "
        "The residual against the N=1 baseline answers this.",
        "",
        "Wall-time interpretation: drive_agent wall ≈ "
        "(LLM turn 1 + tool phase + LLM turn 2 + harness overhead). The "
        "tool phase dominates the difference between N values.",
        "",
    ])


# ─── entrypoint ────────────────────────────────────────────────────────────


def write_summary(results_dir: Path) -> int:
    runs = _load(results_dir)
    if not runs:
        print(f"no runs in {results_dir / 'runs.jsonl'}")
        return 1

    by_n = _by_n(runs)
    n1_runs_ok = _ok(by_n.get(1, []))
    n1_baseline = (
        statistics.median(r["wall_time_s"] for r in n1_runs_ok)
        if n1_runs_ok else None
    )

    parts = [_header(runs), "## Per-N tables", ""]
    for n in sorted(k for k in by_n.keys() if k >= 1):
        parts.append(_per_n_block(n, by_n[n], n1_baseline))
    parts.append(_failure_audit(runs))
    parts.append(_bash_command_check(runs))

    out = results_dir / "SUMMARY_INTRA.md"
    out.write_text("\n".join(parts))
    print(f"wrote {out}")
    return 0
