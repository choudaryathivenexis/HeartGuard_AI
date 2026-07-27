"""
HeartGuard AI — Global stylesheet
=================================
Generates the injected stylesheet from `ui.tokens`. Nothing here contains a literal
colour; every value is read from the token module, so the palette has exactly one
definition.

--------------------------------------------------------------------------
INJECTION ORDER MATTERS
--------------------------------------------------------------------------
    st.set_page_config(...)     must be the first Streamlit call in the script
    ui.styles.inject()          immediately after, before any widget
    ... everything else

`stylesheet()` is cached with `@st.cache_resource`. Streamlit reruns the whole script
top-to-bottom on every interaction, so rebuilding a ~40KB string each time would both
waste work and cause a flash of unstyled content as the <style> block is re-mounted.

--------------------------------------------------------------------------
SELECTOR POLICY
--------------------------------------------------------------------------
FORBIDDEN: `.st-emotion-cache-*`. Those are build hashes that change on every
Streamlit version bump and would silently destroy the design on the next upgrade.
Recon confirmed the existing 154-line stylesheet used none, and none are introduced
here.

Permitted, in order of preference:
    1. `.st-key-<key>`      from st.container(key=...) — verified supported in 1.59.2
    2. `[data-testid="…"]`  all 33 hooks verified present in the shipped JS bundle
    3. ARIA / semantic      [role="tab"], button[kind="primary"] — accessibility
                            contracts, therefore stable
    4. `.hg-*`              our own classes inside st.markdown — fully under control

Cascade order is fixed by `stylesheet()` and must not be rearranged: import, tokens,
reset, chrome, widgets, components, utilities, responsive, reduced-motion.
"""

from __future__ import annotations

import streamlit as st

from . import tokens as T


# ════════════════════════════════════════════════════════════════════════
# 1. Token emission — Python constants become CSS custom properties
# ════════════════════════════════════════════════════════════════════════
def _vars(mapping: dict[str, str]) -> str:
    return "\n".join(f"    --hg-{k.replace('_', '-')}: {v};"
                     for k, v in sorted(mapping.items()))


def _scale_vars() -> str:
    lines = []
    for i, px in enumerate(T.SPACE):
        lines.append(f"    --hg-space-{i}: {px}px;")
    for name, value in T.RADIUS.items():
        lines.append(f"    --hg-radius-{name}: {value};")
    for name, value in T.SHADOW.items():
        lines.append(f"    --hg-shadow-{name}: {value};")
    for name, value in T.DURATION.items():
        lines.append(f"    --hg-duration-{name}: {value};")
    for name, value in T.TRACKING.items():
        lines.append(f"    --hg-track-{name}: {value};")
    for name, value in T.LAYOUT.items():
        lines.append(f"    --hg-{name.replace('_', '-')}: {value};")
    lines.append(f"    --hg-ease: {T.EASING};")
    lines.append(f"    --hg-font-display: {T.FONT_DISPLAY};")
    lines.append(f"    --hg-font-ui: {T.FONT_UI};")
    lines.append(f"    --hg-font-mono: {T.FONT_MONO};")
    return "\n".join(lines)


def _tokens_block() -> str:
    return f""":root {{
{_vars(T.CSS)}
{_scale_vars()}
}}

/* Dark mode. Streamlit stamps its own theme onto the document; both signals are
   honoured so a user's OS preference and an explicit in-app choice both work. */
[data-theme="dark"], .stApp[data-theme="dark"] {{
{_vars(T.CSS_DARK)}
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{_vars(T.CSS_DARK)}
  }}
}}"""


# ════════════════════════════════════════════════════════════════════════
# 2. Reset & base
# ════════════════════════════════════════════════════════════════════════
def _base_block() -> str:
    return f"""
/* ── reset & base ─────────────────────────────────────────────────── */
html, body, [class*="st-"] {{
  font-family: var(--hg-font-ui);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* Every number in this application uses tabular figures. A probability that shifts
   horizontally as it updates is a defect in a measuring instrument. Applied at the
   root so it covers metrics, tables, rails and any measured value without each call
   site having to remember. */
html {{ {T.TABULAR} }}

h1, h2, h3, h4, h5, h6 {{
  font-family: var(--hg-font-display);
  color: var(--hg-text-heading);
  letter-spacing: var(--hg-track-tight);
  font-weight: {T.WEIGHT['semibold']};
}}

code, kbd, pre, samp, .hg-mono {{ font-family: var(--hg-font-mono); }}

/* Visible focus ring on every interactive element. Never `outline: none` without a
   replacement — WCAG 2.2 §2.4.7. */
*:focus-visible {{
  outline: 2px solid var(--hg-focus-ring);
  outline-offset: 2px;
  border-radius: var(--hg-radius-sm);
}}

::selection {{ background: var(--hg-primary-tint); color: var(--hg-text-heading); }}
"""


# ════════════════════════════════════════════════════════════════════════
# 3. Streamlit chrome
# ════════════════════════════════════════════════════════════════════════
def _chrome_block() -> str:
    return """
/* ── Streamlit chrome ─────────────────────────────────────────────── */
/* Hide the hamburger menu, Deploy button and footer. The sidebar collapse control is
   deliberately left alone — hiding it traps a user in a collapsed sidebar. */
[data-testid="stToolbar"],
[data-testid="stAppDeployButton"],
[data-testid="stDecoration"] { display: none !important; }

[data-testid="stHeader"] {
  background: transparent;
  height: 0;
}

/* Content column: max 1440px, 32px gutters, 24px top (§7.1). */
[data-testid="stMainBlockContainer"] {
  max-width: var(--hg-content-max);
  padding-left: var(--hg-content-pad-x);
  padding-right: var(--hg-content-pad-x);
  padding-top: var(--hg-content-pad-t);
  padding-bottom: var(--hg-space-11);
}

/* Sidebar needs BOTH width and min-width or the flex parent overrides it. */
[data-testid="stSidebar"] {
  width: var(--hg-sidebar-width) !important;   /* overrides Streamlit inline width */
  min-width: var(--hg-sidebar-width) !important;
  background: var(--hg-raised);
  border-right: 1px solid var(--hg-border);
}
[data-testid="stSidebarContent"] { padding-top: var(--hg-space-6); }
"""


