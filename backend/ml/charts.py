"""
The matplotlib layer.

Every figure in the application comes from here. Phase 7 measured 38 call sites carrying
268 hard-coded hexes across 22 distinct colours — the Phase 0 recon undercounted this at
85, because it only counted lines that also named a chart function.

BUG-01/02 were exactly this failure: a CSS colour string reaching `ax.barh(color=…)`,
which matplotlib rejects with `ValueError: Invalid RGBA argument`, taking down the whole
Model Performance page for every role.

So the contract of this module is narrow and absolute:

    A CSS colour string must never leave here.

`ui.tokens` already enforces the split — `T.MPL` holds 6-digit hexes only and a test
asserts it. This module consumes `T.MPL` and nothing else, and `color()` / `palette()`
are the only sanctioned way for a call site to obtain a colour for a chart.

WHY FIGURES ARE THEMED HERE RATHER THAN BY rcParams
    `plt.rcParams` is process-global, and a web server renders figures for many
    requests in one long-lived process. A module that mutated rcParams would leak
    its styling into every later figure in an order-dependent way. Every figure is
    themed explicitly at construction instead.

WHY THE FIGURE IS TRANSPARENT
    The page background is a theme token that changes between light and dark. Baking
    the surface colour into the PNG produces a visible rectangle whenever the two
    disagree — including at the moment a user flips the theme, before the rerun. A
    transparent figure with themed ink is correct in both.
"""
from __future__ import annotations

import io
from functools import lru_cache

import matplotlib
import matplotlib.pyplot as plt

from shared import tokens as T

__all__ = [
    "palette", "color", "figure", "style_axes", "to_png", "close",
    "series_color", "risk_color", "categorical", "cmap",
    "hide_spines", "annotate_bars", "active_theme",
]

# Agg, forced. There is no display attached to a web server process, and any backend
# that tries to open a window will fail on the first request rather than at import,
# which makes it look like a chart bug instead of an environment one.
matplotlib.use("Agg", force=True)


def active_theme() -> str:
    """
    The theme charts are drawn for.

    Always 'light'. The interface is light-only, and a chart is drawn server-side with
    no access to the viewer's preference anyway — there is no per-request signal to
    follow, so pretending otherwise would just be a hook nothing can set correctly.

    Kept as a function rather than a constant so the dark palette below stays reachable
    for anything that needs it explicitly, such as a future export.
    """
    return "light"


# ════════════════════════════════════════════════════════════════════════
# Palette
# ════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=2)
def _palette(dark: bool) -> dict[str, str]:
    """
    Memoised because `color()` is called once per colour per figure, and Phase 7's
    sweep turned 268 hard-coded hexes into 268 lookups. Rebuilding a 44-entry dict
    that many times per rerun is pure waste; there are exactly two possible results.
    """
    p = {k: v for k, v in T.MPL.items() if not k.endswith("_dark")}
    if dark:
        for k, v in T.MPL.items():
            if k.endswith("_dark"):
                p[k[:-5]] = v
    return p


def palette(theme: str | None = None) -> dict[str, str]:
    """
    The active chart palette, as matplotlib-safe hexes.

    Returns a flat dict rather than a theme-suffixed one so call sites read
    `p["fg"]` regardless of theme — a call site that has to know which theme it is in
    is a call site that will eventually get it wrong.
    """
    return dict(_palette((theme or active_theme()) == "dark"))


def color(role: str) -> str:
    """
    One chart colour, by role, resolved against the viewer's theme at call time.

    This is what the 268 hard-coded hexes became. It is a function rather than a dict
    lookup on a module constant because the correct value depends on the active theme,
    which is only knowable during a script run — a module-level constant would freeze
    whichever theme happened to be active when the process started.

    An unknown role raises rather than falling back. A silent fallback here produces a
    chart that renders in the wrong colour with nothing to indicate it, which is
    exactly the failure mode the token layer exists to prevent.
    """
    p = _palette(active_theme() == "dark")
    try:
        return p[role]
    except KeyError:
        raise KeyError(
            f"unknown chart colour role {role!r}; "
            f"available: {', '.join(sorted(p))}") from None


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


def categorical(n: int | None = None) -> list[str]:
    """
    The categorical ramp, for series with no inherent order.

    §3.10 allows no hue outside the Brand Six except Iris inside a chart, which is why
    this list is six long and stops. If a caller needs more than six categories the
    chart is wrong, not the palette — so it cycles rather than inventing hues, and a
    repeat is a visible signal that the encoding has run out of room.
    """
    ramp = list(T.CHART_CATEGORICAL)
    if n is None:
        return ramp
    return [ramp[i % len(ramp)] for i in range(n)]


