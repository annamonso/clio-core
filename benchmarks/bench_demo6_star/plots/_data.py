"""Load + summarize bench_demo6_star runs for the figure deck.

Source of truth: ../results_star/runs.jsonl. The formal sweep is
star{1,3}-NNN; smokes (star{1,3}-smoke-…) are excluded for consistency
with the intra deck unless explicitly opted in.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results_star"

SWEEP_PREFIX = ("star1-", "star3-")  # must NOT match "*-smoke-…"


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


def _is_sweep(r: dict) -> bool:
    sid = r.get("scenario_id", "")
    return sid.startswith(SWEEP_PREFIX) and "smoke" not in sid


def all_sweep_runs() -> list[dict]:
    """All sweep-formatted runs, regardless of overall success.

    star3-003 falls in here: workers + edges succeeded but the post-run graph
    fetch timed out. For per-worker / per-edge plots its data is valid; for
    run-level metrics (interaction_count, total_tokens) it is not."""
    return [r for r in _load() if _is_sweep(r)]


def successful_sweep_runs() -> list[dict]:
    """Only runs flagged success=True (graph fetched, integrity passed)."""
    return [r for r in all_sweep_runs() if r.get("success")]


def by_config(runs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in runs:
        out.setdefault(r.get("config", "?"), []).append(r)
    return out


def per_edge_values(runs: list[dict]) -> list[float]:
    """Flatten per-worker edge_latency_ms across runs (only edge_ok edges)."""
    out: list[float] = []
    for r in runs:
        for w in r.get("workers", []):
            if w.get("edge_ok") and w.get("edge_latency_ms", 0) > 0:
                out.append(float(w["edge_latency_ms"]))
    return out


def median_stdev(values: list[float]) -> tuple[float, float]:
    if not values:
        return float("nan"), 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.median(values), statistics.stdev(values)


def write_caption(out_path: Path, text: str) -> None:
    out_path.write_text(text.rstrip() + "\n")
