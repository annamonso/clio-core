"""Shared rcParams + Wong palette for the demo-6 figure deck.

Generic paper-style defaults (no LaTeX dependency); colors from Wong 2011's
8-colour colour-blind-safe palette. Used by make_fig8/9/10.py.
"""
from __future__ import annotations
import matplotlib as mpl


# Wong's 8-colour palette — https://www.nature.com/articles/nmeth.1618
WONG = {
    "black":          "#000000",
    "orange":         "#E69F00",
    "sky_blue":       "#56B4E9",
    "bluish_green":   "#009E73",
    "yellow":         "#F0E442",
    "blue":           "#0072B2",
    "vermillion":     "#D55E00",
    "reddish_purple": "#CC79A7",
}


def apply_paper_style() -> None:
    """Set matplotlib rcParams for the paper-deck style. Call once at script top."""
    mpl.rcParams.update({
        "font.family":          "serif",
        "font.serif":           ["DejaVu Serif"],
        "font.size":            9,
        "axes.titlesize":       10,
        "axes.titleweight":     "bold",
        "axes.labelsize":       9,
        "xtick.labelsize":      8,
        "ytick.labelsize":      8,
        "legend.fontsize":      8,
        "legend.frameon":       False,
        "axes.linewidth":       0.6,
        "axes.spines.top":      False,
        "axes.spines.right":    False,
        "xtick.major.width":    0.6,
        "ytick.major.width":    0.6,
        "xtick.minor.width":    0.4,
        "ytick.minor.width":    0.4,
        "grid.linewidth":       0.4,
        "grid.alpha":           0.4,
        "grid.linestyle":       ":",
        "figure.dpi":           100,    # display dpi
        "savefig.dpi":          300,    # output dpi
        "savefig.bbox":         "tight",
        "savefig.pad_inches":   0.05,
        "pdf.fonttype":         42,     # embed TrueType (avoids Type 3 issues)
        "ps.fonttype":          42,
    })
