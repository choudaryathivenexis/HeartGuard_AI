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
from .format import (esc, pct, metric3, count, signed, reliability_rating,
                     threshold as fmt_threshold)

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
            # The container key does NOT encode active state. It used to
            # (nav-on-<slug> / nav-off-<slug>), which forced TWO icon-mask selectors per
            # item — 36 rules and ~15 KB of the CSS budget for 18 icons. Active state is
            # now carried by the button's own `type`, so the key is stable and one mask
            # rule per icon suffices.
            with sb.container(key=f"nav-{I.slug(label)}"):
                if st.button(label, key=f"navbtn-{I.slug(label)}",
                             width="stretch",
                             type="primary" if label == active else "secondary"):
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
                            width="stretch")
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


# ════════════════════════════════════════════════════════════════════════
# Statistics
# ════════════════════════════════════════════════════════════════════════
def stat(label: str, value: str, delta: str | None = None,
         hint: str | None = None, tone: str = "default") -> str:
    """
    A single measured figure. Label above value, tabular figures mandatory.

    Callers pass ALREADY-FORMATTED strings. Formatting lives in ui/format.py so the
    decimal discipline in §3.4 is enforced once rather than at every call site — the
    codebase previously mixed :.1%, :.2%, :.3f and :.4f for the same quantity depending
    on which call site you happened to read.
    """
    d = (f'<div class="hg-stat__delta hg-stat__delta--{esc(tone)}">{esc(delta)}</div>'
         if delta else "")
    h = f'<div class="hg-stat__hint">{esc(hint)}</div>' if hint else ""
    return (f'<div class="hg-stat hg-stat--{esc(tone)}">'
            f'<div class="hg-stat__label">{esc(label)}</div>'
            f'<div class="hg-stat__value">{esc(value)}</div>{d}{h}</div>')


