"""
HeartGuard AI — Icon set
========================
Hand-built inline SVG. No icon library, because that would be a new dependency and
§1.3 forbids `requirements.txt` growing.

--------------------------------------------------------------------------
WHY ICONS ARE STRUCTURED PRIMITIVES RATHER THAN SVG PATH STRINGS
--------------------------------------------------------------------------
Each icon is a list of geometric primitives, not a `d="M3 4L7 8..."` string. Two
renderers consume that list:

    to_svg(name)        -> inline SVG for the app
    draw_mpl(ax, name)  -> matplotlib, for verification and the PDF report

This exists for a concrete reason: there is no SVG rasteriser available in this
environment, so a set defined as opaque path strings could not be *seen* before
shipping. "Optical weight consistent across the set" is a visual property, and a
claim about a visual property that nobody has looked at is worthless. Structured
primitives can be rendered through matplotlib into a contact sheet and inspected.

It also means the same geometry can appear in the PDF report, where SVG cannot go.

--------------------------------------------------------------------------
SPECIFICATION
--------------------------------------------------------------------------
viewBox 0 0 20 20 · stroke 1.5 · round caps and joins · fill none · currentColor.
Geometry on a 2px grid, content inset ~3px so every icon has the same optical size.

The stroke language matches the Caliper Mark: the mark is 2.5 at 32px, which is 1.56
at 20px, so 1.5 reads as the same hand.
"""

from __future__ import annotations

VIEW = 20
STROKE = 1.5

# ── primitives ───────────────────────────────────────────────────────────
#   ("line",   x1, y1, x2, y2)
#   ("poly",   [(x, y), ...], closed)
#   ("circle", cx, cy, r)
#   ("rect",   x, y, w, h, rx)
#   ("arc",    cx, cy, r, start_deg, end_deg)      SCREEN space, see note below
#   ("ellipse",cx, cy, rx, ry)                     a cylinder lid needs a FLAT oval,
#   ("earc",   cx, cy, rx, ry, a0, a1)             which a circular arc cannot express
#   ("dot",    cx, cy, r)                          filled

