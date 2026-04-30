#!/usr/bin/env python3
"""Fig 12 — Intra-agent fan-out: framework span-attribution integrity vs N.

Three integrity metrics expressed as % of runs that pass each check, grouped
by N. Visual answer to "does the framework capture concurrent tool_calls
without collapse / dedup / split?": all three bars reach 100 % across N levels.
"""
from __future__ import annotations
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import apply_paper_style, WONG
from _data import by_n, integrity_pcts, write_caption


METRICS = [
    ("count_correct", "len(tool_calls) = N",        WONG["blue"]),
    ("ids_unique",    "tool_use ids unique",        WONG["sky_blue"]),
    ("contained",     "single InteractionRecord",   WONG["bluish_green"]),
]


def main() -> None:
    apply_paper_style()
    grouped = by_n()
    ns = sorted(grouped.keys())                          # [1, 4, 10]
    n_runs = [len(grouped[n]) for n in ns]
    pcts = {key: [integrity_pcts(grouped[n])[key] for n in ns]
            for key, _, _ in METRICS}

    fig, ax = plt.subplots(figsize=(3.8, 2.8))
    bar_w = 0.26
    x = np.arange(len(ns), dtype=float)

    for i, (key, label, color) in enumerate(METRICS):
        ax.bar(x + (i - 1) * bar_w, pcts[key],
               width=bar_w, color=color, edgecolor="white", linewidth=0.6,
               label=label)

    # Reference line at 100% — make it visible above the bars.
    ax.axhline(100.0, color=WONG["black"], linestyle=":", linewidth=0.6,
               alpha=0.6)

    ax.set_xticks(x)
    ax.set_xticklabels([f"N={n}\n(n={k} runs)" for n, k in zip(ns, n_runs)])
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("% of runs passing")
    ax.set_title("Tool-call capture integrity under intra-agent fan-out")
    ax.yaxis.grid(True)
    ax.set_axisbelow(True)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.42),
              ncol=3, handlelength=1.4, columnspacing=1.0)

    fig.subplots_adjust(bottom=0.30)

    out = Path(__file__).resolve().parent / "fig12_intra_integrity"
    fig.savefig(out.with_suffix(".pdf"))
    fig.savefig(out.with_suffix(".png"))

    total_runs = sum(n_runs)
    write_caption(out.with_suffix(".caption.txt"), (
        f"Framework capture integrity for the same intra-agent fan-out runs as "
        f"Fig 11. Three checks per run: (1) the planner's main InteractionRecord "
        f"contains exactly N entries in `response.tool_calls`; (2) every "
        f"`tool_use.id` in that array is distinct; (3) all N tool_calls land in "
        f"a single InteractionRecord (not split across LLM turns). "
        f"All three checks pass on 100 % of runs at every N level "
        f"(total n={total_runs}). The reformulated peer-bundle hazard from the "
        f"morning's adapter bug — where N concurrent tools could in principle "
        f"merge under shared session_id — does not manifest at this level: the "
        f"framework's interaction model nests tool_calls inside a single "
        f"record, so concurrency cannot trigger session-level aggregation."
    ))


if __name__ == "__main__":
    main()
