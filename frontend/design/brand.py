"""
HeartGuard AI — The Caliper Mark
================================
The mark is the Reference Rail compressed into a monogram: two caliper jaws measuring
a span, with the crossbar reading as the **H** of HeartGuard.

Calipers are the archetypal precision instrument, and the gap they measure is exactly
what a confidence interval is. The logo and the signature UI element are therefore the
same idea at two scales — that recursion is what makes a brand system feel designed
rather than assembled.

NOT a heart. NOT a pulse line. NOT a shield. Those are the three defaults for anything
named "HeartGuard" and all three are clichés.

--------------------------------------------------------------------------
GEOMETRY (viewBox 0 0 32 32, stroke 2.5, square caps, miter joins)
--------------------------------------------------------------------------
        ▼                     notch — the reading, at the golden section
   ┌────┴──────────────┐
   █━━━━━━━━━━━━━┅┅┅┅┅┅█      left jaw · rail · right jaw
   └───────────────────┘      rail solid to the notch, hairline after

    left jaw    vertical   x=6    y=6 -> 26
    right jaw   vertical   x=26   y=6 -> 26
    rail        horizontal y=16   x=6 -> 26      (the H crossbar)
    fill break  x=18.4                            (61.8%, the golden section)
    notch       4x3 triangle above the rail, apex down, at x=18.4

--------------------------------------------------------------------------
SCALE BEHAVIOUR — two marks, not one scaled mark
--------------------------------------------------------------------------
`mark()`    >= 32px. Notch and fill break resolve; it reads as a measurement.
`mark_sm()` 16-20px. Notch and fill break are DROPPED; it reads as a clean,
            slightly technical H.

A mark that changes what it tells you at different sizes is doing real work. At 16px a
3px triangle and a 1px stroke-width change are sub-pixel mush, so they are removed
rather than rendered as noise.

Everything inherits `currentColor`, so the mark themes automatically and costs no
network request.
"""

from __future__ import annotations

import os

from shared import tokens as T

# Project root from backend.config, not from this file's depth in the tree — the
# old two-level dirname() was only correct while this module lived in ui/.
from backend.config import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT
BRAND_DIR = os.path.join(BASE_DIR, "assets", "brand")

# ── Geometry constants — single source, used by SVG and the Pillow favicon ──
VIEW = 32
JAW_L_X = 6.0
JAW_R_X = 26.0
JAW_TOP = 6.0
JAW_BOT = 26.0
RAIL_Y = 16.0
STROKE = 2.5
GOLDEN = JAW_L_X + (JAW_R_X - JAW_L_X) * 0.618   # 18.36 — the fill break
HAIRLINE = 1.0
# Notch proportions were chosen by rendering four variants at 16/20/32/64px and
# comparing them (baseline/mark_variants.png), not by picking numbers off the brief:
#   gap 0.6 fused the triangle to the rail and read as a funnel, losing the "marker
#   above the track" semantics entirely; a dashed remainder read as debris at 64px and
#   as damage at 32px. A wider gap with a narrower, taller triangle reads as a
#   downward pointer at every size that renders it.
NOTCH_W = 3.4
NOTCH_H = 3.6
NOTCH_GAP = 1.8      # clearance between notch apex and the rail's top edge

MIN_MARK_PX = 20
MIN_LOCKUP_PX = 96


def _notch_points() -> str:
    """4x3 triangle above the rail, apex down, centred on the golden section."""
    apex_y = RAIL_Y - STROKE / 2 - NOTCH_GAP
    base_y = apex_y - NOTCH_H
    return (f"{GOLDEN:.2f},{apex_y:.2f} "
            f"{GOLDEN - NOTCH_W / 2:.2f},{base_y:.2f} "
            f"{GOLDEN + NOTCH_W / 2:.2f},{base_y:.2f}")