def stat_grid(stats: list[dict], cols: int = 4) -> None:
    """
    A strip of equal-height figures separated by hairlines.

    Deliberately NOT floating cards: §3.5 prefers hairline borders over shadows, and a
    dashboard where every tile casts a shadow reads as a template. The grid background
    supplies the 1px gaps, so the strip reads as one instrument panel rather than four
    detached objects.
    """
    cells = "".join(stat(**s) for s in stats)
    st.markdown(
        f'<div class="hg-stat-grid" style="--hg-stat-cols:{int(cols)};">{cells}</div>',
        unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════
# Alerts
# ════════════════════════════════════════════════════════════════════════
def alert(severity: str, title: str, body: str | None = None,
          items: list[str] | None = None) -> None:
    """
    System or clinical notice.

    `severity` ∈ {info, success, warning, danger, extrapolation}.

    `extrapolation` is not a severity level — it is a VALIDITY FAILURE, so it gets no
    risk colour at all. It carries the Ink+Amber hazard stripe as a 6px left edge, the
    only repeating pattern anywhere in the interface. A black-and-amber stripe reads
    universally as "boundary crossed" rather than "worse than High", which is exactly
    the distinction that matters: an extrapolated reading is off the scale, not high on
    it.
    """
    sev = severity if severity in SEMANTIC_TONES else "info"
    icon_name = {"info": "info", "success": "check", "warning": "warning",
                 "danger": "warning", "extrapolation": "warning"}.get(sev, "info")
    lis = ("<ul class=\"hg-alert__list\">"
           + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>") if items else ""
    bod = f'<div class="hg-alert__body">{esc(body)}</div>' if body else ""
    st.markdown(
        f'<div class="hg-alert hg-alert--{esc(sev)}" role="alert">'
        f'<div class="hg-alert__icon">{I.to_svg(icon_name, 16)}</div>'
        f'<div class="hg-alert__content">'
        f'<div class="hg-alert__title">{esc(title)}</div>{bod}{lis}'
        f'</div></div>',
        unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════
# The clinical hero
# ════════════════════════════════════════════════════════════════════════
def risk_verdict(prob: float, band_label: str, band_key: str,
                 bands: tuple[float, float, float], threshold: float,
                 action: str, extrapolated: bool = False,
                 animate: bool = True) -> None:
    """
    The highest-stakes component in the application.

    `bands` and `threshold` are passed in rather than recomputed, so the rail can never
    disagree with the verdict the app already decided — the same discipline the rail
    module follows.

    The eyebrow reads SCREENING RESULT, not "Diagnosis". §3.10 fixes that vocabulary:
    a positive means *further testing indicated*, never *disease present*. A tool at
    0.85 sensitivity misses roughly one diseased patient in six, and no visual treatment
    here may make a "Low" verdict read as reassurance.
    """
    from . import rail as R

    colour = T.RISK[band_key]["rail"]
    tag = ' <span class="hg-verdict__extrap">extrapolated</span>' if extrapolated else ""
    cls = "hg-verdict" + (" hg-verdict--extrap" if extrapolated else "")

    st.markdown(
        f'<div class="{cls}">'
        f'{eyebrow("Screening result")}'
        f'<div class="hg-verdict__row">'
        f'<div class="hg-verdict__prob" style="color:{colour};">{pct(prob)}</div>'
        f'<div class="hg-verdict__band">{chip(band_label, band_key)}{tag}</div>'
        f'</div>'
        f'{R.risk_rail(prob, bands, threshold, band_key, animate=animate)}'
        f'<div class="hg-verdict__action">{esc(action)}</div>'
        f'</div>',
        unsafe_allow_html=True)


def operating_point(threshold: float, sens: float | None, spec: float | None,
                    ppv: float | None = None, npv: float | None = None,
                    source: str = "") -> None:
    """
    The decision boundary in force, and a plain sentence saying WHY it is that value.

    Disclosing the operating point is not decoration. A clinician cannot calibrate
    trust in a flag without it, and hiding it is precisely how a hardcoded 0.50 survived
    unexamined while missing 31% of diseased patients (Run 4).
    """
    cells = [("Threshold", fmt_threshold(threshold)),
             ("Sensitivity", metric3(sens)),
             ("Specificity", metric3(spec))]
    if ppv is not None:
        cells.append(("PPV", metric3(ppv)))
    if npv is not None:
        cells.append(("NPV", metric3(npv)))
    body = "".join(
        f'<div class="hg-op__cell"><div class="hg-op__k">{esc(k)}</div>'
        f'<div class="hg-op__v">{esc(v)}</div></div>' for k, v in cells)
    src = f'<div class="hg-op__source">{esc(source)}</div>' if source else ""
    st.markdown(
        f'<div class="hg-op">{eyebrow("Operating point")}'
        f'<div class="hg-op__grid">{body}</div>{src}</div>',
        unsafe_allow_html=True)


def reliability_panel(auc_value: float | None, ci_lo: float | None,
                      ci_hi: float | None, cal_gap: float | None,
                      n: int | None, band_label: str = "",
                      caution: str | None = None,
                      overall: float | None = None) -> None:
    """
    How well the model performs for THIS KIND of patient.

    Rating is rendered as TEXT (Strong / Moderate / Limited) alongside the rail, never
    as colour alone — §3.3 forbids encoding meaning in hue, and a clinician with
    deuteranopia must read the same information as everyone else.

    This panel exists because aggregate AUC concealed that discrimination ranges from
    0.84 under 45 to 0.73 in the 55-59 band. Only the aggregate was ever shown.
    """
    from . import rail as R

    rating = reliability_rating(auc_value)
    rating_key = {"Strong": "low", "Moderate": "borderline",
                  "Limited": "high"}.get(rating, "borderline")

    meta = []
    if cal_gap is not None:
        meta.append(("Calibration gap", signed(cal_gap)))
    if n:
        meta.append(("Measured on", f"{count(n)} held-out patients"))
    if band_label:
        meta.insert(0, ("Patient group", band_label))
    meta_html = "".join(
        f'<div class="hg-rel__cell"><div class="hg-op__k">{esc(k)}</div>'
        f'<div class="hg-op__v">{esc(v)}</div></div>' for k, v in meta)

    rail_html = ""
    if auc_value is not None:
        rail_html = R.ci_rail(auc_value, ci_lo, ci_hi, domain=(0.55, 0.90),
                              reference=overall, reference_label="overall",
                              label="Discrimination",
                              colour=T.RISK[rating_key]["rail"])

    st.markdown(
        f'<div class="hg-rel">{eyebrow("Model reliability for this patient")}'
        f'<div class="hg-rel__head">'
        f'<span class="hg-rel__rating">{esc(rating)}</span>'
        f'{chip(rating + " discrimination", rating_key)}'
        f'</div>{rail_html}'
        f'<div class="hg-rel__grid">{meta_html}</div></div>',
        unsafe_allow_html=True)
    if caution:
        alert("warning", "Interpret with extra caution", caution)


# ════════════════════════════════════════════════════════════════════════
# Tables
# ════════════════════════════════════════════════════════════════════════
def data_table(df, column_config: dict | None = None, height: int | None = None,
               key: str | None = None) -> None:
    """
    Wraps st.dataframe.

    `st.dataframe` renders to a canvas grid that CSS barely reaches, so `column_config`
    is the supported route for formatting and alignment — not hand-built HTML. A
    13,000-row hand-built table would be a performance disaster and is never the answer.

    FIXED in Phase 8: `height` was being forwarded unconditionally, and Streamlit
    rejects `height=None` with `StreamlitInvalidHeightError` — it wants a positive
    integer, 'stretch', 'content', or the argument absent. So this component raised on
    every call that did not pass an explicit height, i.e. every call a page would
    naturally make. It shipped in Phase 4 because the component test only ever
    exercised `static_table`; `data_table` was exported, documented, and never once
    invoked. A component library needs its smoke test to call EVERY export with its
    default arguments — that is now asserted.
    """
    kwargs = {"column_config": column_config or None, "hide_index": True,
              "width": "stretch"}
    if height is not None:
        kwargs["height"] = height
    if key is not None:
        kwargs["key"] = key
    st.dataframe(df, **kwargs)


# ════════════════════════════════════════════════════════════════════════
# Destructive actions
# ════════════════════════════════════════════════════════════════════════
def danger_zone(title: str, body: str):
    """
    §7.6: a `danger`-toned panel with a HAIRLINE border, not a red fill.

    "Red fills desensitise; the border plus typed confirmation is what actually prevents
    accidents." A user who sees a red block every time they open Activity Logs stops
    seeing it by the third visit — the signal has to be rare to work.
    """
    container = st.container(key="hg-danger-zone")
    with container:
        st.markdown(
            f'<div class="hg-danger">'
            f'<div class="hg-danger__head">{esc(title)}</div>'
            f'<p class="hg-danger__body">{esc(body)}</p></div>',
            unsafe_allow_html=True)
    return container


def destructive(label: str, confirm: str, key: str, *,
                caption: str | None = None) -> bool:
    """
    A destructive action gated behind typed confirmation. Returns True only on the run
    where the user has typed `confirm` exactly and pressed the button.

    §7.6 forbids "a bare primary button next to a benign one", which is what all ten of
    these were: `st.button("Delete Account")` sitting inches from `st.button("Save")`,
    same size, same weight, one click and irreversible. Two of them — Clear All
    Predictions and Purge Audit Logs — were adjacent to each other with no guard at all,
    and the Phase 4 deep test destroyed the entire fixture database by clicking them.

    The typed word is the target's own identifier rather than a generic "DELETE", so
    muscle memory cannot carry a user through the gate: confirming requires reading
    which record is about to go.

    The button stays enabled and reports the mismatch instead of being disabled. A
    disabled button with no explanation is a dead end; this says what is missing.
    """
    typed = st.text_input(
        f"Type {confirm} to confirm", key=f"{key}__confirm",
        placeholder=confirm, label_visibility="visible")
    if caption:
        st.caption(caption)
    pressed = st.button(label, key=f"{key}__go", width="stretch")
    if not pressed:
        return False
    if typed.strip() != confirm:
        alert("warning", "Not confirmed",
              f"This action was not carried out. Type {confirm!r} exactly — "
              f"character for character — to confirm it.")
        return False
    return True


def static_table(cols: list[str], rows: list[list], highlight: int | None = None,
                 align_right: set[int] | None = None) -> None:
    """
    Hand-built HTML for SMALL comparison tables where full control matters — operating
    points, candidate thresholds, benchmark comparators.

    Every cell is escaped. Numeric columns are right-aligned so tabular figures line up,
    which is the whole point of using them.
    """
    ar = align_right or set()
    head = "".join(
        f'<th class="{"hg-tbl--num" if i in ar else ""}">{esc(c)}</th>'
        for i, c in enumerate(cols))
    body = []
    for r, row in enumerate(rows):
        cls = ' class="hg-tbl__row--hl"' if highlight == r else ""
        cells = "".join(
            f'<td class="{"hg-tbl--num" if i in ar else ""}">{esc(v)}</td>'
            for i, v in enumerate(row))
        body.append(f"<tr{cls}>{cells}</tr>")
    st.markdown(
        f'<div class="hg-tbl-wrap"><table class="hg-tbl">'
        f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody>'
        f'</table></div>',
        unsafe_allow_html=True)


__all__ = [
    "eyebrow", "chip", "identifier", "page_header", "section", "panel",
    "sidebar_nav", "sidebar_footer", "footer_meta", "empty_state",
    "stat", "stat_grid", "alert", "risk_verdict", "operating_point",
    "reliability_panel", "data_table", "static_table", "danger_zone", "destructive",
    "NAV_GROUPS", "nav_groups_for", "CLINICAL_TONES", "SEMANTIC_TONES",
]
