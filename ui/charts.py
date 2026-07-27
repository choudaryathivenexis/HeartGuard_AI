"""
The matplotlib layer.

Every figure in the application comes from here. Recon counted 39 call sites carrying
85 hard-coded hexes and 24 `rgba()` strings, and BUG-01/02 were exactly that: a CSS
colour string reaching `ax.barh(color=…)`, which matplotlib rejects with
`ValueError: Invalid RGBA argument`, taking down the whole Model Performance page for
every role.

So the contract of this module is narrow and absolute:

    A CSS colour string must never leave here.

`ui.tokens` already enforces the split — `T.MPL` holds 6-digit hexes only and a test
asserts it. This module consumes `T.MPL` and nothing else, and `chart_palette()` is the
only sanctioned way for a call site to obtain a colour for a chart.

WHY FIGURES ARE THEMED HERE RATHER THAN BY rcParams
    `plt.rcParams` is process-global. Streamlit reruns the script per interaction and
    two pages can render in the same process, so a page that mutated rcParams would
    leak its styling into every other page's figures in an order-dependent way. Every
    figure is themed explicitly at construction instead.

WHY THE FIGURE IS TRANSPARENT
    The page background is a theme token that changes between light and dark. Baking
    the surface colour into the PNG produces a visible rectangle whenever the two
    disagree — including at the moment a user flips the theme, before the rerun. A
    transparent figure with themed ink is correct in both.
"""
from __future__ import annotations

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

from . import tokens as T
from .styles import active_theme

__all__ = [
    "palette", "figure", "style_axes", "render", "close",
    "series_color", "risk_color", "hide_spines", "annotate_bars",
]

# matplotlib must not try to open a window; Streamlit renders the buffer.
matplotlib.use("Agg", force=False)


# ════════════════════════════════════════════════════════════════════════
# Palette
# ════════════════════════════════════════════════════════════════════════
def palette(theme: str | None = None) -> dict[str, str]:
    """
    The active chart palette, as matplotlib-safe hexes.

    Returns a flat dict rather than a theme-suffixed one so call sites read
    `p["fg"]` regardless of theme — a call site that has to know which theme it is in
    is a call site that will eventually get it wrong.
    """
    dark = (theme or active_theme()) == "dark"
    p = {k: v for k, v in T.MPL.items() if not k.endswith("_dark")}
    if dark:
        for k, v in T.MPL.items():
            if k.endswith("_dark"):
                p[k[:-5]] = v
    return p


def series_color(name: str, theme: str | None = None) -> str:
    """
    A model's colour, keyed by NAME.

    Keyed, never positional — BUG-19 was positional colour assignment silently
    re-labelling every series the moment a model was added or disabled. An unknown
    name falls back to the neutral reference colour rather than wrapping around the
    palette and colliding with a real model.
    """
    return T.SERIES.get(name, palette(theme)["reference"])


def risk_color(band_key: str, theme: str | None = None) -> str:
    """Band colour for a chart. `band_key` is one of T.RISK_ORDER."""
    return palette(theme).get(f"risk_{band_key}", palette(theme)["reference"])


# ════════════════════════════════════════════════════════════════════════
# Figure construction
# ════════════════════════════════════════════════════════════════════════
def figure(width: float = 6.0, height: float = 3.4, *, theme: str | None = None,
           dpi: int = 130, **kwargs):
    """
    A themed (fig, ax) pair.

    dpi 130 rather than the default 100: Streamlit serves the PNG at CSS pixel width,
    so a 100-dpi figure is visibly soft on any display with a device pixel ratio above
    1, which by now is most of them.
    """
    theme = theme or active_theme()
    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi, **kwargs)
    fig.patch.set_alpha(0.0)
    style_axes(ax, theme=theme)
    return fig, ax


def style_axes(ax, *, theme: str | None = None, grid: str | None = "y",
               spines: tuple[str, ...] = ("left", "bottom")):
    """
    Apply the house treatment to one axes.

    `grid` is 'x', 'y', 'both' or None. Gridlines sit BEHIND the data — matplotlib
    draws them in front by default, which puts a lattice over every bar.
    """
    p = palette(theme)
    ax.set_facecolor("none")
    for name, spine in ax.spines.items():
        if name in spines:
            spine.set_color(p["spine"])
            spine.set_linewidth(0.8)
        else:
            spine.set_visible(False)
    ax.tick_params(colors=p["axis"], labelsize=8, length=3, width=0.8)
    for lbl in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        lbl.set_color(p["fg_muted"])
    if grid:
        ax.grid(True, axis=grid, color=p["grid"], linewidth=0.7, alpha=0.9)
        ax.set_axisbelow(True)
    else:
        ax.grid(False)
    ax.xaxis.label.set_color(p["fg_muted"])
    ax.yaxis.label.set_color(p["fg_muted"])
    ax.xaxis.label.set_size(8.5)
    ax.yaxis.label.set_size(8.5)
    if ax.get_title():
        ax.title.set_color(p["fg"])
        ax.title.set_size(9.5)
        ax.title.set_fontweight("600")
    return ax


def hide_spines(ax, keep: tuple[str, ...] = ()):
    for name, spine in ax.spines.items():
        spine.set_visible(name in keep)


def annotate_bars(ax, bars, fmt="{:.1f}", *, theme: str | None = None,
                  horizontal: bool = True, pad: float = 0.01):
    """Value labels on bar ends, in the muted ink so they read as annotation."""
    p = palette(theme)
    span = (ax.get_xlim()[1] - ax.get_xlim()[0]) if horizontal else \
           (ax.get_ylim()[1] - ax.get_ylim()[0])
    for bar in bars:
        if horizontal:
            v = bar.get_width()
            ax.text(v + span * pad, bar.get_y() + bar.get_height() / 2,
                    fmt.format(v), va="center", ha="left",
                    color=p["fg_muted"], fontsize=7.5, fontweight="600")
        else:
            v = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, v + span * pad,
                    fmt.format(v), ha="center", va="bottom",
                    color=p["fg_muted"], fontsize=7.5, fontweight="600")


# ════════════════════════════════════════════════════════════════════════
# Output
# ════════════════════════════════════════════════════════════════════════
def render(fig, *, tight: bool = True, close_after: bool = True, **kwargs):
    """
    Hand a figure to Streamlit and dispose of it.

    Closing is not optional. matplotlib keeps every unclosed figure in a global
    registry; a Streamlit page reruns on every widget interaction, so a page that
    leaks one figure per rerun leaks one per keystroke and eventually exhausts memory
    with `RuntimeWarning: More than 20 figures have been opened`.
    """
    if tight:
        try:
            fig.tight_layout()
        except Exception:
            # tight_layout raises on some constrained layouts; a slightly loose
            # figure is better than a page that fails to render.
            pass
    st.pyplot(fig, transparent=True, **kwargs)
    if close_after:
        plt.close(fig)


def close(fig=None):
    plt.close(fig) if fig is not None else plt.close("all")