# ════════════════════════════════════════════════════════════════════════
# 4. Widgets
# ════════════════════════════════════════════════════════════════════════
def _widgets_block() -> str:
    return f"""
/* ── widgets ──────────────────────────────────────────────────────── */
/* Buttons. Interaction is a SOLID verdigris fill with bone text; a clinical state is a
   tinted surface with dark coloured text. The two are built differently so a primary
   button and a "Low" chip can never be confused despite sharing a hue family. */
[data-testid="stButton"] button,
[data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {{
  font-family: var(--hg-font-ui);
  font-weight: {T.WEIGHT['medium']};
  border-radius: var(--hg-radius-md);
  transition: background var(--hg-duration-fast) var(--hg-ease),
              border-color var(--hg-duration-fast) var(--hg-ease);
  min-height: 38px;
}}
button[kind="primary"], button[kind="primaryFormSubmit"] {{
  background: var(--hg-primary);
  border: 1px solid var(--hg-primary);
  color: var(--hg-text-inverse);
}}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {{
  background: var(--hg-primary-hover);
  border-color: var(--hg-primary-hover);
}}
button[kind="secondary"], button[kind="secondaryFormSubmit"] {{
  background: var(--hg-surface);
  border: 1px solid var(--hg-border-control);
  color: var(--hg-text);
}}
button[kind="secondary"]:hover {{
  border-color: var(--hg-primary);
  color: var(--hg-primary);
}}

/* Inputs. Control boundaries use --hg-border-control (3.32:1 on white) rather than the
   decorative hairline, because WCAG 1.4.11 applies to boundaries required to identify
   a control. */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea {{
  border-radius: var(--hg-radius-md);
  border-color: var(--hg-border-control);
  font-family: var(--hg-font-ui);
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {{
  border-color: var(--hg-primary);
  box-shadow: 0 0 0 1px var(--hg-primary);
}}

/* Tabs — underline slide is one of the four permitted motions. */
[role="tablist"] {{
  gap: var(--hg-space-4);
  border-bottom: 1px solid var(--hg-border);
}}
[role="tab"] {{
  font-family: var(--hg-font-ui);
  font-size: 13px;
  font-weight: {T.WEIGHT['medium']};
  color: var(--hg-text-muted);
  transition: color var(--hg-duration-fast) var(--hg-ease);
}}
[role="tab"][aria-selected="true"] {{
  color: var(--hg-primary);
  font-weight: {T.WEIGHT['semibold']};
}}

/* Expanders */
[data-testid="stExpander"] details {{
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  background: var(--hg-surface);
}}
[data-testid="stExpander"] summary {{
  font-family: var(--hg-font-ui);
  font-size: 13px;
  font-weight: {T.WEIGHT['medium']};
  color: var(--hg-text);
}}

/* Metrics — tabular figures and the display face on the value. */
[data-testid="stMetricValue"] {{
  font-family: var(--hg-font-display);
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading);
}}
[data-testid="stMetricLabel"] {{
  font-size: 12px;
  font-weight: {T.WEIGHT['medium']};
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-muted);
}}

[data-testid="stDataFrame"] {{
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  overflow: hidden;
}}
"""