ICONS: dict[str, list[tuple]] = {
    # ── navigation ──────────────────────────────────────────────────────
    "dashboard": [
        ("rect", 3, 3, 6, 6, 1), ("rect", 11, 3, 6, 6, 1),
        ("rect", 3, 11, 6, 6, 1), ("rect", 11, 11, 6, 6, 1),
    ],
    # A gauge with its needle at the golden section — the same "reading" idea as the
    # Caliper Mark, so the primary clinical action carries the brand concept.
    "prediction": [
        ("arc", 10, 13, 6.5, 190, 350),
        ("line", 10, 13, 13.6, 8.6),
        ("dot", 10, 13, 1.15),
    ],
    "patients": [
        ("circle", 7, 7, 2.6),
        ("arc", 7, 17.2, 4.8, 202, 338),
        ("circle", 14.2, 8, 2.0),
        ("arc", 14.6, 17.2, 3.8, 214, 326),
    ],
    "history": [
        ("circle", 10, 10, 7),
        ("line", 10, 6, 10, 10), ("line", 10, 10, 13, 11.5),
    ],
    "performance": [
        ("line", 3, 17, 17, 17),
        ("line", 6, 17, 6, 11), ("line", 10, 17, 10, 7), ("line", 14, 17, 14, 4),
    ],
    "training": [
        ("line", 7, 2.6, 13, 2.6),
        ("poly", [(8.4, 2.6), (8.4, 8), (4.4, 15.2)], False),
        ("poly", [(11.6, 2.6), (11.6, 8), (15.6, 15.2)], False),
        ("earc", 10, 15.2, 5.6, 2.2, 0, 180),
        ("line", 6.2, 11.6, 13.8, 11.6),
    ],
    "reports": [
        ("poly", [(5, 2.5), (12, 2.5), (15, 5.5), (15, 17.5), (5, 17.5)], True),
        ("poly", [(12, 2.5), (12, 5.5), (15, 5.5)], False),
        ("line", 7.5, 10, 12.5, 10), ("line", 7.5, 13, 12.5, 13),
    ],
    "profile": [
        ("circle", 10, 7, 3),
        ("arc", 10, 17.5, 5.8, 203, 337),
    ],
    "doctors": [
        ("circle", 8.2, 6.8, 2.7),
        ("arc", 8.2, 17.4, 5.2, 205, 335),
        ("line", 15.2, 6.8, 15.2, 10.0), ("line", 13.6, 8.4, 16.8, 8.4),
    ],
    "admin": [
        ("circle", 6.2, 10, 3.2),
        ("dot", 6.2, 10, 0.9),
        ("line", 9.4, 10, 17, 10),
        ("line", 13, 10, 13, 13.2),
        ("line", 15.8, 10, 15.8, 12.4),
    ],
    "roles": [
        ("rect", 2.5, 5, 15, 11, 1.5),
        ("line", 2.5, 9, 17.5, 9),
        ("line", 6, 12.5, 10, 12.5),
    ],
    "settings": [
        ("line", 3, 6, 17, 6), ("dot", 8, 6, 1.7),
        ("line", 3, 10, 17, 10), ("dot", 13, 10, 1.7),
        ("line", 3, 14, 17, 14), ("dot", 6.5, 14, 1.7),
    ],
    "analytics": [
        ("line", 3, 3, 3, 17), ("line", 3, 17, 17, 17),
        ("poly", [(5.5, 13.5), (9, 9.5), (12, 12), (16.5, 5.5)], False),
    ],
    "logs": [
        ("dot", 4.5, 5.5, 1), ("line", 8, 5.5, 16.5, 5.5),
        ("dot", 4.5, 10, 1), ("line", 8, 10, 16.5, 10),
        ("dot", 4.5, 14.5, 1), ("line", 8, 14.5, 16.5, 14.5),
    ],
    "backup": [
        ("rect", 3, 4, 14, 5, 1),
        ("poly", [(4.5, 9), (4.5, 16.5), (15.5, 16.5), (15.5, 9)], False),
        ("line", 8, 12.5, 12, 12.5),
    ],
    # A cylinder needs a FLAT oval lid; a circular arc of the required width is
    # 6.4 units tall and rendered as a stack of lenses. Hence the ellipse primitive.
    "dataset": [
        ("ellipse", 10, 5.6, 6.4, 2.4),        # lid
        ("line", 3.6, 5.6, 3.6, 14.4),         # left wall
        ("line", 16.4, 5.6, 16.4, 14.4),       # right wall
        ("earc", 10, 14.4, 6.4, 2.4, 0, 180),  # base
        ("earc", 10, 10.0, 6.4, 2.4, 0, 180),  # mid seam
    ],
    "signout": [
        ("poly", [(11, 3.5), (4.5, 3.5), (4.5, 16.5), (11, 16.5)], False),
        ("line", 8.5, 10, 17, 10),
        ("poly", [(14, 7), (17, 10), (14, 13)], False),
    ],

    # ── controls ────────────────────────────────────────────────────────
    "search": [
        ("circle", 8.75, 8.75, 5.25),
        ("line", 12.75, 12.75, 17, 17),
    ],
    "filter": [
        ("poly", [(3, 4.5), (17, 4.5), (11.5, 11), (11.5, 16.5), (8.5, 15), (8.5, 11)],
         True),
    ],
    "download": [
        ("line", 10, 3, 10, 12),
        ("poly", [(6.5, 8.5), (10, 12), (13.5, 8.5)], False),
        ("poly", [(3.5, 14), (3.5, 17), (16.5, 17), (16.5, 14)], False),
    ],
    "plus": [
        ("line", 10, 4, 10, 16), ("line", 4, 10, 16, 10),
    ],
    "trash": [
        ("line", 3.5, 6, 16.5, 6),
        ("poly", [(8, 6), (8, 3.5), (12, 3.5), (12, 6)], False),
        ("poly", [(5.5, 6), (6.5, 17), (13.5, 17), (14.5, 6)], False),
        ("line", 8.5, 9, 8.5, 14), ("line", 11.5, 9, 11.5, 14),
    ],
    "edit": [
        ("poly", [(3, 17), (3, 13.5), (13.5, 3), (17, 6.5), (6.5, 17)], True),
        ("line", 11.5, 5, 15, 8.5),
    ],
    "external": [
        ("poly", [(11, 3.5), (16.5, 3.5), (16.5, 9)], False),
        ("line", 16.5, 3.5, 9.5, 10.5),
        ("poly", [(13.5, 12), (13.5, 16.5), (3.5, 16.5), (3.5, 6.5), (8, 6.5)], False),
    ],
    "chevron-right": [
        ("poly", [(8, 5), (13, 10), (8, 15)], False),
    ],
    "chevron-down": [
        ("poly", [(5, 8), (10, 13), (15, 8)], False),
    ],

    # ── status ──────────────────────────────────────────────────────────
    "warning": [
        ("poly", [(10, 3), (17.5, 16.5), (2.5, 16.5)], True),
        ("line", 10, 8, 10, 12), ("dot", 10, 14.3, 0.85),
    ],
    "check": [
        ("poly", [(4, 10.5), (8, 14.5), (16, 6)], False),
    ],
    "info": [
        ("circle", 10, 10, 7),
        ("line", 10, 9.5, 10, 14), ("dot", 10, 6.6, 0.85),
    ],
}

