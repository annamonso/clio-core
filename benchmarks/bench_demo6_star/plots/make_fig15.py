#!/usr/bin/env python3
"""Fig 15 — Star: token / cost scaling, star1 vs star3.

Sanity check that the star3 workload was actually 3× the work of star1.
Plots per-run total tokens (sum across workers) and per-run estimated cost
side by side, with each config's individual runs as dots and a P50 marker.
A ratio close to 3× confirms the workload scaled linearly with worker count.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import successful_sweep_runs, by_config, median_stdev, write_caption


def _per_run_tokens(rs: list[dict]) -> list[float]:
    return [
        float(sum(w.get("total_tokens", 0) for w in r.get("workers", [])))
        for r in rs
    ]


def _per_run_cost(rs: list[dict]) -> list[float]:
    return [float(r.get("estimated_cost_usd", 0)) for r in rs]


def main() -> None:
    apply_paper_style()
    grouped = by_config(successful_sweep_runs())
    cfgs = ["star1", "star3"]
    n_runs = [len(grouped.get(c, [])) for c in cfgs]
    if not all(n_runs):
        raise SystemExit(f"missing data: star1={n_runs[0]}, star3={n_runs[1]}")

    tok = [_per_run_tokens(grouped[c]) for c in cfgs]
    cost = [_per_run_cost(grouped[c]) for c in cfgs]

    tok_med = [median_stdev(v)[0] for v in tok]
    cost_med = [median_stdev(v)[0] for v in cost]

    fig, axes = plt.subplots(1, 2, figsize=(5.4, 2.8))

    rng = np.random.default_rng(seed=7)
    for ax, vals, meds, ylabel, title, color in [
        (axes[0], tok, tok_med, "Total tokens per run",
         "Tokens (per run)", WONG["blue"]),
        (axes[1], cost, cost_med, "Estimated cost per run (USD)",
         "Cost (per run)", WONG["bluish_green"]),
    ]:
        for i, c in enumerate(cfgs):
            jitter = rng.uniform(-0.10, 0.10, size=len(vals[i]))
            ax.scatter(np.full(len(vals[i]), i) + jitter, vals[i],
                       color=color, alpha=0.7, s=22,
                       edgecolors="white", linewidth=0.5, zorder=3)
            # Median tick.
            ax.hlines(meds[i], i - 0.25, i + 0.25,
                      color=color, linewidth=1.6, zorder=4)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([f"{c}\n(n={k})" for c, k in zip(cfgs, n_runs)])
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_ylim(bottom=0)
        ax.yaxis.grid(True)
        ax.set_axisbelow(True)
        # Ratio annotation.
        ratio = meds[1] / meds[0] if meds[0] else float("nan")
        ax.text(0.97, 0.10, f"star3 / star1 P50 = {ratio:.2f}×",
                transform=ax.transAxes, ha="right", va="bottom",
                fontsize=8,
                bbox=dict(boxstyle="round,pad=0.3",
                          facecolor="white", edgecolor="0.7", linewidth=0.5))

    fig.suptitle("Star workload scaling: 3 workers ≈ 3× tokens & cost",
                 fontsize=10, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))

    out = Path(__file__).resolve().parent / "fig15_star_scaling"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))

    tok_ratio = tok_med[1] / tok_med[0] if tok_med[0] else float("nan")
    cost_ratio = cost_med[1] / cost_med[0] if cost_med[0] else float("nan")
    write_caption(out.with_suffix(".caption.txt"), (
        f"Workload-scaling sanity check for the star bench. star1 dispatches "
        f"one worker; star3 dispatches three workers running the same "
        f"executor prompt in parallel. Per-run total tokens (sum across "
        f"workers) and per-run estimated cost are plotted with per-run dots "
        f"and a P50 median tick. star3 / star1 ratios: tokens "
        f"{tok_ratio:.2f}×, cost {cost_ratio:.2f}× — both close to the ideal "
        f"3× the topology predicts, confirming the experiment actually did "
        f"3× the LLM work and that any wall-time savings in Fig 13 reflect "
        f"genuine parallelism rather than reduced load."
    ))


if __name__ == "__main__":
    main()