# ════════════════════════════════════════════════════════════════════════
# 5. Legacy compatibility shim
# ════════════════════════════════════════════════════════════════════════
def _shell_block() -> str:
    """
    Sidebar, navigation, page header, chips, empty state.

    Nav icons are attached with CSS `mask-image` and `background: currentColor`, because
    `st.button` takes a plain-text label and escapes inline SVG. A mask contributes only
    alpha, so one data URI serves both themes and the icon inherits the item's text
    colour — including the verdigris accent on the active item. A background-image
    would need the colour baked in and therefore two copies of every icon.
    """
    from . import icons as I

    # One rule per icon. The container key no longer encodes active state (see
    # components.sidebar_nav), so a single selector covers both, halving 36 rules to 18
    # and reclaiming ~7.5 KB of the 60 KB CSS budget.
    # Each data URI is declared ONCE as a custom property and consumed by the shared
    # ::before rule below, which applies both the prefixed and unprefixed mask. Emitting
    # `mask-image:<uri>; -webkit-mask-image:<uri>` per icon duplicated every payload and
    # cost ~7.5 KB of the 60 KB budget for nothing. Safari needed the prefix until 15.4,
    # so dropping it outright is not an option — declaring the value once is.
    icon_rules = []
    for label, icon_name in sorted(I.NAV_ICON.items()):
        icon_rules.append(
            f'.st-key-nav-{I.slug(label)} button::before'
            f'{{--hg-nav-icon:{I.to_data_uri(icon_name)};}}')
    icon_rules.append(
        f'.st-key-nav-signout button::before'
        f'{{--hg-nav-icon:{I.to_data_uri("signout")};}}')

    return f"""
/* ── sidebar: brand ───────────────────────────────────────────────── */
.hg-sb-brand {{
  padding: var(--hg-space-2) var(--hg-space-1) var(--hg-space-4);
  border-bottom: 3px solid var(--hg-primary);
  margin-bottom: var(--hg-space-5);
}}

/* ── sidebar: user card ───────────────────────────────────────────── */
.hg-sb-user {{
  background: var(--hg-sunken);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-4);
  margin-bottom: var(--hg-space-6);
}}
.hg-sb-user__name {{
  font-size: 14px;
  font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading);
  line-height: 1.3;
}}
.hg-sb-user__meta {{ margin: var(--hg-space-2) 0 0; }}
.hg-sb-user__sub {{
  font-size: 11.5px;
  color: var(--hg-text-subtle);
  margin-top: var(--hg-space-2);
}}

/* ── eyebrow ──────────────────────────────────────────────────────── */
.hg-eyebrow {{
  font-size: 11px;
  font-weight: {T.WEIGHT['semibold']};
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-subtle);
  margin: var(--hg-space-5) 0 var(--hg-space-2);
}}
[data-testid="stSidebar"] .hg-eyebrow {{ padding-left: var(--hg-space-2); }}

/* ── sidebar: navigation items ────────────────────────────────────── */
/* One button per item inside a keyed container. Streamlit sets inline styles on the
   button element, so the resets below need !important to land. */
[class*="st-key-nav-"] button {{
  display: flex !important;               /* overrides Streamlit's inline display */
  align-items: center;
  gap: var(--hg-space-3);
  justify-content: flex-start !important; /* overrides Streamlit's centred label */
  text-align: left;
  font-size: 13.5px;
  font-weight: {T.WEIGHT['regular']};
  color: var(--hg-text-muted);
  background: transparent !important;     /* overrides Streamlit's button fill */
  border: 0 !important;
  border-left: 2px solid transparent !important;
  border-radius: var(--hg-radius-md);
  padding: var(--hg-space-3) var(--hg-space-4);
  min-height: 34px;
  box-shadow: none !important;
  transition: background var(--hg-duration-fast) var(--hg-ease),
              color var(--hg-duration-fast) var(--hg-ease);
}}
[class*="st-key-nav-"] button::before {{
  content: '';
  width: 18px; height: 18px;
  flex: 0 0 auto;
  background: currentColor;               /* the mask supplies the shape */
  mask-image: var(--hg-nav-icon); -webkit-mask-image: var(--hg-nav-icon);
  mask-repeat: no-repeat; -webkit-mask-repeat: no-repeat;
  mask-position: center; -webkit-mask-position: center;
  mask-size: contain; -webkit-mask-size: contain;
}}
[class*="st-key-nav-"] button[kind="secondary"]:hover {{
  background: var(--hg-sunken) !important;
  color: var(--hg-text);
}}
/* Active item: tinted fill and a 2px accent edge — NOT a solid verdigris block, even
   though Streamlit's primary kind normally means exactly that. The nav rules come after
   the widget block in the cascade, so these win. */
[class*="st-key-nav-"] button[kind="primary"] {{
  background: var(--hg-primary-tint) !important;
  border-left-color: var(--hg-primary) !important;
  color: var(--hg-primary);
  font-weight: {T.WEIGHT['semibold']};
}}
{''.join(icon_rules)}

.hg-sb-divider {{
  border-top: 1px solid var(--hg-border);
  margin: var(--hg-space-6) 0 var(--hg-space-3);
}}
.st-key-nav-signout button:hover {{
  background: var(--hg-danger-surface) !important;
  color: var(--hg-danger-text);
}}
.hg-sb-foot {{
  font-family: var(--hg-font-mono);
  font-size: 11px;
  color: var(--hg-text-subtle);
  line-height: 1.6;
  padding: var(--hg-space-3) var(--hg-space-2) var(--hg-space-5);
}}

/* ── page header ──────────────────────────────────────────────────── */
.hg-pagehead {{
  padding-bottom: var(--hg-space-4);
  border-bottom: 1px solid var(--hg-border);
  margin-bottom: var(--hg-space-6);
}}
.hg-pagehead__title {{
  font-family: var(--hg-font-display);
  font-size: 24px;
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading);
  margin: 0;
  line-height: 1.2;
}}
.hg-pagehead__sub {{
  font-size: 13px;
  color: var(--hg-text-muted);
  margin: var(--hg-space-2) 0 0;
  max-width: 78ch;
  line-height: 1.6;
}}
.hg-section {{ margin: var(--hg-space-7) 0 var(--hg-space-4); }}
.hg-section .hg-eyebrow {{ margin-top: 0; }}
.hg-section__desc {{
  font-size: 12.5px; color: var(--hg-text-muted);
  margin: var(--hg-space-2) 0 0; max-width: 78ch;
}}

/* ── chips ────────────────────────────────────────────────────────── */
/* The ONLY pill-radius element. A clinical tone is a tinted surface with dark
   coloured text; it never renders as a solid fill, which is what keeps it visually
   distinct from an interactive control in the same hue family. */
.hg-chip {{
  display: inline-flex;
  align-items: center;
  gap: var(--hg-space-2);
  font-size: 11px;
  font-weight: {T.WEIGHT['semibold']};
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  padding: 3px var(--hg-space-3);
  border-radius: var(--hg-radius-pill);
  border: 1px solid;
  white-space: nowrap;
}}
.hg-chip__icon {{ display: inline-flex; }}
.hg-chip--neutral, .hg-chip--role {{
  background: var(--hg-primary-tint);
  color: var(--hg-primary);
  border-color: var(--hg-primary-border);
}}
.hg-chip--low {{ background: var(--hg-risk-low-surface); color: var(--hg-risk-low-text); border-color: var(--hg-risk-low-border); }}
.hg-chip--borderline {{ background: var(--hg-risk-borderline-surface); color: var(--hg-risk-borderline-text); border-color: var(--hg-risk-borderline-border); }}
.hg-chip--intermediate {{ background: var(--hg-risk-intermediate-surface); color: var(--hg-risk-intermediate-text); border-color: var(--hg-risk-intermediate-border); }}
.hg-chip--high {{ background: var(--hg-risk-high-surface); color: var(--hg-risk-high-text); border-color: var(--hg-risk-high-border); }}
.hg-chip--info {{ background: var(--hg-info-surface); color: var(--hg-info-text); border-color: var(--hg-info-border); }}
.hg-chip--success {{ background: var(--hg-success-surface); color: var(--hg-success-text); border-color: var(--hg-success-border); }}
.hg-chip--warning {{ background: var(--hg-warning-surface); color: var(--hg-warning-text); border-color: var(--hg-warning-border); }}
.hg-chip--danger {{ background: var(--hg-danger-surface); color: var(--hg-danger-text); border-color: var(--hg-danger-border); }}

/* ── identifiers ──────────────────────────────────────────────────── */
.hg-ident {{ display: inline-flex; align-items: baseline; gap: var(--hg-space-2); }}
.hg-ident__label {{
  font-size: 10.5px; text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow); color: var(--hg-text-subtle);
}}
.hg-ident__value {{
  font-family: var(--hg-font-mono); font-size: 11.5px; color: var(--hg-text-muted);
}}
.hg-foot-meta {{
  display: flex; flex-wrap: wrap; gap: var(--hg-space-6);
  padding-top: var(--hg-space-5); margin-top: var(--hg-space-8);
  border-top: 1px solid var(--hg-border);
}}

/* ── empty state ──────────────────────────────────────────────────── */
.hg-empty {{
  text-align: center;
  padding: var(--hg-space-9) var(--hg-space-6);
  border: 1px dashed var(--hg-border-strong);
  border-radius: var(--hg-radius-xl);
  background: var(--hg-surface);
}}
.hg-empty__title {{
  font-family: var(--hg-font-display);
  font-size: 16px; font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading); margin-top: var(--hg-space-3);
}}
.hg-empty__body {{
  font-size: 13px; color: var(--hg-text-muted);
  margin: var(--hg-space-2) auto 0; max-width: 46ch; line-height: 1.6;
}}
.hg-empty__action {{
  font-size: 12.5px; color: var(--hg-primary);
  font-weight: {T.WEIGHT['medium']}; margin-top: var(--hg-space-4);
}}
"""


