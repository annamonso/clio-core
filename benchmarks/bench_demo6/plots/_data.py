"""Data loader for the demo-6 figures. Reads runs.jsonl and per-scenario JSONs.

`success=True` filter only — soft-fails (rate-limited) and hard-fails are excluded
per the SUMMARY.md methodology note.
"""
from __future__ import annotations
import json
from pathlib import Path
from statistics import median, stdev


RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def successful_runs(sweep: str) -> list[dict]:
    runs = _load_jsonl(RESULTS_DIR / "runs.jsonl")
    return [r for r in runs if r.get("success") and r.get("sweep") == sweep]


def sweep_a_edges() -> list[float]:
    return sorted(r["edge_latency_ms"] for r in successful_runs("a"))


def sweep_b_by_size() -> dict[int, list[float]]:
    """Map payload_size_bytes → sorted list of edge_latency_ms values."""
    out: dict[int, list[float]] = {}
    for r in successful_runs("b"):
        size = int(r["config"]["payload_size_bytes"])
        out.setdefault(size, []).append(r["edge_latency_ms"])
    for k in out:
        out[k].sort()
    return out


def sweep_c_by_config() -> dict[str, dict[str, list[float]]]:
    """Return {'1h': {'edge': [...], 'wall': [...]}, '2h': {...}}."""
    out: dict[str, dict[str, list[float]]] = {
        "1h": {"edge": [], "wall": []},
        "2h": {"edge": [], "wall": []},
    }
    for r in successful_runs("c"):
        cfg = r["config"]
        label = "1h" if cfg["planner_host"] == cfg["executor_host"] else "2h"
        out[label]["edge"].append(r["edge_latency_ms"])
        out[label]["wall"].append(r["wall_time_s"])
    for label in out:
        for k in out[label]:
            out[label][k].sort()
    return out


def stats(values: list[float]) -> tuple[float, float]:
    """Return (median, stdev). stdev is 0 when n<2."""
    if not values:
        return float("nan"), float("nan")
    if len(values) == 1:
        return values[0], 0.0
    return median(values), stdev(values)


def write_caption(plot_path: Path, text: str) -> None:
    """Write a caption.txt sibling alongside the plot file."""
    cap = plot_path.with_suffix(".caption.txt")
    cap.write_text(text.strip() + "\n")
