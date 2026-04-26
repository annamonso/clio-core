#!/usr/bin/env python3
"""Fig 10 — Sweep C: cost of distribution (single-host vs two-host).

Two-panel: edge_latency_ms (left, ±stdev) and wall_time_s (right, P10–P90 range).
1h = sky blue (muted), 2h = vermillion (accent).
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import sweep_c_by_config, stats, write_caption


def _p10_p90(values: list[float]) -> tuple[float, float]:
    """Linear-interp 10th and 90th percentile. Falls back to min/max for n<=2."""
    if not values:
        return (float("nan"), float("nan"))
    s = sorted(values)
    if len(s) < 3:
        return s[0], s[-1]
    def _q(p: float) -> float:
        k = (len(s) - 1) * p
        f = int(k)
        return s[f] if f == k else s[f] + (s[f + 1] - s[f]) * (k - f)
    return _q(0.10), _q(0.90)


def main() -> None:
    apply_paper_style()
    data = sweep_c_by_config()

    cfgs = ["1h", "2h"]
    labels = ["1h (single-host)", "2h (two-host)"]
    colors = [WONG["sky_blue"], WONG["vermillion"]]

    edge_p50 = [stats(data[c]["edge"])[0] for c in cfgs]
    edge_sd  = [stats(data[c]["edge"])[1] for c in cfgs]
    wall_p50 = [stats(data[c]["wall"])[0] for c in cfgs]
    wall_p10p90 = [_p10_p90(data[c]["wall"]) for c in cfgs]
    wall_yerr_lo = [wall_p50[i] - wall_p10p90[i][0] for i in range(2)]
    wall_yerr_hi = [wall_p10p90[i][1] - wall_p50[i] for i in range(2)]

    n_per_cfg = [len(data[c]["edge"]) for c in cfgs]

    fig, (ax_l, ax_r) = plt.subplots(1, 2, figsize=(7.0, 3.2))
    x = list(range(len(cfgs)))
    bar_w = 0.55

    # --- Left: edge latency ---
    ax_l.bar(x, edge_p50, width=bar_w, color=colors,
             edgecolor="white", linewidth=0.6,
             yerr=edge_sd, capsize=4,
             error_kw=dict(elinewidth=0.9, ecolor="0.25"))
    # Per-bar label, placed above each bar's individual upper error-cap.
    for xi, v, sd in zip(x, edge_p50, edge_sd):
        ax_l.text(xi, v + sd + 0.30, f"{v:.2f} ms",
                  ha="center", va="bottom", fontsize=8)
    ax_l.set_xticks(x)
    ax_l.set_xticklabels(labels)
    ax_l.set_ylabel("Edge latency (ms)")
    ax_l.set_ylim(0, 12)
    ax_l.set_title("Edge channel")
    ax_l.yaxis.grid(True)
    ax_l.set_axisbelow(True)

    # --- Right: wall time ---
    ax_r.bar(x, wall_p50, width=bar_w, color=colors,
             edgecolor="white", linewidth=0.6,
             yerr=[wall_yerr_lo, wall_yerr_hi], capsize=4,
             error_kw=dict(elinewidth=0.9, ecolor="0.25"))
    # Per-bar label above each bar's individual P90 cap (not a shared offset).
    for xi, v, hi in zip(x, wall_p50, wall_yerr_hi):
        ax_r.text(xi, v + hi + 4.0, f"{v:.2f} s",
                  ha="center", va="bottom", fontsize=8)
    ax_r.set_xticks(x)
    ax_r.set_xticklabels(labels)
    ax_r.set_ylabel("Wall time (s)")
    ax_r.set_ylim(0, 145)
    ax_r.set_title("End-to-end wall time")
    ax_r.yaxis.grid(True)
    ax_r.set_axisbelow(True)

    # +44% wall-time delta annotation, computed from data.
    delta_pct = (wall_p50[1] - wall_p50[0]) / wall_p50[0] * 100.0

    # n annotation.
    fig.text(0.5, 0.005, f"n = {n_per_cfg[0]} per configuration  |  "
             f"edge: ±stdev   |   wall: P10 – P90 range",
             ha="center", va="bottom", fontsize=7.5, style="italic", color="0.35")

    fig.suptitle("Cost of distribution: same-host vs cross-host",
                 fontsize=11, fontweight="bold", y=0.99)
    fig.text(0.5, 0.92,
             f"Edge channel: indistinguishable.   Wall time: +{delta_pct:.0f}%.",
             ha="center", va="center", fontsize=9.5, style="italic", color="0.25")

    fig.tight_layout(rect=[0, 0.03, 1, 0.90])

    out = Path(__file__).resolve().parent / "fig10_sweep_c_distribution_cost"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))
    plt.close(fig)

    write_caption(out, """
Same demo-6 workload, planner+executor co-located vs distributed across two
compute nodes. Edge latency is statistically indistinguishable (7.87 vs 7.67 ms)
— the cluster network is not the bottleneck at this payload size. Wall time
grows by 44% in the distributed configuration; this overhead is in srun startup
and cross-node scheduling, not in the inter-agent channel itself. n=3 per
configuration.
""")
    print(f"wrote {out}.pdf, {out}.png, {out}.caption.txt")


if __name__ == "__main__":
    main()