def _rail_block() -> str:
    """
    The Reference Rail.

    Positions arrive as inline `left`/`width` percentages computed in ui/rail.py — the
    geometry is Python, so it is unit-testable; only appearance lives here.
    """
    return f"""
/* ── Reference Rail ───────────────────────────────────────────────── */
.hg-rail {{
  position: relative;
  width: 100%;
  padding-top: 18px;          /* room for the notch, which sits ABOVE the track */
  margin: var(--hg-space-3) 0 var(--hg-space-6);
  {T.TABULAR}
}}
.hg-rail--env, .hg-rail--ci {{ padding-top: 2px; }}

/* head row: name on the left, value on the right */
.hg-rail__head {{
  display: flex; align-items: baseline; gap: var(--hg-space-3);
  margin-bottom: var(--hg-space-2);
}}
.hg-rail__name {{
  font-size: 12px; color: var(--hg-text-muted); flex: 1 1 auto;
}}
.hg-rail__value {{
  font-size: 12.5px; font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading);
}}
.hg-rail__ci-text {{
  font-weight: {T.WEIGHT['regular']}; color: var(--hg-text-subtle); font-size: 11.5px;
}}
.hg-rail__state {{
  font-size: 10.5px; text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-hazard-text); background: var(--hg-hazard-surface);
  border: 1px solid var(--hg-hazard-border);
  border-radius: var(--hg-radius-sm); padding: 1px var(--hg-space-2);
}}

/* threshold notch — ink, never a risk colour: it is a boundary, not a reading */
.hg-rail__notch {{
  position: absolute; top: 0; transform: translateX(-50%);
  display: flex; flex-direction: column; align-items: center; z-index: 3;
}}
.hg-rail__notch-tick {{
  width: 0; height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid var(--hg-text-heading);
}}
.hg-rail__notch-label {{
  order: -1;
  font-size: 9.5px; text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-subtle); white-space: nowrap; margin-bottom: 1px;
}}

/* band strip — labels only. Filling these zones would compete with the one fill that
   carries information: the measured value. */
.hg-rail__strip {{ position: relative; height: 13px; margin-bottom: 3px; }}
.hg-rail__band {{
  position: absolute; top: 0;
  font-size: 9.5px; letter-spacing: var(--hg-track-eyebrow);
  text-align: center; overflow: hidden; white-space: nowrap;
  text-overflow: ellipsis;
}}

/* track */
.hg-rail__track {{
  position: relative;
  height: var(--hg-rail-height);
  background: var(--hg-rail-track);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-sm);
  overflow: hidden;
}}
.hg-rail__track--env {{ height: 12px; }}
.hg-rail__track--ci, .hg-rail__track--sweep {{ height: var(--hg-rail-height-sm); }}

/* Every fill carries a hairline outline in the band border colour. WCAG 1.4.11 asks
   for 3:1 on a meaningful graphical object; Borderline is only 2.57:1 against the
   track unaided, so delineation supplies what fill contrast cannot. */
.hg-rail__fill {{
  position: absolute; inset: 0 auto 0 0;
  border-right: 1px solid var(--hg-text-heading);
  box-shadow: inset 0 0 0 1px rgba(14,19,26,.14);
}}
.hg-rail__fill--anim {{
  animation: hg-rail-fill var(--hg-duration-slow) var(--hg-ease);
}}
@keyframes hg-rail-fill {{ from {{ width: 0 !important; }} }}

.hg-rail__tick {{
  position: absolute; top: 0; bottom: 0; width: 1px;
  background: var(--hg-border-strong); z-index: 2;
}}
.hg-rail__marker {{
  position: absolute; top: -3px; bottom: -3px; width: 2px;
  transform: translateX(-1px);
  background: var(--hg-surface);
  border-left: 2px solid; border-right: 0;
  z-index: 4;
}}
.hg-rail__marker--pin {{
  top: -4px; bottom: -4px; width: 3px;
  border-left-width: 3px;
}}
.hg-rail__marker--point {{
  top: -3px; bottom: -3px; width: 9px; height: 9px;
  margin: auto 0; border: 0; border-radius: 50%;
  transform: translateX(-50%);
  outline: 2px solid var(--hg-surface);
}}

/* invalid span — the hazard stripe, the only repeating pattern in the interface */
.hg-rail__hatch {{ position: absolute; inset: 0 auto 0 0; opacity: .5; z-index: 1; }}
/* p1-p99: where training support is dense. Context, not a reading. */
.hg-rail__dense {{
  position: absolute; inset: 0 auto 0 0;
  background: var(--hg-primary-tint); z-index: 1;
}}
.hg-rail__env {{
  position: absolute; inset: 0 auto 0 0;
  border-left: 1px solid var(--hg-border-control);
  border-right: 1px solid var(--hg-border-control);
  z-index: 2;
}}

/* confidence interval span */
.hg-rail__ci {{
  position: absolute; top: 50%; height: 4px; transform: translateY(-50%);
  border-radius: 2px; opacity: .42; z-index: 2;
}}
.hg-rail__ref {{
  position: absolute; top: -5px; bottom: -5px; width: 0;
  border-left: 1px dashed var(--hg-text-muted); z-index: 3;
}}
.hg-rail__ref-label {{
  position: absolute; top: -13px; left: 3px;
  font-size: 9px; color: var(--hg-text-subtle); white-space: nowrap;
}}

/* candidate operating points */
.hg-rail__cand {{
  position: absolute; top: -2px; bottom: -2px; width: 1px;
  background: var(--hg-text-subtle); z-index: 3;
}}
.hg-rail__cand--sel {{
  width: 2px; background: var(--hg-text-heading);
  top: -4px; bottom: -4px;
}}

/* numeric labels — endpoints are never dropped */
.hg-rail__labels {{ position: relative; height: 15px; margin-top: 3px; }}
.hg-rail__lab {{
  position: absolute; top: 0;
  font-size: 10.5px; color: var(--hg-text-subtle); white-space: nowrap;
}}
.hg-rail__lab--mid {{ color: var(--hg-text-muted); font-weight: {T.WEIGHT['medium']}; }}

.hg-rail-stack {{ display: flex; flex-direction: column; }}
.hg-rail-row {{ border-bottom: 1px solid var(--hg-border); }}
.hg-rail-row:last-child {{ border-bottom: 0; }}
.hg-rail-row .hg-rail {{ margin-bottom: var(--hg-space-3); }}

/* Below 480px the rail keeps its FULL WIDTH and drops only the intermediate labels.
   Endpoints and the band strip stay — a rail without endpoints is decoration. */
@media (max-width: 480px) {{
  .hg-rail__lab--mid {{ display: none; }}
  .hg-rail__notch-label {{ display: none; }}
  .hg-rail__band {{ font-size: 8.5px; }}
}}
"""


