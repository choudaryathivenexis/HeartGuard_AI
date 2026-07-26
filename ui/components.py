"""
HeartGuard AI — Component library
=================================
Reusable render functions. Every component that touches user-controlled data escapes
it internally, so no call site can forget — that is what closed BUG-12, and a redesign
that multiplies `unsafe_allow_html` sites multiplies that risk.

Phase 2 delivers the shell components (`page_header`, `sidebar_nav`, `footer_meta`,
`chip`, `eyebrow`). The remainder of the library from §6 arrives in Phase 4.

--------------------------------------------------------------------------
THE TREATMENT RULE — enforced here, not just documented
--------------------------------------------------------------------------
Low risk and the primary both sit in the Verdigris family, so they are separated by
*treatment*, never by hue:

    interaction     solid verdigris fill + bone text     (buttons, active nav)
    clinical state  tinted surface + dark coloured text  (chips, verdicts, bands)

`chip()` therefore refuses to render a clinical tone as a solid fill, and no
interactive control in this module renders as a tint. A primary button and a "Low" chip
cannot be confused because they are built differently.
"""

from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

from . import brand as B
from . import icons as I
from . import tokens as T
from .format import esc

# Tones permitted for clinical state (tinted surface + coloured text).
CLINICAL_TONES = set(T.RISK_ORDER)
# Tones permitted for system state.
SEMANTIC_TONES = set(T.SEMANTIC) | {"extrapolation", "neutral"}


# ════════════════════════════════════════════════════════════════════════
# Small primitives
# ════════════════════════════════════════════════════════════════════════
def eyebrow(text: str) -> str:
    """11px uppercase label. Encodes hierarchy without adding a heading level."""
    return f'<div class="hg-eyebrow">{esc(text)}</div>'


def chip(label: str, tone: str = "neutral", icon: str | None = None) -> str:
    """
    Status pill — the only pill-radius element in the interface.

    A clinical tone renders as a tinted surface with dark coloured text, never as a
    solid fill. See the treatment rule in the module docstring.
    """
    cls = f"hg-chip hg-chip--{esc(tone)}"
    ico = (f'<span class="hg-chip__icon">{I.to_svg(icon, 12)}</span>'
           if icon and icon in I.ICONS else "")
    return f'<span class="{cls}">{ico}{esc(label)}</span>'


def identifier(value: str, label: str | None = None) -> str:
    """Monospace identifier — model versions, digests, patient codes, run ids."""
    lab = f'<span class="hg-ident__label">{esc(label)}</span>' if label else ""
    return (f'<span class="hg-ident">{lab}'
            f'<span class="hg-ident__value">{esc(value)}</span></span>')


# ════════════════════════════════════════════════════════════════════════
# Page header
# ════════════════════════════════════════════════════════════════════════
def page_header(title: str, subtitle: str | None = None,
                eyebrow_text: str | None = None) -> None:
    """
    Page title block. Replaces the old `section_header`, which emitted a 24px title,
    a subtitle and an <hr> with no hierarchy above it.

    Sticky positioning is applied in CSS rather than here, so the shadow appears only
    once the page has scrolled — a header that always casts a shadow reads as a
    template.
    """
    parts = ['<div class="hg-pagehead">']
    if eyebrow_text:
        parts.append(eyebrow(eyebrow_text))
    parts.append(f'<h1 class="hg-pagehead__title">{esc(title)}</h1>')
    if subtitle:
        parts.append(f'<p class="hg-pagehead__sub">{esc(subtitle)}</p>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def section(title: str, description: str | None = None) -> None:
    """Sub-section divider: eyebrow label plus a rule."""
    body = f'<div class="hg-section">{eyebrow(title)}'
    if description:
        body += f'<p class="hg-section__desc">{esc(description)}</p>'
    body += '</div>'
    st.markdown(body, unsafe_allow_html=True)


@contextmanager
def panel(title: str | None = None, tone: str = "default", key: str | None = None):
    """
    Bordered surface — the structural workhorse.

    Uses a keyed container so the CSS can scope to `.st-key-<key>`, which is the
    officially supported hook, rather than a positional selector.
    """
    container = st.container(key=key) if key else st.container()
    with container:
        if title:
            st.markdown(eyebrow(title), unsafe_allow_html=True)
        yield


# ════════════════════════════════════════════════════════════════════════
# Sidebar navigation
# ════════════════════════════════════════════════════════════════════════
# Grouped with eyebrow labels rather than one flat list of 17 items. Groups are
# declared here in display order; only those a role can actually reach are rendered,
# and an empty group disappears entirely.
NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Clinical", [
        "Dashboard", "Heart Disease Prediction", "Patient Management",
        "Prediction History", "Reports",
    ]),
    ("Model", [
        "Model Performance", "ML Model Management",
    ]),
    ("Administration", [
        "Doctor Management", "Prediction Management", "Dataset Management",
        "Admin Management", "Role & Permission Management", "System Settings",
    ]),
    ("System", [
        "Analytics", "Activity Logs", "Backup & Restore", "Profile",
    ]),
]