# ════════════════════════════════════════════════════════════════════════
# The mark
# ════════════════════════════════════════════════════════════════════════
def mark(size: int = 32, color: str | None = None, title: str = "HeartGuard AI") -> str:
    """
    Full Caliper Mark. Use at 32px and above.

    `color=None` inherits currentColor, which is what makes it theme automatically.
    """
    c = color or "currentColor"
    return (
        f'<svg viewBox="0 0 {VIEW} {VIEW}" width="{size}" height="{size}" '
        f'role="img" aria-label="{title}" fill="none" '
        f'style="display:block;overflow:visible;">'
        f'<title>{title}</title>'
        f'<g stroke="{c}" stroke-linecap="square" stroke-linejoin="miter">'
        # jaws
        f'<path d="M{JAW_L_X} {JAW_TOP}V{JAW_BOT}" stroke-width="{STROKE}"/>'
        f'<path d="M{JAW_R_X} {JAW_TOP}V{JAW_BOT}" stroke-width="{STROKE}"/>'
        # rail: solid to the golden section, hairline thereafter
        f'<path d="M{JAW_L_X} {RAIL_Y}H{GOLDEN:.2f}" stroke-width="{STROKE}"/>'
        f'<path d="M{GOLDEN:.2f} {RAIL_Y}H{JAW_R_X}" stroke-width="{HAIRLINE}"/>'
        f'</g>'
        # the reading
        f'<polygon points="{_notch_points()}" fill="{c}"/>'
        f'</svg>'
    )


def mark_sm(size: int = 20, color: str | None = None,
            title: str = "HeartGuard AI") -> str:
    """
    Reduced mark for 16-20px. Notch and fill break dropped — reads as a technical H.

    Deliberately a separate construction rather than a scaled `mark()`: at 16px the
    3px notch and the 1px hairline are sub-pixel and render as dirt.
    """
    c = color or "currentColor"
    return (
        f'<svg viewBox="0 0 {VIEW} {VIEW}" width="{size}" height="{size}" '
        f'role="img" aria-label="{title}" fill="none" '
        f'style="display:block;">'
        f'<title>{title}</title>'
        f'<g stroke="{c}" stroke-width="{STROKE + 0.5}" '
        f'stroke-linecap="square" stroke-linejoin="miter">'
        f'<path d="M{JAW_L_X} {JAW_TOP}V{JAW_BOT}"/>'
        f'<path d="M{JAW_R_X} {JAW_TOP}V{JAW_BOT}"/>'
        f'<path d="M{JAW_L_X} {RAIL_Y}H{JAW_R_X}"/>'
        f'</g></svg>'
    )


# ════════════════════════════════════════════════════════════════════════
# Wordmark & lockups
# ════════════════════════════════════════════════════════════════════════
# The wordmark is HTML rather than SVG <text> on purpose: SVG text cannot use the
# variable-font width axis reliably across browsers, and HTML inherits the @import'ed
# Archivo face with `font-variation-settings` support everywhere we care about.
def wordmark(size: int = 18, dark: bool | None = False) -> str:
    """
    `HeartGuard` in Archivo 600 expanded, then `AI` in crimson behind a rule.

    `dark` takes three values, and the third is the one to use in the application:

        False  bake the LIGHT hexes    — for print, PDF and one-off exports
        True   bake the DARK hexes     — same, on a known-dark surface
        None   emit `var(--hg-*)`      — follow whatever theme is live

    THE SIDEBAR LOGO WAS INVISIBLE BECAUSE OF THIS DEFAULT.
    ui.components.sidebar_nav called `lockup()` without an argument, so it baked
    `text_heading` (#1A2029, near-black) into an inline style. On a dark sidebar that
    is near-black text on a near-black surface — the wordmark vanished while the `AI`
    stayed legible, because the accent is crimson and crimson survives both surfaces.
    A baked hex cannot respond to a theme change; the CSS variable can, and the
    stylesheet already flips those variables per theme. So in-app callers pass None.
    """
    if dark is None:
        ink = "var(--hg-text-heading)"
        accent = "var(--hg-primary)"
    else:
        ink = T.CSS_DARK["text_heading"] if dark else T.CSS["text_heading"]
        accent = T.CSS_DARK["primary"] if dark else T.CSS["primary"]
    ai = round(size * 0.72, 2)
    return (
        f'<span style="display:inline-flex;align-items:center;gap:0;'
        f'font-family:{T.FONT_DISPLAY};line-height:1;white-space:nowrap;">'
        f'<span style="font-size:{size}px;font-weight:{T.WEIGHT["semibold"]};'
        f'font-variation-settings:\'wdth\' 112;letter-spacing:-0.01em;'
        f'color:{ink};">HeartGuard</span>'
        f'<span style="width:1px;height:{round(size * 0.78, 1)}px;'
        f'background:{accent};margin:0 8px;display:inline-block;"></span>'
        f'<span style="font-size:{ai}px;font-weight:{T.WEIGHT["regular"]};'
        f'font-variation-settings:\'wdth\' 112;color:{accent};">AI</span>'
        f'</span>'
    )