def _components_block() -> str:
    """Stats, alerts, the clinical verdict, operating point, reliability, tables."""
    hatch_edge = (
        f"repeating-linear-gradient(45deg,"
        f"{T.HAZARD['stripe_a']} 0 3px,"
        f"{T.HAZARD['stripe_b']} 3px 6px)"
    )
    return f"""
/* ── stats ────────────────────────────────────────────────────────── */
/* Hairline-separated strip, not floating cards. The grid background supplies the 1px
   gaps so four figures read as one instrument panel. No shadows — §3.5 prefers
   hairlines for structure, and a card that always casts a shadow reads as a template. */
.hg-stat-grid {{
  display: grid;
  grid-template-columns: repeat(var(--hg-stat-cols, 4), minmax(0, 1fr));
  gap: 1px;
  background: var(--hg-border);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  overflow: hidden;
  margin-bottom: var(--hg-space-6);
}}
.hg-stat {{
  background: var(--hg-surface);
  padding: var(--hg-space-5);
  display: flex; flex-direction: column; gap: 2px;
}}
.hg-stat__label {{
  font-size: 11px; font-weight: {T.WEIGHT['medium']};
  text-transform: uppercase; letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-muted);
}}
.hg-stat__value {{
  font-family: var(--hg-font-display);
  font-size: 30px; font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading); line-height: 1.05;
}}
.hg-stat__delta {{ font-size: 12px; font-weight: {T.WEIGHT['medium']}; }}
.hg-stat__delta--low, .hg-stat__delta--success {{ color: var(--hg-risk-low-text); }}
.hg-stat__delta--high, .hg-stat__delta--danger {{ color: var(--hg-risk-high-text); }}
.hg-stat__delta--warning {{ color: var(--hg-warning-text); }}
.hg-stat__hint {{ font-size: 11.5px; color: var(--hg-text-subtle); }}
.hg-stat--low .hg-stat__value {{ color: var(--hg-risk-low-text); }}
.hg-stat--high .hg-stat__value {{ color: var(--hg-risk-high-text); }}

/* ── alerts ───────────────────────────────────────────────────────── */
.hg-alert {{
  display: flex; gap: var(--hg-space-4);
  padding: var(--hg-space-4) var(--hg-space-5);
  border: 1px solid; border-left-width: 3px;
  border-radius: var(--hg-radius-md);
  margin: var(--hg-space-3) 0;
  font-size: 13px; line-height: 1.6;
}}
.hg-alert__icon {{ flex: 0 0 auto; margin-top: 1px; }}
.hg-alert__title {{ font-weight: {T.WEIGHT['semibold']}; }}
.hg-alert__body {{ margin-top: 3px; }}
.hg-alert__list {{ margin: var(--hg-space-2) 0 0 var(--hg-space-5); padding: 0; }}
.hg-alert--info {{ background: var(--hg-info-surface); border-color: var(--hg-info-border); border-left-color: var(--hg-text-muted); color: var(--hg-info-text); }}
.hg-alert--success {{ background: var(--hg-success-surface); border-color: var(--hg-success-border); border-left-color: var(--hg-success-text); color: var(--hg-success-text); }}
.hg-alert--warning {{ background: var(--hg-warning-surface); border-color: var(--hg-warning-border); border-left-color: var(--hg-warning-text); color: var(--hg-warning-text); }}
.hg-alert--danger {{ background: var(--hg-danger-surface); border-color: var(--hg-danger-border); border-left-color: var(--hg-danger-text); color: var(--hg-danger-text); }}

/* Extrapolation is NOT a severity — it is a validity failure, so it takes no risk
   colour. The Ink+Amber hazard stripe is the only repeating pattern in the interface,
   which makes it unmistakable and impossible to read as "worse than High". */
.hg-alert--extrapolation {{
  background: var(--hg-hazard-surface);
  border-color: var(--hg-hazard-border);
  border-left: 6px solid transparent;
  border-image: {hatch_edge} 1;
  color: var(--hg-hazard-text);
}}
.hg-alert--extrapolation .hg-alert__title {{ letter-spacing: .2px; }}

/* ── the clinical verdict ─────────────────────────────────────────── */
.hg-verdict {{
  background: var(--hg-surface);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-xl);
  padding: var(--hg-space-6);
  margin-bottom: var(--hg-space-5);
}}
.hg-verdict--extrap {{ border-color: var(--hg-hazard-border); }}
.hg-verdict__row {{
  display: flex; align-items: center; gap: var(--hg-space-5);
  margin: var(--hg-space-2) 0 var(--hg-space-2);
}}
/* Archivo Expanded 600 at 64px, tabular. The figure is the reading — it earns the
   display face and the size, and nothing decorative sits behind it. */
.hg-verdict__prob {{
  font-family: var(--hg-font-display);
  font-size: 64px; font-weight: {T.WEIGHT['semibold']};
  font-variation-settings: 'wdth' 112;
  letter-spacing: var(--hg-track-tighter);
  line-height: 1; {T.TABULAR}
}}
/* Band chip BESIDE the figure, never below it. */
.hg-verdict__band {{ display: flex; flex-direction: column; gap: var(--hg-space-2); }}
.hg-verdict__extrap {{
  font-size: 10px; text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-hazard-text); background: var(--hg-hazard-surface);
  border: 1px solid var(--hg-hazard-border);
  border-radius: var(--hg-radius-sm); padding: 1px var(--hg-space-2);
}}
.hg-verdict__action {{
  font-size: 13px; color: var(--hg-text); line-height: 1.6;
  padding-top: var(--hg-space-3); border-top: 1px solid var(--hg-border);
}}

/* ── operating point & reliability ────────────────────────────────── */
.hg-op, .hg-rel {{
  background: var(--hg-raised);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-5);
  margin-bottom: var(--hg-space-4);
}}
.hg-op .hg-eyebrow, .hg-rel .hg-eyebrow {{ margin-top: 0; }}
.hg-op__grid, .hg-rel__grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(84px, 1fr));
  gap: var(--hg-space-4) var(--hg-space-5);
}}
.hg-op__k {{
  font-size: 10.5px; text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow); color: var(--hg-text-subtle);
}}
.hg-op__v {{
  font-size: 14px; font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading); {T.TABULAR}
}}
.hg-op__source {{
  font-size: 12px; color: var(--hg-text-muted);
  margin-top: var(--hg-space-4); padding-top: var(--hg-space-3);
  border-top: 1px solid var(--hg-border); line-height: 1.6;
}}
.hg-rel__head {{
  display: flex; align-items: center; gap: var(--hg-space-3);
  margin-bottom: var(--hg-space-2);
}}
/* Rating as TEXT as well as colour — §3.3 forbids meaning carried by hue alone. */
.hg-rel__rating {{
  font-family: var(--hg-font-display);
  font-size: 18px; font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading);
}}
.hg-rel__grid {{ margin-top: var(--hg-space-3); }}

/* ── static tables ───────────────────────────────────────────────── */
.hg-tbl-wrap {{
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  overflow-x: auto;                 /* wide tables scroll themselves, never the page */
  margin-bottom: var(--hg-space-5);
}}
.hg-tbl {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
.hg-tbl th {{
  text-align: left; padding: var(--hg-space-3) var(--hg-space-4);
  background: var(--hg-sunken);
  font-size: 10.5px; font-weight: {T.WEIGHT['semibold']};
  text-transform: uppercase; letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-muted);
  border-bottom: 1px solid var(--hg-border);
  white-space: nowrap;
}}
.hg-tbl td {{
  padding: var(--hg-space-3) var(--hg-space-4);
  border-bottom: 1px solid var(--hg-border);
  color: var(--hg-text); {T.TABULAR}
}}
.hg-tbl tbody tr:last-child td {{ border-bottom: 0; }}
.hg-tbl tbody tr:hover td {{ background: var(--hg-sunken); }}
.hg-tbl--num {{ text-align: right; }}
.hg-tbl__row--hl td {{
  background: var(--hg-primary-tint);
  font-weight: {T.WEIGHT['semibold']};
}}

@media (max-width: 768px) {{
  .hg-stat-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .hg-verdict__prob {{ font-size: 48px; }}
  .hg-verdict__row {{ gap: var(--hg-space-4); }}
}}
"""


