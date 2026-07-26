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

    icon_rules = []
    for label, icon_name in sorted(I.NAV_ICON.items()):
        sl = I.slug(label)
        uri = I.to_data_uri(icon_name)
        icon_rules.append(
            f'.st-key-nav-on-{sl} button::before,'
            f'.st-key-nav-off-{sl} button::before{{mask-image:{uri};'
            f'-webkit-mask-image:{uri};}}')
    signout_uri = I.to_data_uri("signout")
    icon_rules.append(
        f'.st-key-nav-signout button::before{{mask-image:{signout_uri};'
        f'-webkit-mask-image:{signout_uri};}}')

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
[class*="st-key-nav-on-"] button,
[class*="st-key-nav-off-"] button,
.st-key-nav-signout button {{
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
[class*="st-key-nav-on-"] button::before,
[class*="st-key-nav-off-"] button::before,
.st-key-nav-signout button::before {{
  content: '';
  width: 18px; height: 18px;
  flex: 0 0 auto;
  background: currentColor;               /* the mask supplies the shape */
  mask-repeat: no-repeat; -webkit-mask-repeat: no-repeat;
  mask-position: center; -webkit-mask-position: center;
  mask-size: contain; -webkit-mask-size: contain;
}}
[class*="st-key-nav-off-"] button:hover {{
  background: var(--hg-sunken) !important;
  color: var(--hg-text);
}}
/* Active item: tinted fill and a 2px accent edge — not a solid verdigris block. */
[class*="st-key-nav-on-"] button {{
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
.login-wrap {{ text-align: center; }}
.login-logo {{
  font-family: var(--hg-font-display);
  font-size: 38px;
  font-weight: {T.WEIGHT['bold']};
  color: var(--hg-primary);
  letter-spacing: var(--hg-track-tighter);
}}
.login-brand {{
  font-family: var(--hg-font-display);
  font-size: 24px;
  font-weight: {T.WEIGHT['semibold']};
  color: var(--hg-text-heading);
}}
.login-tag {{ font-size: 13px; color: var(--hg-text-muted); margin-bottom: var(--hg-space-6); }}
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
