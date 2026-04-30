#!/usr/bin/env python3
"""Fig 13 — Star fan-out: critical path vs serial baseline.

For each successful run, plot two stacked-style markers:
  * `workers_wall_s_max` (the parallel critical path — what fan-out actually
    cost),
  * `workers_wall_s_sum` (the would-be-serial baseline — sum of per-worker
    walls if dispatched one at a time).
star1 has only one worker so max = sum and the bars overlap (sanity).
star3 should show a clear max ≪ sum gap proving cross-host parallelism.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import successful_sweep_runs, by_config, median_stdev, write_caption


def main() -> None:
    apply_paper_style()
    grouped = by_config(successful_sweep_runs())
    cfgs = ["star1", "star3"]
    n_runs = [len(grouped.get(c, [])) for c in cfgs]
    if not all(n_runs):
        raise SystemExit(f"missing data: star1={n_runs[0]}, star3={n_runs[1]}")

    max_vals = [
        [r["workers_wall_s_max"] for r in grouped[c]] for c in cfgs
    ]
    sum_vals = [
        [r["workers_wall_s_sum"] for r in grouped[c]] for c in cfgs
    ]

    max_med = [median_stdev(v)[0] for v in max_vals]
    max_sd  = [median_stdev(v)[1] for v in max_vals]
    sum_med = [median_stdev(v)[0] for v in sum_vals]
    sum_sd  = [median_stdev(v)[1] for v in sum_vals]

    fig, ax = plt.subplots(figsize=(3.8, 2.8))
    bar_w = 0.36
    x = np.arange(len(cfgs), dtype=float)

    ax.bar(x - bar_w / 2, sum_med, width=bar_w, yerr=sum_sd,
           color=WONG["vermillion"], edgecolor="white", linewidth=0.6,
           capsize=2.5,
           label="serial baseline (Σ per-worker wall)",
           error_kw={"elinewidth": 0.7, "capthick": 0.7})
    ax.bar(x + bar_w / 2, max_med, width=bar_w, yerr=max_sd,
           color=WONG["bluish_green"], edgecolor="white", linewidth=0.6,
           capsize=2.5,
           label="parallel critical path (max per-worker wall)",
           error_kw={"elinewidth": 0.7, "capthick": 0.7})

    # Individual-run dots overlaid on each bar (n=3 spread).
    for i, c in enumerate(cfgs):
        for v in sum_vals[i]:
            ax.scatter([x[i] - bar_w / 2], [v], color=WONG["black"],
                       s=10, alpha=0.55, zorder=3, edgecolors="none")
        for v in max_vals[i]:
            ax.scatter([x[i] + bar_w / 2], [v], color=WONG["black"],
                       s=10, alpha=0.55, zorder=3, edgecolors="none")

    # Speedup annotation between the two star3 bars (drawn with an arrow so
    # the visual reads max ↔ sum).
    s3_speedup = sum_med[1] / max_med[1] if max_med[1] else float("nan")
    y_arrow = (sum_med[1] + max_med[1]) / 2
    ax.annotate("", xy=(x[1] + bar_w / 2, max_med[1] + 4),
                xytext=(x[1] - bar_w / 2, sum_med[1] - 4),
                arrowprops=dict(arrowstyle="->", color=WONG["black"],
                                lw=0.8, shrinkA=2, shrinkB=2))
    ax.text(x[1] + bar_w / 2 + 0.04, y_arrow,
            f"{s3_speedup:.2f}× speedup",
            ha="left", va="center", fontsize=8, color=WONG["black"],
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor="0.7", linewidth=0.5))

    ax.set_xticks(x)
    ax.set_xticklabels([f"{c}\n(n={k})" for c, k in zip(cfgs, n_runs)])
    ax.set_ylabel("Worker wall time (s)")
    ax.set_title("Star fan-out: critical path vs serial baseline")
    ax.set_ylim(0, max(sum_med) * 1.25)
    ax.set_xlim(-0.6, 1.8)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", handlelength=1.6)

    out = Path(__file__).resolve().parent / "fig13_star_fanout_critical_path"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))

    write_caption(out.with_suffix(".caption.txt"), (
        f"Cross-host fan-out parallelism for the star bench. star1 dispatches "
        f"one worker (1 controller → 1 worker on a remote node); star3 "
        f"dispatches three workers in parallel via "
        f"`concurrent.futures.ThreadPoolExecutor`. For each run we measure the "
        f"per-worker `claude -p` wall time and report two aggregates: the "
        f"critical path (max) — what the fan-out actually costs end-to-end — "
        f"and the serial baseline (sum) — what running the same workers one "
        f"at a time would have taken. star1 trivially has max = sum (one "
        f"worker). star3 shows max = {max_med[1]:.1f} s vs sum = "
        f"{sum_med[1]:.1f} s, a ≈{s3_speedup:.2f}× speedup, close to the ideal "
        f"3× the topology permits. The shortfall vs ideal is consistent with "
        f"per-node `claude -p` startup variance (each thread issues its own "
        f"`srun … claude -p`)."
    ))


if __name__ == "__main__":
    main()