def _legacy_block() -> str:
    """
    Back-compatible rules for the 24 pre-redesign classes.

    Recon counted 111 usages of these across 116 `unsafe_allow_html` blocks. Rewriting
    every call site in one step would make an AppTest failure impossible to attribute,
    so the old class names keep working — restyled onto the new tokens — and each page
    migrates to the component library in its own phase. This block shrinks to nothing
    by Phase 10.
    """
    return f"""
/* ── legacy shim (removed progressively, Phases 2-10) ─────────────── */
.hg-title {{
  font-family: var(--hg-font-display);
  font-size: 24px;
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading);
  margin: 0 0 2px 0;
}}
.hg-subtitle {{
  font-size: 13px;
  color: var(--hg-text-muted);
  margin: 0 0 var(--hg-space-4) 0;
}}
.hg-divider {{
  border: 0;
  border-top: 1px solid var(--hg-border);
  margin: var(--hg-space-4) 0 var(--hg-space-6) 0;
}}
.panel {{
  background: var(--hg-surface);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-6);
  margin-bottom: var(--hg-space-5);
}}
.alert-info, .alert-warning {{
  border-radius: var(--hg-radius-md);
  padding: var(--hg-space-4) var(--hg-space-5);
  font-size: 13px;
  line-height: 1.6;
  margin: var(--hg-space-3) 0;
  border-left: 3px solid;
}}
.alert-info {{
  background: var(--hg-info-surface);
  border-color: var(--hg-info-border);
  border-left-color: var(--hg-text-muted);
  color: var(--hg-info-text);
}}
.alert-warning {{
  background: var(--hg-warning-surface);
  border-color: var(--hg-warning-border);
  border-left-color: var(--hg-warning-text);
  color: var(--hg-warning-text);
}}
.kpi-wrap {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1px;
  background: var(--hg-border);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  overflow: hidden;
  margin-bottom: var(--hg-space-6);
}}
/* Hairline-separated, equal height, no shadows — a strip, not floating cards. */
.kpi-card {{
  background: var(--hg-surface) !important;   /* overrides inline gradient from callers */
  border: 0 !important;
  padding: var(--hg-space-5) var(--hg-space-5);
}}
.kpi-val {{
  font-family: var(--hg-font-display);
  font-size: 30px;
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading) !important;   /* overrides inline colour from callers */
  line-height: 1.1;
}}
.kpi-lbl {{
  font-size: 11px;
  font-weight: {T.WEIGHT['medium']};
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-muted);
  margin-top: var(--hg-space-2);
}}
.role-badge {{
  display: inline-block;
  font-size: 11px;
  font-weight: {T.WEIGHT['semibold']};
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  padding: 2px var(--hg-space-3);
  border-radius: var(--hg-radius-pill);
  background: var(--hg-primary-tint);
  color: var(--hg-primary);
  border: 1px solid var(--hg-primary-border);
}}
.rb-doctor, .rb-admin, .rb-superadmin {{
  background: var(--hg-primary-tint);
  color: var(--hg-primary);
  border-color: var(--hg-primary-border);
}}
.user-card {{
  background: var(--hg-sunken);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-4);
  margin-bottom: var(--hg-space-5);
}}
.res-risk, .res-safe {{
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-6);
  border: 1px solid;
}}
.res-risk {{
  background: var(--hg-risk-high-surface);
  border-color: var(--hg-risk-high-border);
}}
.res-safe {{
  background: var(--hg-risk-low-surface);
  border-color: var(--hg-risk-low-border);
}}
.res-title {{
  font-family: var(--hg-font-display);
  font-size: 20px;
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-base);
}}
.res-prob {{ font-size: 14px; color: var(--hg-text); margin-top: var(--hg-space-2); }}
.res-note {{ font-size: 12.5px; color: var(--hg-text-muted); margin-top: var(--hg-space-3); line-height: 1.6; }}
"""


