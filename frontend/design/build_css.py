"""
Build frontend/static/css/app.css from the design tokens.

WHY GENERATED AND NOT HAND-WRITTEN
`shared/tokens.py` is the single definition of every colour in the product. Hand-typing
those hexes into a stylesheet would create a second definition that drifts — which is
the exact failure the token module was written to end. So the custom-property block is
emitted from the tokens and the component rules consume the variables.

WHY THIS IS ~700 LINES AND NOT 1800
The stylesheet it replaces spent most of its weight fighting Streamlit: overriding
`[data-testid=...]` selectors, undoing default widget chrome, re-specifying layout the
framework had already decided. Rendering our own HTML removes all of that. What is left
is the design system itself.

Run:  python -m frontend.design.build_css
"""
from __future__ import annotations

import os

from backend import config
from shared import tokens as T

OUTPUT = os.path.join(config.STATIC_DIR, "css", "app.css")


def _root_vars() -> str:
    lines = [":root {"]
    for key, value in sorted(T.CSS.items()):
        lines.append(f"  --hg-{key.replace('_', '-')}: {value};")
    for i, px in enumerate(T.SPACE):
        lines.append(f"  --hg-space-{i}: {px}px;")
    for name, value in T.RADIUS.items():
        lines.append(f"  --hg-radius-{name}: {value};")
    for name, value in T.SHADOW.items():
        lines.append(f"  --hg-shadow-{name}: {value};")
    lines.append(f"  --hg-font-display: {T.FONT_DISPLAY};")
    lines.append(f"  --hg-font-ui: {T.FONT_UI};")
    lines.append(f"  --hg-font-mono: {T.FONT_MONO};")
    lines.append("  --hg-sidebar-width: 264px;")
    lines.append("  --hg-content-max: 1440px;")
    lines.append("}")
    return "\n".join(lines)


