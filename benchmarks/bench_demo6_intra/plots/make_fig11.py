#!/usr/bin/env python3
"""Fig 11 — Intra-agent fan-out: wall time vs N (parallelism evidence).

Plots measured wall time at N ∈ {1, 4, 10} alongside the parallel-baseline
(constant + 1 s for the longest sleep) and serial-baseline (linear: + N s)
projections anchored on the N=1 median. Visual answer to "did the SDK
parallelize?": measured points sit on the parallel line, not the serial one.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import walls_by_n, median_stdev, write_caption


def main() -> None:
    apply_paper_style()
    walls = walls_by_n()
    ns = sorted(walls.keys())                      # [1, 4, 10]

    medians = [median_stdev(walls[n])[0] for n in ns]
    stdevs  = [median_stdev(walls[n])[1] for n in ns]

    n1_baseline = medians[ns.index(1)]
    # Tool sleep injected into each Bash call (seconds). Mirrors
    # intra_runner.TOOL_SLEEP_S; declared locally to keep this script
    # standalone for the figure deck.
    tool_sleep_s = 1.0
    parallel_proj = [n1_baseline + tool_sleep_s for _ in ns]                  # +1s flat
    serial_proj   = [n1_baseline + (n - 1) * tool_sleep_s for n in ns]        # +N s

    fig, ax = plt.subplots(figsize=(3.8, 2.8))

    # Reference baselines first (so measured data plots on top).
    ax.plot(ns, serial_proj, color=WONG["vermillion"], linestyle="--",
            linewidth=1.0, marker="", label=f"serial baseline (+(N−1)·{tool_sleep_s:.0f}s)")
    ax.plot(ns, parallel_proj, color=WONG["bluish_green"], linestyle="--",
            linewidth=1.0, marker="", label=f"parallel baseline (+{tool_sleep_s:.0f}s)")

    # Measured: median ± stdev error bars + scatter for individual runs.
    ax.errorbar(ns, medians, yerr=stdevs,
                fmt="o", color=WONG["blue"], ecolor=WONG["blue"],
                elinewidth=0.8, capsize=2.5, capthick=0.8,
                markersize=5, markerfacecolor=WONG["blue"],
                markeredgecolor="white", markeredgewidth=0.5,
                label="measured (median ± stdev)", zorder=3)
    # Individual runs as light dots — show n=3 spread.
    for n in ns:
        for w in walls[n]:
            ax.scatter([n], [w], color=WONG["blue"], alpha=0.25,
                       s=14, marker="o", zorder=2, edgecolors="none")

    ax.set_xticks(ns)
    ax.set_xlabel("N parallel Bash tool_calls per LLM turn")
    ax.set_ylabel("Wall time (s)")
    ax.set_title("Intra-agent fan-out: wall time scales as parallel, not serial")
    ax.set_ylim(bottom=max(0, n1_baseline - 1.5))
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", handlelength=2.0)

    out = Path(__file__).resolve().parent / "fig11_intra_walltime_vs_n"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))

    # Caption text for the deck.
    diff10 = medians[ns.index(10)] - n1_baseline
    write_caption(out.with_suffix(".caption.txt"), (
        f"Wall time of one `claude -p` planner invocation that issues N parallel "
        f"Bash tool calls per LLM turn (each call: `sleep {tool_sleep_s:.0f}; echo`). "
        f"N ∈ {{1,4,10}}, n=3 runs per level on a single ares-comp-13 host, "
        f"60 s pacing between runs. "
        f"Measured points (blue, median±stdev with individual runs) sit on the "
        f"parallel-baseline projection (green dashed: +{tool_sleep_s:.0f} s flat) "
        f"rather than the serial-baseline projection "
        f"(red dashed: +(N−1)·{tool_sleep_s:.0f} s). The N=10 measured "
        f"residual vs the N=1 baseline is {diff10:.2f} s — well below the "
        f"{(10-1)*tool_sleep_s:.0f} s a serialized dispatch would have added. "
        f"Conclusion: Claude Code's harness dispatches multiple `tool_use` blocks "
        f"in a single assistant message concurrently. The small linear-in-N "
        f"residual above the {tool_sleep_s:.0f} s parallel floor is consistent "
        f"with a fixed per-tool dispatch + result-aggregation overhead in the "
        f"harness."
    ))


if __name__ == "__main__":
    main()