def lockup(size: int = 26, dark: bool | None = False, wordmark_size: int = 18) -> str:
    """
    Mark + 12px gap + wordmark, optically centred on the rail rather than the box.

    The mark's visual centre is the crossbar at y=16 of 32, i.e. exactly mid-height,
    so `align-items:center` is correct here — but the gap is measured from the jaw, not
    the SVG bounding box, which is why overflow is visible on the mark.

    `dark=None` makes the whole lockup theme-following; see `wordmark`. The caliper
    mark itself already inherits `currentColor`, so setting the colour on this wrapper
    is what drives it — which is why the wrapper colour has to be a variable too, not
    just the wordmark's.
    """
    if dark is None:
        colour = "var(--hg-text-heading)"
    else:
        colour = T.CSS_DARK["text_heading"] if dark else T.CSS["text_heading"]
    return (
        f'<span style="display:inline-flex;align-items:center;gap:12px;'
        f'color:{colour};">'
        f'{mark(size)}{wordmark(wordmark_size, dark)}'
        f'</span>'
    )


def lockup_mono(color: str, size: int = 26, wordmark_size: int = 18) -> str:
    """
    Single-colour lockup for print, PDF headers and one-colour reproduction.

    Both mark and wordmark take the given colour; the Verdigris rule and `AI` accent
    collapse into it, which is the correct behaviour for one-ink output.
    """
    ai = round(wordmark_size * 0.72, 2)
    return (
        f'<span style="display:inline-flex;align-items:center;gap:12px;color:{color};">'
        f'{mark(size, color=color)}'
        f'<span style="display:inline-flex;align-items:center;'
        f'font-family:{T.FONT_DISPLAY};line-height:1;white-space:nowrap;">'
        f'<span style="font-size:{wordmark_size}px;font-weight:{T.WEIGHT["semibold"]};'
        f'font-variation-settings:\'wdth\' 112;letter-spacing:-0.01em;">HeartGuard</span>'
        f'<span style="width:1px;height:{round(wordmark_size * 0.78, 1)}px;'
        f'background:{color};margin:0 8px;display:inline-block;opacity:.7;"></span>'
        f'<span style="font-size:{ai}px;font-weight:{T.WEIGHT["regular"]};'
        f'font-variation-settings:\'wdth\' 112;opacity:.8;">AI</span>'
        f'</span></span>'
    )


def mark_watermark(size: int = 160, opacity: float = 0.15, dark: bool = False) -> str:
    """
    The mark at low opacity for empty states.

    §3.9 forbids photography in empty states — this is the sanctioned alternative.
    """
    c = T.CSS_DARK["text_subtle"] if dark else T.CSS["text_subtle"]
    return (f'<div style="color:{c};opacity:{opacity};display:flex;'
            f'justify-content:center;padding:var(--hg-space-6) 0;">'
            f'{mark(size)}</div>')


# ════════════════════════════════════════════════════════════════════════
# Favicon — Pillow, because st.set_page_config(page_icon=...) needs a file
# ════════════════════════════════════════════════════════════════════════
def _draw_favicon(px: int, fg: str, bg: str):
    """
    Render the mark to a PIL image. Geometry scaled from the same constants as the SVG,
    so the favicon can never drift from the mark.

    Pillow is already installed as a matplotlib dependency, so this adds nothing to
    requirements.txt — the same reasoning that kept reportlab out of the project.
    """
    from PIL import Image, ImageDraw

    s = px / VIEW                      # scale factor, 32 -> px
    img = Image.new("RGBA", (px, px), bg)
    d = ImageDraw.Draw(img)

    def rect(x0, y0, x1, y1):
        d.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], fill=fg)

    # Jaws — drawn as rectangles so the square caps are exact
    rect(JAW_L_X - STROKE / 2, JAW_TOP - STROKE / 2,
         JAW_L_X + STROKE / 2, JAW_BOT + STROKE / 2)
    rect(JAW_R_X - STROKE / 2, JAW_TOP - STROKE / 2,
         JAW_R_X + STROKE / 2, JAW_BOT + STROKE / 2)
    # Rail — solid to the golden section
    rect(JAW_L_X - STROKE / 2, RAIL_Y - STROKE / 2, GOLDEN, RAIL_Y + STROKE / 2)
    # Rail — hairline thereafter
    rect(GOLDEN, RAIL_Y - HAIRLINE / 2, JAW_R_X + STROKE / 2, RAIL_Y + HAIRLINE / 2)
    # Notch
    apex_y = RAIL_Y - STROKE / 2 - NOTCH_GAP
    base_y = apex_y - NOTCH_H
    d.polygon([(GOLDEN * s, apex_y * s),
               ((GOLDEN - NOTCH_W / 2) * s, base_y * s),
               ((GOLDEN + NOTCH_W / 2) * s, base_y * s)], fill=fg)
    return img