# ════════════════════════════════════════════════════════════════════════
# Colormaps
# ════════════════════════════════════════════════════════════════════════
# The pages arrived using matplotlib's RdYlGn, YlOrRd and RdBu_r. All three are
# off-brand — they introduce blues, yellow-greens and a pure red that appear nowhere
# else in the system — and RdYlGn in particular is the single worst choice available for
# clinical work: red-green is the most common form of colour-vision deficiency, so its
# two endpoints are indistinguishable for roughly one man in twelve. These replacements
# are built from the token ramps and separate on lightness as well as hue.
_CMAP_STOPS = {
    # Low → high magnitude. Bone through the brand crimson into Ink.
    "sequential": (T.BONE, T.CRIMSON_RAMP[300], T.CRIMSON, T.INK),
    # Low → high risk. Follows RISK order so a heatmap and a rail agree.
    "risk": (T.RISK["low"]["rail"], T.RISK["borderline"]["rail"],
             T.RISK["intermediate"]["rail"], T.RISK["high"]["rail"]),
    # Signed: negative → neutral → positive. For SHAP and for anything centred on zero.
    # The crimson tint is DERIVED, not invented — a literal here would be the first hex
    # outside tokens.py in the whole system and the token test would stop being a
    # guarantee.
    # Jade stays on the negative end. A diverging scale needs two OPPOSED hues, so it
    # cannot be built from the brand colour alone — running red-to-red through white
    # would make "strongly negative" and "strongly positive" the same colour.
    "diverging": (T.JADE, T.JADE_RAMP[200], T.BONE,
                  T.mix(T.CRIMSON, T.BONE, 0.62), T.CRIMSON),
}


@lru_cache(maxsize=8)
def cmap(kind: str = "sequential", reverse: bool = False):
    """
    A brand colormap. `kind` is 'sequential', 'risk' or 'diverging'.

    CHOOSE BY MEANING, AND MIND THE ONE LIMITATION:

      sequential   magnitude. Luminance falls monotonically 0.919 → 0.137 → 0.006, so
                   it survives greyscale printing and any colour-vision deficiency.
                   Use this for counts, importances, and every heatmap where the
                   question is "how much".
      diverging    signed quantities centred on zero. Symmetric by luminance
                   (0.139 → 0.911 → 0.137), dark at both ends, light in the middle.
      risk         the four clinical bands, and ONLY those. Measured luminance is
                   0.195 → 0.261 → 0.137 — NOT monotonic, and it cannot be made so
                   while staying inside the Brand Six, which is the same finding
                   recorded for the risk ramp in Phase 1. It is safe for band
                   identity, where hue carries a category that is also labelled in
                   text, and wrong for magnitude, where a reader would infer an
                   ordering the lightness does not support. Reach for `sequential`
                   instead whenever the quantity is continuous.

    Cached because building a LinearSegmentedColormap is not free and a page may ask
    for the same one in several figures.
    """
    from matplotlib.colors import LinearSegmentedColormap
    try:
        stops = list(_CMAP_STOPS[kind])
    except KeyError:
        raise KeyError(f"unknown colormap {kind!r}; "
                       f"available: {', '.join(sorted(_CMAP_STOPS))}") from None
    if reverse:
        stops.reverse()
    return LinearSegmentedColormap.from_list(f"hg_{kind}{'_r' if reverse else ''}",
                                             stops, N=256)


# ════════════════════════════════════════════════════════════════════════
# Figure construction
# ════════════════════════════════════════════════════════════════════════
def figure(width: float = 6.0, height: float = 3.4, *, theme: str | None = None,
           dpi: int = 130, **kwargs):
    """
    A themed (fig, ax) pair.

    dpi 130 rather than the default 100: the PNG is served at CSS pixel width, so a
    100-dpi figure is visibly soft on any display with a device pixel ratio above 1,
    which by now is most of them.
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


def on_color(background) -> str:
    """
    Readable ink for text sitting ON a filled cell.

    Chosen by the background's measured luminance, never by the underlying value.
    The heatmaps arrived doing the latter — `'black' if value > 0.12` — which only
    worked because RdYlGn happens to be light at its high end. Swapping in a ramp
    that is DARK at its high end silently made the largest cell in every confusion
    matrix dark-on-dark. Deciding from the colour cannot break that way.

    Accepts a hex string or an RGB(A) tuple, which is what a matplotlib colormap
    returns.

    MEASURES BOTH CANDIDATES rather than testing luminance against a threshold. The
    first version used `luminance > 0.45`, which is badly wrong: Ink and Bone cross over
    at luminance ≈ 0.18, so every cell between 0.18 and 0.45 was given the WORSE of the
    two options. Measured worst-case contrast across the three ramps was 2.00-2.85,
    under the 3:1 floor, when picking correctly never drops below ~4.1. Comparing the
    two ratios cannot be off by a mistuned constant.
    """
    if not isinstance(background, str):
        r, g, b = (int(round(255 * c)) for c in tuple(background)[:3])
        background = f"#{r:02X}{g:02X}{b:02X}"
    return max((T.INK, T.BONE), key=lambda ink: T.contrast_ratio(ink, background))


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
def to_png(fig, *, tight: bool = True, close_after: bool = True, dpi: int = 150) -> bytes:
    """
    Render a figure to PNG bytes and dispose of it.

    This replaces the old `render()`, which handed the figure to `st.pyplot`. The web
    layer serves charts as images from a route, so the figure has to become bytes here
    rather than being pushed at a framework.

    CLOSING IS NOT OPTIONAL. matplotlib keeps every unclosed figure in a global
    registry, and a long-lived Flask process serving one chart per request leaks one
    figure per request until it exhausts memory with `RuntimeWarning: More than 20
    figures have been opened` - and a server process never restarts to clear them.
    """
    if tight:
        try:
            fig.tight_layout()
        except Exception:
            # tight_layout raises on some constrained layouts; a slightly loose
            # figure is better than a page that fails to render.
            pass
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, transparent=True,
                bbox_inches="tight", pad_inches=0.08)
    if close_after:
        plt.close(fig)
    return buf.getvalue()


def close(fig=None):
    plt.close(fig) if fig is not None else plt.close("all")
