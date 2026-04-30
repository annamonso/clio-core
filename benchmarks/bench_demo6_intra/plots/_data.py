"""Load + summarize bench_demo6_intra runs for the figure deck.

Source of truth: ../results_intra/runs.jsonl (already pruned of pre-restart
diagnostic smokes).
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results_intra"

# Per the spec: only the n=3-per-level sweep runs (intra-nN-NNN). The single
# post-restart smoke (intra-smoke-...) used the same harness but isn't part of
# the formal sweep, so it's excluded from the plots.
SWEEP_PREFIX = "intra-n"


def _load() -> list[dict]:
    fp = RESULTS_DIR / "runs.jsonl"
    out: list[dict] = []
    for line in fp.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def sweep_runs() -> list[dict]:
    """Successful runs from the formal N=[1,4,10] x n=3 sweep."""
    return [
        r for r in _load()
        if r.get("success")
        and r.get("scenario_id", "").startswith(SWEEP_PREFIX)
    ]


def by_n() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in sweep_runs():
        out.setdefault(int(r["n_tools"]), []).append(r)
    return out


def walls_by_n() -> dict[int, list[float]]:
    return {n: [float(r["wall_time_s"]) for r in rs] for n, rs in by_n().items()}


def bash_counts_by_n() -> dict[int, list[int]]:
    return {
        n: [int(r["bash_tool_calls_total"]) for r in rs]
        for n, rs in by_n().items()
    }


def integrity_pcts(rs: list[dict]) -> dict[str, float]:
    """Returns the three-metric integrity (% of runs)."""
    if not rs:
        return {"count_correct": 0.0, "ids_unique": 0.0, "contained": 0.0}
    n = len(rs)
    return {
        "count_correct": 100.0 * sum(
            1 for r in rs if r["bash_tool_calls_total"] == r["n_tools"]
        ) / n,
        "ids_unique":    100.0 * sum(1 for r in rs if r["tool_call_ids_unique"]) / n,
        "contained":     100.0 * sum(
            1 for r in rs if r["single_interaction_containment"]
        ) / n,
    }


def median_stdev(values: list[float]) -> tuple[float, float]:
    if not values:
        return float("nan"), 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.median(values), statistics.stdev(values)


def write_caption(out_path: Path, text: str) -> None:
    out_path.write_text(text.rstrip() + "\n")