# Navigation label -> icon name. Kept here so the sidebar has one lookup and cannot
# drift from the icon set.
NAV_ICON = {
    "Dashboard": "dashboard",
    "Heart Disease Prediction": "prediction",
    "Patient Management": "patients",
    "Prediction History": "history",
    "Model Performance": "performance",
    "ML Model Management": "training",
    "Reports": "reports",
    "Profile": "profile",
    "Doctor Management": "doctors",
    "Admin Management": "admin",
    "Prediction Management": "logs",
    "Role & Permission Management": "roles",
    "System Settings": "settings",
    "Analytics": "analytics",
    "Activity Logs": "logs",
    "Backup & Restore": "backup",
    "Dataset Management": "dataset",
}


# ════════════════════════════════════════════════════════════════════════
# SVG renderer
# ════════════════════════════════════════════════════════════════════════
def _svg_shape(shape: tuple) -> str:
    kind = shape[0]
    if kind == "line":
        _, x1, y1, x2, y2 = shape
        return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
    if kind == "poly":
        _, pts, closed = shape
        d = "M" + " L".join(f"{x} {y}" for x, y in pts) + (" Z" if closed else "")
        return f'<path d="{d}"/>'
    if kind == "circle":
        _, cx, cy, r = shape
        return f'<circle cx="{cx}" cy="{cy}" r="{r}"/>'
    if kind == "rect":
        _, x, y, w, h, rx = shape
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>'
    if kind == "arc":
        _, cx, cy, r, a0, a1 = shape
        return _svg_arc(cx, cy, r, a0, a1)
    if kind == "ellipse":
        _, cx, cy, rx, ry = shape
        return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"/>'
    if kind == "earc":
        _, cx, cy, rx, ry, a0, a1 = shape
        return _svg_earc(cx, cy, rx, ry, a0, a1)
    if kind == "dot":
        _, cx, cy, r = shape
        return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="currentColor" stroke="none"/>'
    raise ValueError(f"unknown primitive {kind!r}")


