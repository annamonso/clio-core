#!/usr/bin/env python3
"""Fig 14 — Star: per-edge ingest latency, star1 vs star3.

Distribution of `edge_latency_ms` per worker, separated by config. star1
fires one cross-host start POST per run; star3 fires three in parallel from
a single controller node against the leader's `/api/_inter-agent/ingest`
single-threaded Werkzeug handler. If star3's median rises vs star1, the
leader is serializing the concurrent POSTs.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import (
    all_sweep_runs, by_config, per_edge_values, median_stdev, write_caption,
)


def main() -> None:
    apply_paper_style()
    # Use ALL sweep runs (including star3-003 whose run-level success failed at
    # graph_fetch). Edge POSTs themselves succeeded — the per-edge latency is
    # an independent, valid measurement and including it triples the star3
    # sample to a more usable 9.
    grouped = by_config(all_sweep_runs())

    s1 = per_edge_values([r for r in grouped.get("star1", []) if r.get("success")])
    s3 = per_edge_values(grouped.get("star3", []))   # include star3-003

    if not s1 or not s3:
        raise SystemExit(f"missing data: star1={len(s1)}, star3={len(s3)}")

    s1_med, s1_sd = median_stdev(s1)
    s3_med, s3_sd = median_stdev(s3)

    fig, ax = plt.subplots(figsize=(3.8, 2.8))

    # Strip plot with median markers — n is small so a box plot would mislead
    # by drawing IQRs from too few points.
    rng = np.random.default_rng(seed=42)
    for i, (label, vals, color) in enumerate([
        ("star1", s1, WONG["blue"]),
        ("star3", s3, WONG["vermillion"]),
    ]):
        jitter = rng.uniform(-0.12, 0.12, size=len(vals))
        ax.scatter(np.full(len(vals), i) + jitter, vals,
                   color=color, alpha=0.65, s=22, edgecolors="white",
                   linewidth=0.5, zorder=3, label=f"{label} (n={len(vals)})")
        # Median tick.
        med, _ = median_stdev(vals)
        ax.hlines(med, i - 0.22, i + 0.22, color=color, linewidth=1.4,
                  zorder=4)

    ax.set_xticks([0, 1])
    ax.set_xticklabels([f"star1\nn={len(s1)}", f"star3\nn={len(s3)}"])
    ax.set_ylabel("Per-edge ingest latency (ms)")
    ax.set_title("Cross-host edge POST latency: star1 vs star3")
    ax.set_ylim(0, max(max(s1), max(s3)) * 1.20)
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", handlelength=0.6)

    # Inline annotation: medians and ratio. Anchored bottom-right so it
    # cannot occlude the star1 outlier (~36 ms) at top-left.
    ratio = s3_med / s1_med if s1_med else float("nan")
    ax.text(0.98, 0.66,
            f"P50 star1 = {s1_med:.2f} ms\n"
            f"P50 star3 = {s3_med:.2f} ms\n"
            f"ratio = {ratio:.2f}×",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor="white", edgecolor="0.7", linewidth=0.5))

    out = Path(__file__).resolve().parent / "fig14_star_per_edge_latency"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))

    write_caption(out.with_suffix(".caption.txt"), (
        f"Distribution of per-edge ingest latency (`edge_latency_ms`) measured "
        f"as the controller→leader curl RTT for a `start` POST to "
        f"`/api/_inter-agent/ingest`. star1 fires one POST per run; star3 "
        f"fires three concurrent POSTs from a single controller node against "
        f"the leader's single-threaded Werkzeug handler. star3 includes the "
        f"three edge measurements from star3-003 (whose run-level success "
        f"failed at the post-run graph fetch — edge POSTs themselves "
        f"succeeded). star1 P50 = {s1_med:.2f} ms; star3 P50 = "
        f"{s3_med:.2f} ms; ratio = {ratio:.2f}×. A ratio close to 1.0× "
        f"indicates the leader's ingest path is fast enough that 3× "
        f"concurrent POSTs do not visibly serialize at this scale. The single "
        f"~36 ms outlier in star1 is consistent with one-off scheduling jitter."
    ))


if __name__ == "__main__":
    main()
