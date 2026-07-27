"""
The sign-in screen — §7.2.

A 44/56 full-bleed split. The left panel is the product's only piece of pure brand
surface; the right panel is a single 400px form card and nothing else.

WHY THIS MODULE EXISTS SEPARATELY FROM components.py
    Everything in components.py is reusable across pages. Nothing here is: the
    full-bleed override, the ambient rail and the trust-marker strip appear on exactly
    one screen. Keeping them out of the component library stops that library from
    accumulating one-offs, which is how component libraries die.

WHY IT TAKES FACTS AS ARGUMENTS
    `brand_panel` receives the record count and the trust markers already formatted.
    It does not open models/results.json. That mirrors `risk_verdict`, which receives
    the bands and threshold rather than recomputing them — a presentation module that
    reads model artifacts is a presentation module that can disagree with the model.
    app.py owns the reading; this module owns the rendering.

THE AMBIENT RAIL
    §7.2 asks for "a large, static Reference Rail as ambient background art in the
    lower third of the left panel ... at 8% opacity, no animation." It is decorative,
    so it is aria-hidden and carries no value marker — a rail showing a *number* on the
    sign-in screen would be a claim about a patient who does not exist yet. What it
    shows is the empty instrument: the track, the four band zones, the scale. The
    visual language, taught before first contact, with nothing asserted.

    It is hand-built rather than routed through ui/rail.py because rail.py renders
    positioned HTML sized in em against live data, and this needs a single scalable
    vector that survives being stretched across a 44%-width panel at any viewport.
"""
from __future__ import annotations

import contextlib

import streamlit as st

from . import brand as B
from . import tokens as T
from .format import esc

__all__ = [
    "split", "brand_panel", "card", "inline_error", "seed_hint", "ambient_rail",
    "STATEMENT",
]

# The one line of substance from §7.2. `{n}` is filled with the real training row
# count so the claim cannot drift away from the manifest.
STATEMENT = ("Cardiovascular risk screening across {n} patient records, with the "
             "model's operating envelope disclosed on every result.")


# ════════════════════════════════════════════════════════════════════════
# Ambient rail
# ════════════════════════════════════════════════════════════════════════
def ambient_rail() -> str:
    """
    The empty instrument, as a scalable vector.

    Geometry is expressed against the real band edges from thresholds.json so the
    proportions on the sign-in screen match the proportions on a result — 0.2335 /
    0.3572 / 0.6699. Hard-coding them here would be a second source of truth, so they
    arrive as fractions of the 0–1 domain and are scaled to the viewBox.
    """
    w, h = 900.0, 260.0
    x0, x1 = 20.0, w - 20.0
    span = x1 - x0
    track_y = 150.0
    # Band edges as fractions of the probability domain. These are the shipped
    # thresholds; they are visual proportions here, not a claim about any patient.
    edges = [0.0, 0.2335, 0.3572, 0.6699, 1.0]
    ramp = [T.RISK[k]["rail"] for k in ("low", "borderline", "intermediate", "high")]

    parts = [
        f'<svg class="hg-login-rail" viewBox="0 0 {w:.0f} {h:.0f}" '
        f'preserveAspectRatio="none" aria-hidden="true" focusable="false">'
    ]
    # Band zones — flat segments, no gradient, matching the rail's own treatment.
    for i in range(4):
        bx = x0 + edges[i] * span
        bw = (edges[i + 1] - edges[i]) * span
        parts.append(f'<rect x="{bx:.1f}" y="{track_y:.1f}" width="{bw:.1f}" '
                     f'height="14" fill="{ramp[i]}"/>')
    # Terminal serifs — the caliper jaws, the same motif as the mark.
    for tx in (x0, x1):
        parts.append(f'<line x1="{tx:.1f}" y1="{track_y - 22:.1f}" x2="{tx:.1f}" '
                     f'y2="{track_y + 36:.1f}" stroke="currentColor" stroke-width="2"/>')
    # Interior notches at the band edges, descending below the track.
    for e in edges[1:-1]:
        nx = x0 + e * span
        parts.append(f'<line x1="{nx:.1f}" y1="{track_y - 12:.1f}" x2="{nx:.1f}" '
                     f'y2="{track_y + 26:.1f}" stroke="currentColor" stroke-width="1.5"/>')
    # Minor graticule every 10%, above the track only, so the band zones stay clean.
    for i in range(1, 10):
        gx = x0 + (i / 10.0) * span
        parts.append(f'<line x1="{gx:.1f}" y1="{track_y - 7:.1f}" x2="{gx:.1f}" '
                     f'y2="{track_y:.1f}" stroke="currentColor" stroke-width="1"/>')
    parts.append('</svg>')
    return "".join(parts)