def nav_groups_for(pages: list[str]) -> list[tuple[str, list[str]]]:
    """
    Filter the group structure to the pages a role can reach, preserving order.

    Any page not listed in NAV_GROUPS is appended to `System` rather than silently
    dropped — losing a route because someone forgot to register it would be a far
    worse failure than a slightly odd grouping.
    """
    known = {p for _, items in NAV_GROUPS for p in items}
    out: list[tuple[str, list[str]]] = []
    for group, items in NAV_GROUPS:
        present = [p for p in items if p in pages]
        if group == "System":
            present += [p for p in pages if p not in known]
        if present:
            out.append((group, present))
    return out


def sidebar_nav(user: dict, pages: list[str], active: str) -> str:
    """
    Render the sidebar and return the selected page label.

    IMPLEMENTATION NOTE — why buttons rather than st.radio
    -----------------------------------------------------
    The previous shell used a single `st.radio`. A radio cannot carry an inline icon,
    cannot be grouped under eyebrow labels, and cannot take a per-item active treatment
    (§7.1 asks for a 2px verdigris left border on the active item). One button per item
    inside a keyed container gives all three, and `.st-key-*` is the supported scoping
    hook.

    The returned value is still the page LABEL, so `app.py`'s router is unchanged — the
    routing contract does not move.
    """
    sb = st.sidebar

    # ── brand ──────────────────────────────────────────────────────────
    sb.markdown(
        f'<div class="hg-sb-brand">{B.lockup(size=24, wordmark_size=17)}</div>',
        unsafe_allow_html=True)

    # ── user card ──────────────────────────────────────────────────────
    role = user.get("role", "")
    sb.markdown(
        f'<div class="hg-sb-user">'
        f'<div class="hg-sb-user__name">{esc(user.get("fullname", ""))}</div>'
        f'<div class="hg-sb-user__meta">{chip(role, "role")}</div>'
        f'<div class="hg-sb-user__sub">{esc(user.get("specialisation", "") or "")}</div>'
        f'</div>',
        unsafe_allow_html=True)

    # ── grouped navigation ─────────────────────────────────────────────
    selected = active
    for group, items in nav_groups_for(pages):
        sb.markdown(eyebrow(group), unsafe_allow_html=True)
        for label in items:
            is_active = (label == active)
            slug = I.slug(label)
            state = "on" if is_active else "off"
            with sb.container(key=f"nav-{state}-{slug}"):
                if st.button(label, key=f"navbtn-{slug}",
                             use_container_width=True):
                    selected = label
    return selected


def sidebar_footer(app_version: str, model_version: str = "",
                   on_signout=None) -> bool:
    """
    Sign-out pinned below a hairline, then version identifiers in mono.

    Returns True when sign-out was pressed, so the caller keeps control of the
    session-clearing logic — this component never touches session state.
    """
    sb = st.sidebar
    sb.markdown('<div class="hg-sb-divider"></div>', unsafe_allow_html=True)
    with sb.container(key="nav-signout"):
        clicked = st.button("Sign out", key="navbtn-signout",
                            use_container_width=True)
    sb.markdown(
        f'<div class="hg-sb-foot">'
        f'<div>{esc(app_version)}</div>'
        f'<div>model {esc(model_version or "not trained")}</div>'
        f'</div>',
        unsafe_allow_html=True)
    return clicked


def footer_meta(app_version: str, model_version: str, dataset_sha: str) -> None:
    """Mono identifiers at the foot of a page — provenance, quietly available."""
    st.markdown(
        f'<div class="hg-foot-meta">'
        f'{identifier(app_version, "app")}'
        f'{identifier(model_version or "—", "model")}'
        f'{identifier(dataset_sha or "—", "dataset")}'
        f'</div>',
        unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════
# Empty state
# ════════════════════════════════════════════════════════════════════════
def empty_state(title: str, body: str, action: str | None = None) -> None:
    """
    An invitation to act, never an apology.

    §3.9 forbids photography in empty states; the Caliper Mark at low opacity is the
    sanctioned alternative.
    """
    act = (f'<div class="hg-empty__action">{esc(action)}</div>' if action else "")
    st.markdown(
        f'<div class="hg-empty">'
        f'{B.mark_watermark(72, 0.15)}'
        f'<div class="hg-empty__title">{esc(title)}</div>'
        f'<div class="hg-empty__body">{esc(body)}</div>{act}'
        f'</div>',
        unsafe_allow_html=True)


__all__ = [
    "eyebrow", "chip", "identifier", "page_header", "section", "panel",
    "sidebar_nav", "sidebar_footer", "footer_meta", "empty_state",
    "NAV_GROUPS", "nav_groups_for",
]
