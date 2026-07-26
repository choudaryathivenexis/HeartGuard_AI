"""
Component library tests.

Components that render inside Streamlit are exercised through AppTest, so each one is
demonstrably renderable in isolation (§9 Phase 4: "every component demonstrable in
isolation"). Pure string-returning components are asserted directly.

The security assertions matter most. This redesign multiplies `unsafe_allow_html` call
sites, which multiplies the BUG-12 surface — so every component that accepts
user-controlled data is fed a live XSS payload and checked for neutralisation.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import components as C
from ui import tokens as T

FAILURES: list[str] = []
XSS = '<img src=x onerror="alert(1)">'
SQLI = "'; DROP TABLE users;--"
UNI = "Ω≈ç 患者 🫀"


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


def well_formed(html: str) -> bool:
    try:
        ET.fromstring(f"<root>{html}</root>")
        return True
    except ET.ParseError:
        return False


def neutralised(html: str) -> bool:
    """
    Is the XSS payload inert?

    The security property is that no TAG can form — i.e. the angle brackets were
    escaped. An earlier version of this helper also rejected the substring "onerror",
    which made every correctly-escaped component fail: html.escape() turns `<` into
    `&lt;` but leaves the word "onerror" as literal text, where it is harmless. This is
    the same mistake that twice broke the brand tests in Phase 1b — substring-matching
    markup instead of asserting the actual property.
    """
    return ("<img" not in html
            and "&lt;img" in html          # proof it arrived and WAS escaped
            and "onerror=\"" not in html)  # no live attribute, only escaped text


# ════════════════════════════════════════════════════════════════════════
print("=== string components: markup + escaping ===")
for name, html in [
    ("eyebrow", C.eyebrow(XSS)),
    ("chip", C.chip(XSS, "high")),
    ("identifier", C.identifier(XSS, XSS)),
    ("stat", C.stat(XSS, XSS, delta=XSS, hint=XSS)),
]:
    check(f"{name} is well-formed", well_formed(html), html[:100])
    check(f"{name} neutralises the XSS payload", neutralised(html), html[:120])
    check(f"{name} still renders the text content", "img src=x" in html)

for name, html in [("chip", C.chip(UNI, "low")), ("stat", C.stat(UNI, UNI))]:
    check(f"{name} preserves unicode", "患者" in html)
for name, html in [("chip", C.chip(SQLI)), ("identifier", C.identifier(SQLI))]:
    check(f"{name} handles SQL-ish input as plain text", well_formed(html))

check("chip with an unknown icon degrades silently",
      well_formed(C.chip("x", "low", icon="nonexistent")))
check("chip with a real icon embeds SVG", "<svg" in C.chip("x", "low", icon="check"))

# ════════════════════════════════════════════════════════════════════════
print("\n=== the treatment rule (§3.3): clinical state is never a solid fill ===")
# Low risk and the primary share the Verdigris family. They are separated by TREATMENT,
# so a clinical chip must be a tinted surface with dark text — never a solid fill that
# could be mistaken for a button.
for band in T.RISK_ORDER:
    html = C.chip(band.title(), band)
    check(f"chip '{band}' uses its tinted-surface class",
          f"hg-chip--{band}" in html)
    check(f"chip '{band}' carries no inline solid fill",
          "background:" not in html, html)
check("chip always carries a TEXT label, never colour alone",
      "Low" in C.chip("Low", "low"))

# ════════════════════════════════════════════════════════════════════════
print("\n=== static_table ===")
import io
import contextlib


class _Capture:
    """Collect st.markdown output without a Streamlit runtime."""

    def __init__(self):
        self.out = []

    def markdown(self, body, **kw):
        self.out.append(body)

    def dataframe(self, *a, **kw):
        self.out.append("<dataframe/>")

    def container(self, key=None):
        return contextlib.nullcontext()

    def __getattr__(self, _):
        return lambda *a, **k: None

    @property
    def html(self):
        return "".join(self.out)


cap = _Capture()
C.st = cap                     # component module renders through this shim
C.static_table(["Model", XSS], [["RF", XSS], ["XGB", "0.8000"]],
               highlight=0, align_right={1})
h = cap.html
check("static_table is well-formed", well_formed(h), h[:140])
check("static_table escapes header cells", "<img" not in h)
check("static_table escapes body cells", neutralised(h))
check("static_table right-aligns numeric columns", "hg-tbl--num" in h)
check("static_table highlights the requested row", "hg-tbl__row--hl" in h)
check("wide tables scroll themselves, not the page", "hg-tbl-wrap" in h)

# ════════════════════════════════════════════════════════════════════════
print("\n=== alert severities ===")
for sev in ["info", "success", "warning", "danger", "extrapolation"]:
    cap = _Capture(); C.st = cap
    C.alert(sev, XSS, body=XSS, items=[XSS, "second"])
    h = cap.html
    check(f"alert '{sev}' is well-formed", well_formed(h), h[:120])
    check(f"alert '{sev}' escapes title, body and items", neutralised(h))
    check(f"alert '{sev}' uses its own class", f"hg-alert--{sev}" in h)
    check(f"alert '{sev}' announces itself to assistive tech", 'role="alert"' in h)

cap = _Capture(); C.st = cap
C.alert("nonsense-severity", "t")
check("unknown severity falls back to info rather than rendering unstyled",
      "hg-alert--info" in cap.html)

# Extrapolation must take NO risk colour — it is a validity failure, not a severity.
cap = _Capture(); C.st = cap
C.alert("extrapolation", "Outside model applicability")
h = cap.html
check("extrapolation alert carries no risk-band colour class",
      not any(f"--{b}" in h for b in T.RISK_ORDER), h[:160])
# The hazard stripe is applied in CSS, so assert it in the stylesheet rather than
# looking for it in markup that only carries a class name.
from ui import styles as S
_css = S.stylesheet.__wrapped__()
check("extrapolation alert is styled from the hazard tokens, not a seventh hue",
      "hg-alert--extrapolation" in _css and "--hg-hazard-surface" in _css)
check("hazard stripe uses only Ink and Amber",
      T.HAZARD["stripe_a"] == T.INK and T.HAZARD["stripe_b"] == T.AMBER)

# ════════════════════════════════════════════════════════════════════════
print("\n=== risk_verdict — the clinical hero ===")
BANDS = (0.2293, 0.3481, 0.6999)
for band, prob, label in [("low", 0.12, "LOW RISK"),
                          ("borderline", 0.30, "BORDERLINE"),
                          ("intermediate", 0.52, "INTERMEDIATE RISK"),
                          ("high", 0.88, "HIGH RISK")]:
    cap = _Capture(); C.st = cap
    C.risk_verdict(prob, label, band, BANDS, 0.3481,
                   "Above the action threshold. Further testing indicated.",
                   animate=False)
    h = cap.html
    check(f"verdict '{band}' is well-formed", well_formed(h), h[:140])
    check(f"verdict '{band}' shows the probability to 1dp",
          f"{prob * 100:.1f}%" in h, h[:200])
    check(f"verdict '{band}' embeds the Reference Rail", "hg-rail" in h)
    check(f"verdict '{band}' colours the figure with its band rail colour",
          T.RISK[band]["rail"] in h)

cap = _Capture(); C.st = cap
C.risk_verdict(0.34, "BORDERLINE", "borderline", BANDS, 0.3481, "act", animate=False)
h = cap.html
check("verdict eyebrow says SCREENING, not 'Diagnosis'",
      "Screening result" in h and "iagnos" not in h)
check("band chip sits BESIDE the figure, not below",
      h.index("hg-verdict__prob") < h.index("hg-verdict__band"))
banned = ["healthy", "negative", "you have", "clear"]
check("verdict copy avoids forbidden clinical vocabulary",
      not any(b in h.lower() for b in banned))

cap = _Capture(); C.st = cap
C.risk_verdict(0.9, "HIGH RISK", "high", BANDS, 0.3481, "act",
               extrapolated=True, animate=False)
h = cap.html
check("extrapolated verdict is tagged", "extrapolated" in h.lower())
check("extrapolated verdict takes the hazard border class",
      "hg-verdict--extrap" in h)

cap = _Capture(); C.st = cap
C.risk_verdict(0.34, XSS, "borderline", BANDS, 0.3481, XSS, animate=False)
check("verdict escapes band label and action text", neutralised(cap.html))

# ════════════════════════════════════════════════════════════════════════
print("\n=== operating_point ===")
cap = _Capture(); C.st = cap
C.operating_point(0.3712, 0.8365, 0.3752, 0.6104, 0.6553,
                  source="Derived for ages 55–59 from out-of-fold predictions.")
h = cap.html
check("well-formed", well_formed(h), h[:140])
check("threshold shown to 3dp", "0.371" in h)
check("sensitivity shown to 3dp", "0.837" in h or "0.836" in h)
check("states WHY this threshold is in force", "out-of-fold" in h)
cap = _Capture(); C.st = cap
C.operating_point(0.35, None, None, source=XSS)
check("missing metrics render as em dash rather than crashing",
      "—" in cap.html)
check("source text is escaped", "<img" not in cap.html)

# ════════════════════════════════════════════════════════════════════════
print("\n=== reliability_panel ===")
for auc_v, expect in [(0.8382, "Strong"), (0.7854, "Moderate"), (0.7298, "Limited")]:
    cap = _Capture(); C.st = cap
    C.reliability_panel(auc_v, auc_v - 0.02, auc_v + 0.02, -0.005, 3167,
                        band_label="55–59", overall=0.8000)
    h = cap.html
    check(f"AUC {auc_v} rated '{expect}' as TEXT, not colour alone", expect in h)
    check(f"AUC {auc_v} panel embeds a CI rail", "hg-rail__ci" in h)
    check(f"AUC {auc_v} shows the calibration gap signed", "-0.005" in h)
    check(f"AUC {auc_v} states the holdout n", "3,167" in h)

cap = _Capture(); C.st = cap
C.reliability_panel(0.73, 0.71, 0.75, -0.01, 3085, band_label="60 and over",
                    caution="Weight clinical judgement more heavily than the score.")
check("low-reliability caution is rendered as a warning alert",
      "hg-alert--warning" in cap.html and "clinical judgement" in cap.html)
cap = _Capture(); C.st = cap
C.reliability_panel(None, None, None, None, None)
check("panel with no data degrades without crashing", well_formed(cap.html))

# ════════════════════════════════════════════════════════════════════════
print("\n=== stat_grid & empty_state ===")
cap = _Capture(); C.st = cap
C.stat_grid([{"label": "Total scans", "value": "13,729"},
             {"label": "High risk", "value": "74", "tone": "high"},
             {"label": "AUC", "value": "0.8000", "hint": "[0.7925–0.8072]"},
             {"label": "Sensitivity", "value": "0.850"}], cols=4)
h = cap.html
check("stat_grid is well-formed", well_formed(h))
check("stat_grid sets its column count from the argument", "--hg-stat-cols:4" in h)
check("stat_grid renders one cell per stat", h.count("hg-stat__label") == 4)
check("stat_grid uses hairline gaps, not shadows",
      "box-shadow" not in h and "hg-stat-grid" in h)

cap = _Capture(); C.st = cap
C.empty_state(XSS, XSS, action=XSS)
h = cap.html
check("empty_state is well-formed", well_formed(h))
check("empty_state escapes all three fields", "<img" not in h)
check("empty_state uses the Caliper Mark, not photography (§3.9)",
      "<svg" in h and "<img" not in h)

# ════════════════════════════════════════════════════════════════════════
print("\n=== no stray hex: every colour traces to a token ===")
import re

cap = _Capture(); C.st = cap
C.risk_verdict(0.34, "BORDERLINE", "borderline", BANDS, 0.3481, "act", animate=False)
C.operating_point(0.35, 0.85, 0.55, 0.65, 0.72, source="x")
C.reliability_panel(0.73, 0.71, 0.75, -0.01, 100, band_label="b", overall=0.8)
C.alert("extrapolation", "t", "b", ["i"])
C.stat_grid([{"label": "a", "value": "1"}])
C.static_table(["a"], [["1"]])
all_html = cap.html + C.chip("x", "high") + C.identifier("v", "l")

allowed = set()
for d in (T.CSS, T.MPL, T.CSS_DARK):
    allowed |= {v.upper() for v in d.values() if v.startswith("#")}
for band in T.RISK_ORDER:
    allowed |= {v.upper() for v in T.RISK[band].values()}
allowed |= {T.HAZARD["stripe_a"].upper(), T.HAZARD["stripe_b"].upper()}
found = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}", all_html)}
check("no hex outside the token module", not (found - allowed), str(found - allowed))
check("components reference CSS custom properties", "var(--hg-" in all_html)

print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