def _arc_point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    """
    Arc parametrisation in SCREEN space: y grows DOWNWARD, angles increase clockwise.

        point(t) = (cx + r*cos t,  cy + r*sin t)

    THIS CONVENTION IS LOAD-BEARING. The first version used SVG's `cy - r*sin` here
    while matplotlib (with an inverted y-axis) effectively applies `cy + r*sin`, so the
    two renderers drew every arc MIRRORED. The verification contact sheet therefore did
    not show what the app would render: shoulder arcs curved into smiles and the gauge
    became a bowl. Both renderers now derive from this one formula.

    Useful ranges, in this convention:
        180 -> 360   upper half   (an arch: shoulders, a gauge opening downward)
          0 -> 180   lower half   (a cup)
    """
    import math
    t = math.radians(deg)
    return cx + r * math.cos(t), cy + r * math.sin(t)


def _svg_arc(cx: float, cy: float, r: float, a0: float, a1: float) -> str:
    """Arc as an SVG path, using the screen-space convention in `_arc_point`."""
    if abs(a1 - a0) >= 360:
        return f'<circle cx="{cx}" cy="{cy}" r="{r}"/>'
    x0, y0 = _arc_point(cx, cy, r, a0)
    x1, y1 = _arc_point(cx, cy, r, a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    # sweep=1 matches increasing angle in screen space
    return (f'<path d="M{x0:.2f} {y0:.2f} '
            f'A{r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}"/>')


def _svg_earc(cx: float, cy: float, rx: float, ry: float,
              a0: float, a1: float) -> str:
    """Elliptical arc, same screen-space convention as `_arc_point`."""
    import math
    x0 = cx + rx * math.cos(math.radians(a0))
    y0 = cy + ry * math.sin(math.radians(a0))
    x1 = cx + rx * math.cos(math.radians(a1))
    y1 = cy + ry * math.sin(math.radians(a1))
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return (f'<path d="M{x0:.2f} {y0:.2f} '
            f'A{rx} {ry} 0 {large} 1 {x1:.2f} {y1:.2f}"/>')


def to_svg(name: str, size: int = 20, stroke: float = STROKE,
           label: str | None = None) -> str:
    """
    Inline SVG for an icon.

    Icons inherit `currentColor`, so they take the colour of their context — muted in
    navigation at rest, the accent colour inside a coloured component.

    `label` sets aria-label for an icon-only control; without it the icon is marked
    decorative so a screen reader skips it rather than announcing "image".
    """
    if name not in ICONS:
        raise KeyError(f"unknown icon {name!r}")
    body = "".join(_svg_shape(s) for s in ICONS[name])
    a11y = (f'role="img" aria-label="{label}"' if label
            else 'aria-hidden="true" focusable="false"')
    return (
        f'<svg viewBox="0 0 {VIEW} {VIEW}" width="{size}" height="{size}" {a11y} '
        f'fill="none" stroke="currentColor" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="display:block;flex:0 0 auto;">{body}</svg>'
    )


# ════════════════════════════════════════════════════════════════════════
# matplotlib renderer — verification, and the PDF report
# ════════════════════════════════════════════════════════════════════════
def draw_mpl(ax, name: str, color: str = "#0E131A", lw: float = STROKE) -> None:
    """Draw an icon into a matplotlib axes with y inverted to match SVG coordinates."""
    from matplotlib.patches import Arc, Circle, FancyBboxPatch

    for shape in ICONS[name]:
        kind = shape[0]
        if kind == "line":
            _, x1, y1, x2, y2 = shape
            ax.plot([x1, x2], [y1, y2], color=color, lw=lw,
                    solid_capstyle="round", solid_joinstyle="round")
        elif kind == "poly":
            _, pts, closed = shape
            xs = [p[0] for p in pts] + ([pts[0][0]] if closed else [])
            ys = [p[1] for p in pts] + ([pts[0][1]] if closed else [])
            ax.plot(xs, ys, color=color, lw=lw,
                    solid_capstyle="round", solid_joinstyle="round")
        elif kind == "circle":
            _, cx, cy, r = shape
            ax.add_patch(Circle((cx, cy), r, fill=False, ec=color, lw=lw))
        elif kind == "rect":
            _, x, y, w, h, rx = shape
            ax.add_patch(FancyBboxPatch(
                (x + rx, y + rx), w - 2 * rx, h - 2 * rx,
                boxstyle=f"round,pad={rx}", fill=False, ec=color, lw=lw))
        elif kind == "arc":
            _, cx, cy, r, a0, a1 = shape
            ax.add_patch(Arc((cx, cy), 2 * r, 2 * r, angle=0,
                             theta1=a0, theta2=a1, ec=color, lw=lw))
        elif kind == "ellipse":
            _, cx, cy, rx, ry = shape
            ax.add_patch(Arc((cx, cy), 2 * rx, 2 * ry, angle=0,
                             theta1=0, theta2=360, ec=color, lw=lw))
        elif kind == "earc":
            _, cx, cy, rx, ry, a0, a1 = shape
            ax.add_patch(Arc((cx, cy), 2 * rx, 2 * ry, angle=0,
                             theta1=a0, theta2=a1, ec=color, lw=lw))
        elif kind == "dot":
            _, cx, cy, r = shape
            ax.add_patch(Circle((cx, cy), r, fill=True, fc=color, ec="none"))
    ax.set_xlim(0, VIEW)
    ax.set_ylim(VIEW, 0)          # inverted: SVG y grows downward
    ax.set_aspect("equal")
    ax.axis("off")


def slug(label: str) -> str:
    """Stable CSS-safe slug for a page label. Used for container keys and selectors."""
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def to_data_uri(name: str, stroke: float = STROKE) -> str:
    """
    URL-encoded SVG for use as a CSS `mask-image`.

    WHY A MASK RATHER THAN A BACKGROUND IMAGE
    -----------------------------------------
    Some contexts take a plain-text label only - inline SVG is escaped there, so an
    icon cannot be placed inside `st.button`. The icon is therefore attached via CSS
    `::before` on the button.

    A `background-image` data URI would need its colour baked in, which breaks theming:
    two copies of every icon, switched by `[data-theme]`. Used as a `mask-image` the SVG
    contributes only its alpha channel and the visible colour comes from
    `background: currentColor` — so one data URI serves both themes and inherits the
    text colour automatically, including the active-item accent.

    The stroke is set to a literal colour because mask compositing ignores it; only
    coverage matters.
    """
    body = "".join(_svg_shape(s) for s in ICONS[name])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}" '
           f'fill="none" stroke="%23000" stroke-width="{stroke}" '
           f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    # Minimal percent-encoding — enough for a CSS url() without needing quoting rules.
    svg = (svg.replace("%23000", "\x00")          # protect the already-encoded hash
              .replace("#", "%23")
              .replace("\x00", "%23000")
              .replace('"', "'")
              .replace("<", "%3C").replace(">", "%3E")
              .replace("\n", "").replace("\r", ""))
    return f"url(\"data:image/svg+xml,{svg}\")"


def contact_sheet(path: str = "icons-contact-sheet.png", cols: int = 7,
                  cell_px: int = 84) -> str:
    """
    Render every icon to one image so the set can actually be looked at.

    "Optical weight consistent across the set" is a visual property; this is how it
    gets checked rather than asserted.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = sorted(ICONS)
    rows = (len(names) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols,
                             figsize=(cols * cell_px / 100, rows * cell_px / 100),
                             dpi=100, facecolor="#FFFFFF")
    axes = axes.ravel() if rows * cols > 1 else [axes]
    for ax, name in zip(axes, names):
        draw_mpl(ax, name)
        ax.set_title(name, fontsize=6, color="#566171", pad=2)
    for ax in axes[len(names):]:
        ax.axis("off")
    fig.tight_layout(pad=0.4)
    fig.savefig(path, facecolor="#FFFFFF", bbox_inches="tight")
    plt.close(fig)
    return path


__all__ = ["ICONS", "NAV_ICON", "to_svg", "to_data_uri", "draw_mpl",
           "contact_sheet", "slug", "VIEW", "STROKE"]