def generate_favicons(px: int = 512) -> list[str]:
    """
    Write assets/brand/favicon.png (Ink on Bone) and favicon-dark.png (inverted).

    Returns the paths written. Safe to call at import time — it is a no-op once the
    files exist, so it costs one stat() per rerun rather than a re-render.
    """
    os.makedirs(BRAND_DIR, exist_ok=True)
    written: list[str] = []
    targets = [
        ("favicon.png", T.INK, T.BONE),
        ("favicon-dark.png", T.BONE, T.INK),
    ]
    for name, fg, bg in targets:
        path = os.path.join(BRAND_DIR, name)
        if not os.path.exists(path):
            try:
                _draw_favicon(px, fg, bg).save(path, "PNG", optimize=True)
            except Exception:
                # A missing favicon must never break the app — set_page_config falls
                # back to a default icon if the file is absent.
                continue
        written.append(path)
    return written


def favicon_path(dark: bool = False) -> str | None:
    """Absolute path to a generated favicon, or None if generation failed."""
    generate_favicons()
    p = os.path.join(BRAND_DIR, "favicon-dark.png" if dark else "favicon.png")
    return p if os.path.exists(p) else None


def ensure_static_favicon() -> str | None:
    """
    Put a favicon where the templates actually ask for it.

    Both templates request `static/img/favicon.png`, which resolves to
    frontend/static/img/. The generator above writes to assets/brand/ — the brand
    asset directory — so nothing ever appeared at the served path and every page load
    404'd on its icon. Nothing breaks visibly when a favicon is missing, which is why
    it survived the port unnoticed.

    Copied rather than re-pointed: assets/brand/ is the canonical home for brand
    artwork and is referenced by the dissertation, while static/ is what the web server
    exposes. A no-op once the file exists.
    """
    import shutil

    from backend import config

    target_dir = os.path.join(config.STATIC_DIR, "img")
    target = os.path.join(target_dir, "favicon.png")
    if os.path.exists(target):
        return target
    source = favicon_path()
    if not source:
        return None
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(source, target)
        return target
    except Exception:
        # A missing icon is cosmetic. It must never stop the application starting.
        return None


def export_lockup_svg() -> str | None:
    """
    Write assets/brand/lockup.svg for the dissertation. Not used at runtime.

    Pure SVG (text converted to a <text> element) so it can be placed in a document
    without the HTML wrapper the in-app lockup uses.
    """
    os.makedirs(BRAND_DIR, exist_ok=True)
    path = os.path.join(BRAND_DIR, "lockup.svg")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 40" '
        'width="260" height="40" fill="none">'
        '<title>HeartGuard AI</title>'
        f'<g transform="translate(0,4)" stroke="{T.INK}" '
        'stroke-linecap="square" stroke-linejoin="miter">'
        f'<path d="M{JAW_L_X} {JAW_TOP}V{JAW_BOT}" stroke-width="{STROKE}"/>'
        f'<path d="M{JAW_R_X} {JAW_TOP}V{JAW_BOT}" stroke-width="{STROKE}"/>'
        f'<path d="M{JAW_L_X} {RAIL_Y}H{GOLDEN:.2f}" stroke-width="{STROKE}"/>'
        f'<path d="M{GOLDEN:.2f} {RAIL_Y}H{JAW_R_X}" stroke-width="{HAIRLINE}"/>'
        f'</g>'
        f'<polygon points="{_notch_points()}" fill="{T.INK}" '
        'transform="translate(0,4)"/>'
        f'<text x="44" y="26" font-family="Archivo, sans-serif" font-size="20" '
        f'font-weight="600" letter-spacing="-0.2" fill="{T.INK}">HeartGuard</text>'
        f'<rect x="166" y="11" width="1" height="16" fill="{T.CRIMSON}"/>'
        f'<text x="175" y="26" font-family="Archivo, sans-serif" font-size="14.4" '
        f'font-weight="400" fill="{T.CRIMSON}">AI</text>'
        '</svg>'
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        return path
    except Exception:
        return None


__all__ = [
    "mark", "mark_sm", "wordmark", "lockup", "lockup_mono", "mark_watermark",
    "generate_favicons", "favicon_path", "export_lockup_svg",
    "MIN_MARK_PX", "MIN_LOCKUP_PX", "GOLDEN",
]