# ════════════════════════════════════════════════════════════════════════
# 5b. Login (§7.2)
# ════════════════════════════════════════════════════════════════════════
def _login_block() -> str:
    """
    The 44/56 full-bleed split.

    Every rule is gated behind `:has()` on markup that only the login screen emits, so
    this block is inert on all 27 authenticated pages. That is what makes it safe to
    override the shell's content column here — the override cannot leak.

    The left panel is Ink in BOTH themes. It is brand surface rather than page surface,
    so it takes literal hexes, not the themed --hg-surface family. Its text colours are
    fixed Bone alphas for the same reason.
    """
    ink = T.INK
    bone = T.BONE
    return f"""
/* ── login: full-bleed override ───────────────────────────────────── */
/* Scoped to the marker container emitted by ui.login.split(). The shell's 1440px
   content column and 32px gutters would otherwise stop the split reaching the
   viewport edges, which is the whole point of the screen. */
.stApp:has(.st-key-login-mode) [data-testid="stMainBlockContainer"] {{
  padding: 0 !important;
  max-width: none !important;
}}
.stApp:has(.st-key-login-mode) [data-testid="stSidebar"] {{ display: none !important; }}
[data-testid="stHorizontalBlock"]:has(.hg-login-brand) {{
  gap: 0 !important;
  align-items: stretch;
}}

/* ── login: left panel ────────────────────────────────────────────── */
[data-testid="stColumn"]:has(.hg-login-brand) {{
  background: {ink};
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 56px clamp(28px, 4vw, 56px);
  position: relative;
  overflow: hidden;
}}
/* Guarantees the ambient art resolves against the COLUMN and not against some
   intermediate Streamlit wrapper that a future release decides to position. */
[data-testid="stColumn"]:has(.hg-login-brand) [data-testid="stVerticalBlock"],
[data-testid="stColumn"]:has(.hg-login-brand) [data-testid="stMarkdownContainer"],
[data-testid="stColumn"]:has(.hg-login-brand) .stMarkdown {{ position: static; }}

.hg-login-brand {{ position: relative; z-index: 1; }}
.hg-login-lockup {{ margin-bottom: var(--hg-space-7); }}
.hg-login-statement {{
  margin: 0;
  max-width: 40ch;
  font-size: 16px;
  line-height: 1.65;
  color: {T.alpha(bone, 0.74)};
}}

.hg-login-markers {{
  margin-top: var(--hg-space-8);
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.hg-login-marker {{ display: flex; align-items: baseline; gap: var(--hg-space-4); }}
.hg-login-marker__k {{
  flex: none;
  min-width: 124px;
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: {T.alpha(bone, 0.50)};
}}
.hg-login-marker__v {{
  font-family: var(--hg-font-mono);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: {T.alpha(bone, 0.90)};
}}

/* ── login: ambient rail (decorative, 8%, static) ─────────────────── */
.hg-login-art {{
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 33%;
  z-index: 0;
  opacity: 0.08;
  color: {bone};
  pointer-events: none;
  display: flex;
  align-items: flex-end;
}}
.hg-login-rail {{ display: block; width: 100%; height: 100%; }}

/* ── login: right panel ───────────────────────────────────────────── */
[data-testid="stColumn"]:has(.st-key-login-card) {{
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px clamp(16px, 3vw, 32px);
}}
.st-key-login-card {{
  width: 100%;
  max-width: 400px;
  margin: 0 auto;
  padding: 40px;
  background: var(--hg-surface);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-xl);
  box-shadow: var(--hg-shadow-e3);
}}
.hg-login-head {{ margin-bottom: var(--hg-space-6); }}
.hg-login-title {{
  margin: 0;
  font-family: var(--hg-font-display);
  font-size: 22px;
  font-weight: {T.WEIGHT['semibold']};
  letter-spacing: var(--hg-track-tight);
  color: var(--hg-text-heading);
}}
.hg-login-sub {{
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--hg-text-muted);
}}

/* Segmented control spans the card; Sign in / Register are equal halves. */
.st-key-login-seg [data-testid="stSegmentedControl"] {{ width: 100%; }}
.st-key-login-seg [data-testid="stSegmentedControl"] > div {{
  display: flex;
  width: 100%;
}}
.st-key-login-seg [data-testid="stSegmentedControl"] label {{
  flex: 1 1 0;
  justify-content: center;
}}

/* §7.2: primary action full width, 44px tall — the WCAG 2.2 AA target minimum. */
.st-key-login-card .stFormSubmitButton button,
.st-key-login-card .stButton button {{
  width: 100%;
  min-height: 44px;
}}

/* ── login: inline validation ─────────────────────────────────────── */
/* Sits beneath its field, never above the form. The negative top margin pulls it
   into the gap Streamlit leaves under an input so the message reads as belonging
   to that field rather than floating between two of them. */
.hg-login-err {{
  display: flex;
  gap: var(--hg-space-2);
  align-items: stretch;
  margin: -10px 0 var(--hg-space-4);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--hg-danger-text);
}}
.hg-login-err::before {{
  content: '';
  flex: none;
  width: 2px;
  background: var(--hg-danger-border);
  border-radius: 1px;
}}
.hg-login-hint {{
  margin: var(--hg-space-6) 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  text-align: center;
  color: var(--hg-text-subtle);
}}

/* ── login: stack below 900px ─────────────────────────────────────── */
@media (max-width: 900px) {{
  [data-testid="stHorizontalBlock"]:has(.hg-login-brand) {{ flex-direction: column; }}
  [data-testid="stColumn"]:has(.hg-login-brand) {{
    min-height: auto;
    padding: 40px 28px 0;
  }}
  [data-testid="stColumn"]:has(.st-key-login-card) {{ min-height: auto; padding: 32px 20px; }}
  .hg-login-art {{ position: relative; height: 96px; margin-top: var(--hg-space-7); }}
}}
"""