COMPONENTS = """
/* ═══════════════════════════════════════════════════════════════════
   RESET
   ═══════════════════════════════════════════════════════════════════ */
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; font-variant-numeric: tabular-nums; }
body {
  margin: 0;
  font-family: var(--hg-font-ui);
  font-size: 14px;
  line-height: 1.55;
  color: var(--hg-text);
  background: var(--hg-canvas);
  -webkit-font-smoothing: antialiased;
}
h1, h2, h3, h4 {
  font-family: var(--hg-font-display);
  color: var(--hg-text-heading);
  margin: 0 0 var(--hg-space-3);
  line-height: 1.2;
  font-weight: 600;
  letter-spacing: -0.011em;
}
h1 { font-size: 30px; }
h2 { font-size: 20px; }
h3 { font-size: 16px; }
p  { margin: 0 0 var(--hg-space-4); }
a  { color: var(--hg-link); text-decoration: underline; text-underline-offset: 2px; }
a:hover { color: var(--hg-primary-hover); }
code, pre, .mono { font-family: var(--hg-font-mono); }
img, svg { max-width: 100%; }
:focus-visible {
  outline: 2px solid var(--hg-focus-ring);
  outline-offset: 2px;
  border-radius: 2px;
}

/* ═══════════════════════════════════════════════════════════════════
   APP SHELL
   ═══════════════════════════════════════════════════════════════════ */
.shell { display: flex; min-height: 100vh; }

.sidebar {
  width: var(--hg-sidebar-width);
  flex: 0 0 var(--hg-sidebar-width);
  background: var(--hg-raised);
  border-right: 1px solid var(--hg-border);
  display: flex;
  flex-direction: column;
  padding: var(--hg-space-6) 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}
.sidebar__brand { padding: 0 var(--hg-space-6) var(--hg-space-4); }
.sidebar__rule {
  height: 2px; background: var(--hg-primary);
  margin: 0 var(--hg-space-6) var(--hg-space-5);
}
.sidebar__user {
  margin: 0 var(--hg-space-5) var(--hg-space-6);
  padding: var(--hg-space-4);
  background: var(--hg-sunken);
  border-radius: var(--hg-radius-lg);
}
.sidebar__name { font-weight: 600; color: var(--hg-text-heading); }
.sidebar__meta { font-size: 12px; color: var(--hg-text-muted); }
.sidebar__group { margin-bottom: var(--hg-space-5); }
.sidebar__grouptitle {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--hg-text-subtle);
  padding: 0 var(--hg-space-6); margin-bottom: var(--hg-space-2);
}
.navlink {
  display: flex; align-items: center; gap: var(--hg-space-4);
  padding: 9px var(--hg-space-6);
  color: var(--hg-text); text-decoration: none;
  border-left: 3px solid transparent;
  font-size: 13.5px;
}
.navlink:hover { background: var(--hg-sunken); color: var(--hg-text-heading); }
.navlink--active {
  background: var(--hg-primary-tint);
  border-left-color: var(--hg-primary);
  color: var(--hg-primary);
  font-weight: 600;
}
.navlink svg { flex: none; }
.sidebar__foot {
  margin-top: auto; padding: var(--hg-space-5) var(--hg-space-6) 0;
  border-top: 1px solid var(--hg-border);
  font-family: var(--hg-font-mono); font-size: 11px; color: var(--hg-text-subtle);
}

.main { flex: 1 1 auto; min-width: 0; }
.content {
  max-width: var(--hg-content-max);
  margin: 0 auto;
  padding: var(--hg-space-8) var(--hg-space-8) var(--hg-space-11);
}

/* ═══════════════════════════════════════════════════════════════════
   PAGE HEADER
   ═══════════════════════════════════════════════════════════════════ */
.pagehead {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--hg-space-6);
  padding-bottom: var(--hg-space-4);
  border-bottom: 1px solid var(--hg-border);
  margin-bottom: var(--hg-space-7);
}
.pagehead__sub { color: var(--hg-text-muted); font-size: 13px; margin: 0; max-width: 78ch; }
.pagehead__art { color: var(--hg-primary); flex: none; display: flex;
                 align-items: center; gap: var(--hg-space-4); }
.eyebrow {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--hg-text-subtle);
  margin-bottom: var(--hg-space-3);
}

/* ═══════════════════════════════════════════════════════════════════
   PANELS, GRID
   ═══════════════════════════════════════════════════════════════════ */
.panel {
  background: var(--hg-surface);
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  padding: var(--hg-space-6);
  margin-bottom: var(--hg-space-6);
}
.panel__title { font-size: 15px; margin-bottom: var(--hg-space-4); }
.grid { display: grid; gap: var(--hg-space-6); }
.grid--2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.grid--4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.grid--sidebarless { grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); }
@media (max-width: 1100px) {
  .grid--3, .grid--4, .grid--sidebarless { grid-template-columns: repeat(2, minmax(0,1fr)); }
}
@media (max-width: 760px) {
  .grid--2, .grid--3, .grid--4, .grid--sidebarless { grid-template-columns: 1fr; }
}

/* ═══════════════════════════════════════════════════════════════════
   STAT STRIP
   ═══════════════════════════════════════════════════════════════════ */
.stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  background: var(--hg-surface);
  overflow: hidden;
  margin-bottom: var(--hg-space-7);
}
.stat { padding: var(--hg-space-5) var(--hg-space-6);
        border-right: 1px solid var(--hg-border); }
.stat:last-child { border-right: 0; }
.stat__label {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--hg-text-subtle);
}
.stat__value {
  font-family: var(--hg-font-display); font-size: 30px; font-weight: 600;
  color: var(--hg-text-heading); line-height: 1.1; margin-top: 2px;
}
.stat__hint { font-size: 11.5px; color: var(--hg-text-subtle); }
.stat--danger .stat__value { color: var(--hg-danger-text); }
.stat--good   .stat__value { color: var(--hg-success-text); }

/* ═══════════════════════════════════════════════════════════════════
   FORMS
   ═══════════════════════════════════════════════════════════════════ */
.field { margin-bottom: var(--hg-space-5); }
.field__label {
  display: block; font-size: 12.5px; font-weight: 500;
  color: var(--hg-text); margin-bottom: 5px;
}
.field__hint { font-size: 11.5px; color: var(--hg-text-subtle); margin-top: 4px; }
input[type=text], input[type=password], input[type=email], input[type=number],
input[type=date], select, textarea {
  width: 100%;
  padding: 9px 11px;
  font-family: var(--hg-font-ui);
  font-size: 14px;
  color: var(--hg-text);
  background: var(--hg-surface);
  border: 1px solid var(--hg-border-control);
  border-radius: var(--hg-radius-md);
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--hg-primary);
  box-shadow: 0 0 0 3px var(--hg-primary-tint);
}
textarea { min-height: 84px; resize: vertical; }
.checkline { display: flex; align-items: center; gap: var(--hg-space-3);
             min-height: 24px; margin-bottom: var(--hg-space-3); }
.checkline input { width: 16px; height: 16px; accent-color: var(--hg-primary); }

.btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: var(--hg-space-3);
  min-height: 38px; padding: 8px 16px;
  font-family: var(--hg-font-ui); font-size: 14px; font-weight: 500;
  border-radius: var(--hg-radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  text-decoration: none;
  /* Labels wrap rather than overflow. A fixed-height button with a nowrap label is
     how text ends up rendered outside its own border in a narrow column. */
  white-space: normal;
  overflow-wrap: anywhere;
  line-height: 1.35;
  text-align: center;
}
.btn--primary { background: var(--hg-primary); color: var(--hg-text-inverse);
                border-color: var(--hg-primary); }
.btn--primary:hover { background: var(--hg-primary-hover);
                      border-color: var(--hg-primary-hover); color: var(--hg-text-inverse); }
.btn--secondary { background: var(--hg-surface); color: var(--hg-text);
                  border-color: var(--hg-border-control); }
.btn--secondary:hover { border-color: var(--hg-primary); color: var(--hg-primary); }
.btn--danger { background: var(--hg-danger-text); color: #fff;
               border-color: var(--hg-danger-text); }
.btn--block { width: 100%; }
.btn--sm { min-height: 30px; padding: 4px 10px; font-size: 12.5px; }
.btn[disabled] { opacity: .55; cursor: not-allowed; }

/* ═══════════════════════════════════════════════════════════════════
   TABLES
   ═══════════════════════════════════════════════════════════════════ */
.tablewrap {
  border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-lg);
  overflow-x: auto;
  background: var(--hg-surface);
  margin-bottom: var(--hg-space-6);
}
table.data { width: 100%; border-collapse: collapse; font-size: 13px; }
table.data th {
  text-align: left; font-weight: 600; font-size: 11.5px;
  text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--hg-text-muted); background: var(--hg-sunken);
  padding: 9px 12px; border-bottom: 1px solid var(--hg-border);
  white-space: nowrap;
}
table.data td { padding: 9px 12px; border-bottom: 1px solid var(--hg-border); }
table.data tr:last-child td { border-bottom: 0; }
table.data tr:hover td { background: var(--hg-raised); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.empty {
  padding: var(--hg-space-9); text-align: center; color: var(--hg-text-muted);
  border: 1px dashed var(--hg-border-strong); border-radius: var(--hg-radius-lg);
  background: var(--hg-surface);
}

/* ═══════════════════════════════════════════════════════════════════
   CHIPS, ALERTS
   ═══════════════════════════════════════════════════════════════════ */
.chip {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; padding: 3px 9px;
  border-radius: var(--hg-radius-pill); border: 1px solid;
  white-space: nowrap;
}
.chip--neutral { color: var(--hg-text-muted); background: var(--hg-sunken);
                 border-color: var(--hg-border); }
.chip--low  { color: var(--hg-risk-low-text);  background: var(--hg-risk-low-surface);
              border-color: var(--hg-risk-low-border); }
.chip--borderline { color: var(--hg-risk-borderline-text);
                    background: var(--hg-risk-borderline-surface);
                    border-color: var(--hg-risk-borderline-border); }
.chip--intermediate { color: var(--hg-risk-intermediate-text);
                      background: var(--hg-risk-intermediate-surface);
                      border-color: var(--hg-risk-intermediate-border); }
.chip--high { color: var(--hg-risk-high-text); background: var(--hg-risk-high-surface);
              border-color: var(--hg-risk-high-border); }

.alert {
  display: flex; gap: var(--hg-space-4);
  padding: var(--hg-space-4) var(--hg-space-5);
  border-radius: var(--hg-radius-md);
  border: 1px solid; border-left-width: 3px;
  margin-bottom: var(--hg-space-5);
  font-size: 13px;
}
.alert__title { font-weight: 600; margin-bottom: 2px; }
.alert--info    { color: var(--hg-info-text); background: var(--hg-info-surface);
                  border-color: var(--hg-info-border); }
.alert--success { color: var(--hg-success-text); background: var(--hg-success-surface);
                  border-color: var(--hg-success-border); }
.alert--warning { color: var(--hg-warning-text); background: var(--hg-warning-surface);
                  border-color: var(--hg-warning-border); }
.alert--danger, .alert--error {
  color: var(--hg-danger-text); background: var(--hg-danger-surface);
  border-color: var(--hg-danger-border);
}

/* ═══════════════════════════════════════════════════════════════════
   RISK VERDICT + REFERENCE RAIL
   ═══════════════════════════════════════════════════════════════════ */
.verdict { text-align: left; }
.verdict__row { display: flex; align-items: center; gap: var(--hg-space-5); }
.verdict__value {
  font-family: var(--hg-font-display); font-size: 52px; font-weight: 700;
  line-height: 1; letter-spacing: -0.022em;
}
.verdict--low  .verdict__value { color: var(--hg-risk-low-text); }
.verdict--borderline .verdict__value { color: var(--hg-risk-borderline-text); }
.verdict--intermediate .verdict__value { color: var(--hg-risk-intermediate-text); }
.verdict--high .verdict__value { color: var(--hg-risk-high-text); }
.verdict__action { color: var(--hg-text); margin-top: var(--hg-space-4); }

.rail { margin: var(--hg-space-5) 0 var(--hg-space-3); }
.rail__bands { display: flex; height: 12px; border-radius: 2px; overflow: hidden;
               border: 1px solid var(--hg-border); }
.rail__band { height: 100%; }
.rail__band--low { background: var(--hg-risk-low-rail); }
.rail__band--borderline { background: var(--hg-risk-borderline-rail); }
.rail__band--intermediate { background: var(--hg-risk-intermediate-rail); }
.rail__band--high { background: var(--hg-risk-high-rail); }
.rail__scale { position: relative; height: 16px; margin-top: 3px;
               font-size: 10.5px; color: var(--hg-text-subtle); }
.rail__marker { position: absolute; transform: translateX(-50%);
                font-weight: 600; color: var(--hg-text-heading); }
.rail__labels { display: flex; justify-content: space-between;
                font-size: 10.5px; color: var(--hg-text-subtle); }

/* ═══════════════════════════════════════════════════════════════════
   AUTH
   ═══════════════════════════════════════════════════════════════════ */
.auth { display: flex; min-height: 100vh; }

/* The brand side is now ARTWORK AND A LOGO, nothing else. The statement and the three
   trust markers that used to sit here were removed on request: they made the panel a
   second page to read before signing in, and the numbers they quoted are on the model
   performance page where a reader can act on them. */
.auth__brandside {
  flex: 0 0 46%; color: #fff;
  padding: clamp(32px, 4vw, 56px);
  display: flex; flex-direction: column; justify-content: flex-start;
  position: relative; overflow: hidden; isolation: isolate;
  /* Layered beneath the SVG: a warm crimson bloom top-right over a deep ink field.
     Two gradients rather than one flat colour because a single solid makes the
     artwork look pasted onto the panel instead of lit within it. */
  background:
    radial-gradient(120% 90% at 78% 8%, rgba(194,43,74,0.22) 0%, rgba(194,43,74,0) 55%),
    linear-gradient(158deg, #141B25 0%, var(--hg-text-heading) 46%, #080C11 100%);
}
.auth__brandside > * { position: relative; z-index: 1; }
.auth__backdrop { position: absolute; inset: 0; z-index: 0; pointer-events: none; }
.auth__backdrop svg { display: block; width: 100%; height: 100%; }
/* A vignette over the artwork, so the logo keeps its contrast wherever the
   composition crops to. Without it the ticks run right up under the wordmark on a
   short viewport. */
.auth__brandside::after {
  content: ""; position: absolute; inset: 0; z-index: 0; pointer-events: none;
  background: linear-gradient(180deg, rgba(8,12,17,0.72) 0%, rgba(8,12,17,0) 34%,
              rgba(8,12,17,0) 62%, rgba(8,12,17,0.55) 100%);
}
.auth__formside {
  flex: 1 1 auto; display: flex; align-items: center; justify-content: center;
  padding: 48px clamp(16px, 3vw, 32px);
}
.auth__card {
  width: 100%; max-width: 400px; padding: 40px;
  background: var(--hg-surface); border: 1px solid var(--hg-border);
  border-radius: var(--hg-radius-xl); box-shadow: var(--hg-shadow-e3);
}
/* `text-wrap: balance` earns its place here: "System administrator sign-in" wrapped
   after the hyphen, leaving a line ending "sign-" and a line reading "in". Balancing
   moves the break to the space. Browsers that do not support it ignore the declaration
   and wrap as before, so there is nothing to fall back to. */
.auth__card h1 { font-size: 26px; line-height: 1.2; margin: 0 0 6px;
                 text-wrap: balance; }
.auth__tabs { display: flex; gap: 4px; margin-bottom: var(--hg-space-6); }
.auth__tab {
  flex: 1; text-align: center; padding: 7px 12px; font-size: 13px;
  border: 1px solid var(--hg-border-control); border-radius: var(--hg-radius-md);
  color: var(--hg-text); text-decoration: none; background: var(--hg-surface);
}
.auth__tab--active { border-color: var(--hg-primary); color: var(--hg-primary);
                     background: var(--hg-primary-tint); font-weight: 600; }
.auth__hint { font-size: 12px; color: var(--hg-text-subtle); text-align: center;
              margin: var(--hg-space-5) 0 0; }

/* Who this account is for. Stated on the form rather than discovered after signing
   in: registration always creates a Doctor, and the sign-in doors each admit one role
   — a person at the wrong one should be able to see that before typing a password. */
.auth__role {
  display: flex; gap: 11px; align-items: flex-start;
  padding: 11px 13px; margin-bottom: var(--hg-space-5);
  border: 1px solid var(--hg-primary-border); border-radius: var(--hg-radius-lg);
  background: var(--hg-primary-tint);
}
.auth__role svg { flex: 0 0 auto; color: var(--hg-primary); margin-top: 1px; }
.auth__role strong { display: block; font-size: 12.5px; color: var(--hg-primary);
                     letter-spacing: 0.01em; }
.auth__role span { display: block; font-size: 11.5px; color: var(--hg-text-muted);
                   line-height: 1.5; margin-top: 2px; }

/* ── validation ──────────────────────────────────────────────────────────
   `:user-invalid`, NOT `:invalid`. `:invalid` matches an empty required field from
   the moment the page loads, so every field on the registration form would be
   outlined in red before the user has typed a character — an interface scolding
   somebody for not yet having done anything. `:user-invalid` waits until the field
   has been interacted with or the form submitted.

   There is no JavaScript in any of this: the Content-Security-Policy on this
   application is `script-src 'none'`, so constraint validation is the browser's own,
   backed by the identical checks in backend/web/auth.py. Client-side validation is a
   courtesy to the user; the server's is the one that decides. */
.field input:user-invalid,
.field select:user-invalid {
  border-color: var(--hg-danger-border);
  background: var(--hg-danger-surface);
}
.field input:user-invalid:focus,
.field select:user-invalid:focus {
  outline-color: var(--hg-danger-border);
}
.field input:user-invalid ~ .field__hint { color: var(--hg-danger-text); }
.field input:user-valid { border-color: var(--hg-border-control); }
.field__req { color: var(--hg-primary); margin-left: 2px; }

@media (max-width: 900px) {
  .auth { flex-direction: column; }
  /* A fixed height rather than content height: with the statement gone the panel
     would otherwise collapse to the logo alone and the artwork would never be seen
     on a phone, which is where most people will open a shared link. */
  .auth__brandside { flex: none; min-height: 210px; padding: 28px 24px; }
}

/* ═══════════════════════════════════════════════════════════════════
   MISC
   ═══════════════════════════════════════════════════════════════════ */
.muted { color: var(--hg-text-muted); }
.subtle { color: var(--hg-text-subtle); font-size: 12px; }
.row { display: flex; gap: var(--hg-space-4); align-items: center; flex-wrap: wrap; }
.row--end { justify-content: flex-end; }
.spacer { flex: 1 1 auto; }
.chart { width: 100%; height: auto; display: block; }
.danger-zone {
  border: 1px solid var(--hg-danger-border); border-left-width: 3px;
  border-radius: var(--hg-radius-md); padding: var(--hg-space-5);
  background: var(--hg-danger-surface);
}
.danger-zone__title {
  font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--hg-danger-text);
}
.flashes { margin-bottom: var(--hg-space-5); }
details.expander {
  border: 1px solid var(--hg-border); border-radius: var(--hg-radius-md);
  padding: var(--hg-space-4) var(--hg-space-5); margin-bottom: var(--hg-space-5);
  background: var(--hg-surface);
}
details.expander summary { cursor: pointer; font-weight: 500; color: var(--hg-primary); }
details.expander[open] summary { margin-bottom: var(--hg-space-4); }

@media print {
  .sidebar, .pagehead__art, .btn, .flashes { display: none !important; }
  body { background: #fff; }
  .content { padding: 0; max-width: none; }
  .panel { break-inside: avoid; }
}
"""


def build() -> str:
    css = f"@import url('{T.FONT_IMPORT}');\n{_root_vars()}\n{COMPONENTS}"
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(css)
    return css


if __name__ == "__main__":
    out = build()
    print(f"wrote {OUTPUT}  ({len(out.encode('utf-8')) / 1024:.1f} KB)")
