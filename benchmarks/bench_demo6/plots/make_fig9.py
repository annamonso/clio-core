#!/usr/bin/env python3
"""Fig 9 — Sweep B payload size vs edge latency.

Log-x payload size (100 B → 100 KB), linear-y edge latency. The 100 B point is
flagged separately as a Flask cold-start outlier (first batch right after a
service cycle); the trend line connects only 1 KB / 10 KB / 100 KB.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import sweep_b_by_size, sweep_a_edges, stats, write_caption


def main() -> None:
    apply_paper_style()
    by_size = sweep_b_by_size()
    sizes = sorted(by_size)

    # Decompose into outlier (100 B) and trend (1 KB, 10 KB, 100 KB).
    OUTLIER = 100
    trend_sizes = [s for s in sizes if s != OUTLIER]
    trend_p50 = [stats(by_size[s])[0] for s in trend_sizes]
    trend_sd  = [stats(by_size[s])[1] for s in trend_sizes]
    trend_n   = [len(by_size[s])      for s in trend_sizes]
    o_p50, o_sd = stats(by_size[OUTLIER]) if OUTLIER in by_size else (None, None)
    o_n         = len(by_size.get(OUTLIER, []))

    sweep_a_p50, _ = stats(sweep_a_edges())

    fig, ax = plt.subplots(figsize=(4.4, 3.0))

    # Sweep A horizontal baseline reference.
    ax.axhline(sweep_a_p50, color=WONG["black"], linestyle="--", linewidth=0.8,
               label=f"Sweep A baseline ({sweep_a_p50:.2f} ms)")

    # Trend: 1 KB → 10 KB → 100 KB with stdev error bars and connecting line.
    ax.errorbar(trend_sizes, trend_p50, yerr=trend_sd,
                fmt="o-", markersize=6, linewidth=1.0,
                color=WONG["bluish_green"],
                ecolor=WONG["bluish_green"], elinewidth=1.0, capsize=3,
                label="Sweep B (median ± stdev)")

    # Outlier: 100 B as a hollow marker, NOT connected to the trend.
    if o_p50 is not None:
        ax.errorbar([OUTLIER], [o_p50], yerr=[o_sd],
                    fmt="o", markersize=7,
                    markerfacecolor="white",
                    markeredgecolor=WONG["reddish_purple"],
                    markeredgewidth=1.4,
                    ecolor=WONG["reddish_purple"], elinewidth=1.0, capsize=3,
                    linestyle="none",
                    label="100 B (cold-start outlier *)")

    ax.set_xscale("log")
    ax.set_xlim(70, 150_000)
    ax.set_ylim(5, 13)
    ax.set_xlabel("Payload size (bytes)")
    ax.set_ylabel("Edge latency (ms)")
    ax.set_title("Edge latency vs payload size")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)

    # Per-size n annotation, compact so it doesn't crowd the legend.
    n_counts = [len(by_size[s]) for s in sizes]
    n_str = "n per cell: " + " / ".join(str(n) for n in n_counts)
    ax.text(0.02, 0.97, n_str,
            transform=ax.transAxes, ha="left", va="top", fontsize=7.5,
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor="white", edgecolor="0.7", linewidth=0.5))

    # Legend at upper-right (clear of the trend points and footnote).
    ax.legend(loc="upper right", fontsize=7.5,
              framealpha=0.95, edgecolor="0.7")

    # Footnote bottom-centre, on its own row, italic + muted.
    ax.text(0.5, 0.02,
            "* 100 B = post-cycle cold start, excluded from trend",
            transform=ax.transAxes, ha="center", va="bottom",
            fontsize=7, style="italic", color="0.35")

    out = Path(__file__).resolve().parent / "fig9_sweep_b_payload"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))
    plt.close(fig)

    write_caption(out, """
Edge latency for the cross-host ingest POST as payload size varies from 100 B to
100 KB. The 100 B point reflects Flask cold-start variance from a service cycle
immediately preceding the first batch and is marked separately. The 1 KB → 10 KB
→ 100 KB sequence shows a slight upward trend (7.46 → 7.72 → 9.56 ms median),
but stdev bands overlap heavily at this sample size — suggestive, not conclusive.
A workload exposing strong payload-size scaling would require larger payloads or
a slower channel; characterization of such a regime is future work.
""")
    print(f"wrote {out}.pdf, {out}.png, {out}.caption.txt")


if __name__ == "__main__":
    main()