# ════════════════════════════════════════════════════════════════════════
# 6. Utilities, responsive, motion
# ════════════════════════════════════════════════════════════════════════
def _tail_block() -> str:
    return """
/* ── utilities ────────────────────────────────────────────────────── */
.hg-u-mono { font-family: var(--hg-font-mono); }
.hg-u-eyebrow {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: var(--hg-track-eyebrow);
  color: var(--hg-text-muted);
}
.hg-u-muted { color: var(--hg-text-muted); }
.hg-u-subtle { color: var(--hg-text-subtle); }

/* ── responsive ───────────────────────────────────────────────────── */
@media (max-width: 1100px) {
  [data-testid="stMainBlockContainer"] { padding-left: 20px; padding-right: 20px; }
}
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding-left: 14px; padding-right: 14px; }
  .kpi-wrap { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); }
}

/* ── motion ───────────────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
  }
}

/* ── forced colors ────────────────────────────────────────────────── */
@media (forced-colors: active) {
  .panel, .kpi-wrap, .user-card, .res-risk, .res-safe { border: 1px solid CanvasText; }
}

/* ── print ────────────────────────────────────────────────────────── */
@media print {
  [data-testid="stSidebar"], [data-testid="stHeader"] { display: none !important; }
  [data-testid="stMainBlockContainer"] { max-width: none; padding: 0; }
}
"""


# ════════════════════════════════════════════════════════════════════════
# Assembly
# ════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def stylesheet() -> str:
    """
    The complete stylesheet, assembled once per process.

    Cascade order is fixed and must not be rearranged (see module docstring). The
    @import MUST be the first rule or browsers drop it silently.
    """
    return "\n".join([
        f"@import url('{T.FONT_IMPORT}');",
        _tokens_block(),
        _base_block(),
        _chrome_block(),
        _widgets_block(),
        _shell_block(),
        _rail_block(),
        _components_block(),
        _login_block(),
        _legacy_block(),
        _tail_block(),
    ])


def active_theme() -> str:
    """
    'dark' or 'light' for the current viewer.

    Read from `st.context.theme` rather than inferred from a DOM attribute. Streamlit's
    own theme signal is authoritative and available in Python, so the token override
    below is deterministic instead of depending on whether a `data-theme` attribute
    happens to be stamped on the document in this version.
    """
    try:
        t = getattr(st.context, "theme", None)
        value = getattr(t, "type", None) or getattr(t, "base", None)
        if value:
            return "dark" if str(value).lower() == "dark" else "light"
    except Exception:
        pass
    try:
        return "dark" if st.get_option("theme.base") == "dark" else "light"
    except Exception:
        return "light"


def _theme_override(theme: str) -> str:
    """
    Re-declare the dark tokens at :root when the viewer is in dark mode.

    The base stylesheet already carries `[data-theme="dark"]` and a
    prefers-color-scheme block, but neither fires when a user picks dark mode inside
    Streamlit while their OS is light. This override closes that gap; it is the only
    part of the stylesheet that is not cacheable per-process, so it is emitted
    separately and kept small.
    """
    if theme != "dark":
        return ""
    return ":root{\n" + _vars(T.CSS_DARK) + "\n}"


def inject() -> None:
    """Inject the stylesheet. Call once, immediately after st.set_page_config."""
    st.markdown(
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        f"<style>{stylesheet()}</style>"
        f"<style>{_theme_override(active_theme())}</style>",
        unsafe_allow_html=True,
    )


def size_kb() -> float:
    """Injected CSS weight — §8 budgets under 60KB."""
    return len(stylesheet().encode("utf-8")) / 1024.0