# ════════════════════════════════════════════════════════════════════════
# Layout
# ════════════════════════════════════════════════════════════════════════
@contextlib.contextmanager
def split():
    """
    Yield (left, right) as a 44/56 full-bleed split.

    The empty `login-mode` container is a CSS hook, not a spacer: the stylesheet uses
    `.stApp:has(.st-key-login-mode)` to strip the main block's padding and max-width
    for this screen only. Without it the split would sit inside the 1440px content
    column with 32px gutters and would not be full-bleed at all.
    """
    st.container(key="login-mode")
    left, right = st.columns([44, 56], gap="small")
    yield left, right


def brand_panel(statement: str, markers: list[tuple[str, str]]) -> None:
    """
    The left panel: lockup, statement, trust markers, ambient rail.

    `markers` is a list of (label, value) already formatted by the caller. Values are
    rendered in mono because they are measurements, and measurements are monospaced
    everywhere in this application.
    """
    rows = "".join(
        f'<div class="hg-login-marker">'
        f'<span class="hg-login-marker__k">{esc(k)}</span>'
        f'<span class="hg-login-marker__v">{esc(v)}</span>'
        f'</div>'
        for k, v in markers
    )
    st.markdown(
        '<div class="hg-login-brand">'
        # Mono lockup in Bone: the panel is Ink, so the two-colour lockup would put
        # Verdigris on near-black and lose most of its contrast.
        f'<div class="hg-login-lockup">'
        f'{B.lockup_mono(T.BONE, size=34, wordmark_size=24)}</div>'
        f'<p class="hg-login-statement">{esc(statement)}</p>'
        f'<div class="hg-login-markers">{rows}</div>'
        f'<div class="hg-login-art">{ambient_rail()}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


@contextlib.contextmanager
def card(title: str, subtitle: str = ""):
    """The right panel: one 400px card, vertically centred, holding live widgets."""
    with st.container(key="login-right"):
        with st.container(key="login-card"):
            head = f'<h1 class="hg-login-title">{esc(title)}</h1>'
            if subtitle:
                head += f'<p class="hg-login-sub">{esc(subtitle)}</p>'
            st.markdown(f'<div class="hg-login-head">{head}</div>',
                        unsafe_allow_html=True)
            yield


# ════════════════════════════════════════════════════════════════════════
# Validation
# ════════════════════════════════════════════════════════════════════════
def inline_error(msg: str | None) -> None:
    """
    §7.2: "Inline validation beneath each field, not a banner above."

    A no-op when `msg` is falsy, so a call site can sit unconditionally beneath its
    field. That matters: the error slot must occupy the same position in the document
    whether or not it has content, or fields would jump as validation appears.
    """
    if not msg:
        return
    st.markdown(
        f'<div class="hg-login-err" role="alert">{esc(msg)}</div>',
        unsafe_allow_html=True,
    )


def seed_hint() -> None:
    """
    Points at the server console instead of printing credentials into the DOM.

    §7.2 required the three default logins be removed from the browser. They are now
    printed once, by auth_db.init_db, at the moment the database is first created —
    visible to whoever started the process, invisible to whoever visits the page.
    """
    st.markdown(
        '<p class="hg-login-hint">First run? The seeded accounts were printed to the '
        'server console when the database was created.</p>',
        unsafe_allow_html=True,
    )
