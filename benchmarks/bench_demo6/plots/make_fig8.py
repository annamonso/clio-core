#!/usr/bin/env python3
"""Fig 8 — Sweep A variance histogram.

Distribution of edge_latency_ms across 6 successful Sweep A runs.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import sweep_a_edges, stats, write_caption


def main() -> None:
    apply_paper_style()
    edges = sweep_a_edges()
    p50, sd = stats(edges)
    n = len(edges)

    fig, ax = plt.subplots(figsize=(3.8, 2.8))
    ax.hist(edges, bins=10, range=(7.0, 12.0),
            color=WONG["blue"], edgecolor="white", linewidth=0.6)

    # Median dashed line + shaded ±1 stdev band centred on median.
    ax.axvspan(p50 - sd, p50 + sd, color=WONG["blue"], alpha=0.10, zorder=0)
    ax.axvline(p50, color=WONG["black"], linestyle="--", linewidth=0.9,
               label=f"median = {p50:.2f} ms")

    ax.set_xlim(7.0, 12.0)
    ax.set_ylim(0, 4)                       # headroom for the upper-right note
    ax.set_yticks([0, 1, 2, 3, 4])           # integer counts only
    ax.set_xlabel("Edge latency (ms)")
    ax.set_ylabel("Count")
    ax.set_title("Cross-host edge latency distribution, demo-6 baseline")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)

    ax.text(0.97, 0.96,
            f"n = {n}  ·  median {p50:.2f} ms  ·  stdev {sd:.2f} ms",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor="white", edgecolor="0.7", linewidth=0.5))

    out = Path(__file__).resolve().parent / "fig8_sweep_a_variance"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))
    plt.close(fig)

    write_caption(out, """
Six independent runs of demo-6 (planner on ares-comp-12, executor on ares-comp-13).
Edge latency is the harness-measured RTT of the cross-host ingest POST.
Distribution is tight (stdev 1.24 ms on 7.91 ms median); the cluster network's
contribution to the inter-agent channel is stable at this sample size.
""")
    print(f"wrote {out}.pdf, {out}.png, {out}.caption.txt")


if __name__ == "__main__":
    main()
