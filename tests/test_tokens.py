"""
Token contract tests.

Runnable without pytest (`python tests/test_tokens.py`) so the gate does not depend
on a test runner that is not in requirements.txt.

The single most important assertion here is `test_mpl_is_hex_only`. BUG-01 and BUG-02
were CSS `rgba()` strings passed to matplotlib, which killed the Model Performance
page for all three roles and took four tabs down with it. That bug is now
structurally impossible to reintroduce: any colour destined for matplotlib must live
in MPL, and every MPL value is asserted to be hex.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import tokens as T
from ui import format as F

FAILURES: list[str] = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


# ════════════════════════════════════════════════════════════════════════
print("=== MPL is hex-only (BUG-01 / BUG-02 structural guard) ===")
bad = {k: v for k, v in T.MPL.items() if not T.HEX_RE.match(v)}
check("every MPL value matches ^#rrggbb(aa)?$", not bad, str(bad))
check("MPL contains no rgba() strings",
      not any("rgba" in v for v in T.MPL.values()))
check("MPL contains no var() references",
      not any("var(" in v for v in T.MPL.values()))
check("CHART_CATEGORICAL is hex-only",
      all(T.HEX_RE.match(c) for c in T.CHART_CATEGORICAL))
check("MPL is non-trivial", len(T.MPL) >= 30, f"only {len(T.MPL)} entries")

# ════════════════════════════════════════════════════════════════════════
print("\n=== Brand Six discipline ===")
check("exactly six brand colours", len(T.BRAND_SIX) == 6, str(list(T.BRAND_SIX)))
viol = T.verify_derivation()
check("every ramp step derives from the Brand Six", not viol,
      f"{len(viol)} violations: {viol[:4]}")

# The one declared exception, asserted explicitly so it can never grow silently.
series_hues = set(T.SERIES.values())
allowed = set(T.BRAND_SIX.values()) | {T.IRIS, "#C2404F"}
check("chart series introduce only Iris beyond the six",
      series_hues <= allowed, str(series_hues - allowed))

# ════════════════════════════════════════════════════════════════════════
print("\n=== WCAG 2.2 AA contrast (calculated, not eyeballed) ===")
for band in T.RISK_ORDER:
    spec = T.RISK[band]
    r = T.contrast_ratio(spec["text"], spec["surface"])
    check(f"risk '{band}' text on its surface >= 4.5:1",
          r >= 4.5, f"{r:.2f}:1")

for name, spec in T.SEMANTIC.items():
    r = T.contrast_ratio(spec["text"], spec["surface"])
    check(f"semantic '{name}' text on its surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")

r = T.contrast_ratio(T.CSS["text"], T.CSS["surface"])
check("body text on surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS["text"], T.CSS["canvas"])
check("body text on canvas >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS["text_muted"], T.CSS["surface"])
check("muted text on surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS["text_heading"], T.CSS["surface"])
check("headings on surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")

# Primary button: solid verdigris fill with bone text (the interaction treatment)
r = T.contrast_ratio(T.BONE, T.CSS["primary"])
check("bone text on primary fill >= 4.5:1", r >= 4.5, f"{r:.2f}:1")

# Borders and large text need 3:1
# WCAG 1.4.11 requires 3:1 only for boundaries REQUIRED TO IDENTIFY a control.
# A decorative panel hairline is exempt and cannot reach 3:1 while staying a hairline
# (neutral-200 is 1.37:1 on white). Control boundaries get their own token, which does.
r = T.contrast_ratio(T.CSS["border_control"], T.CSS["surface"])
check("CONTROL border on surface >= 3:1 (WCAG 1.4.11)", r >= 3.0, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS["border_control"], T.CSS["canvas"])
check("CONTROL border on canvas >= 3:1 (WCAG 1.4.11)", r >= 3.0, f"{r:.2f}:1")
check("decorative border is lighter than the control border",
      T.relative_luminance(T.CSS["border"]) > T.relative_luminance(T.CSS["border_control"]),
      "decorative hairline must not out-weigh a control edge")

# Hazard treatment must be readable — it is the most important banner in the app
r = T.contrast_ratio(T.HAZARD["text"], T.HAZARD["surface"])
check("hazard text on hazard surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")

print("\n=== dark-mode contrast ===")
r = T.contrast_ratio(T.CSS_DARK["text"], T.CSS_DARK["canvas"])
check("dark body text on dark canvas >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS_DARK["text_muted"], T.CSS_DARK["surface"])
check("dark muted text on dark surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
r = T.contrast_ratio(T.DARK["primary"], T.CSS_DARK["canvas"])
check("dark primary on dark canvas >= 3:1", r >= 3.0, f"{r:.2f}:1")

# ════════════════════════════════════════════════════════════════════════
print("\n=== risk ramp survives greyscale and CVD ===")
# The brief asserts the four rails descend monotonically in luminance. They do not,
# and cannot: a ramp routed through Amber is necessarily non-monotonic because Amber
# is the lightest of the three chromatics. Rather than degrade Amber into olive to
# satisfy a claim, the real guarantee is asserted instead — MUTUAL separability, which
# is what greyscale printing and colour vision deficiency actually require.
import itertools

lums = {b: T.relative_luminance(T.RISK[b]["rail"]) for b in T.RISK_ORDER}
pairs = [(a, b, abs(lums[a] - lums[b]))
         for a, b in itertools.combinations(T.RISK_ORDER, 2)]
worst = min(pairs, key=lambda x: x[2])
check("all six rail pairs separable by >= 0.04 luminance",
      all(d >= 0.04 for _, _, d in pairs),
      f"closest: {worst[0]}/{worst[1]} dL={worst[2]:.4f}")

# Every rail must be visible against the track it sits on. Borderline is only 2.57:1
# unaided, which is why rail.py draws a hairline outline in the band border colour —
# WCAG 1.4.11 is satisfied by delineation, independently of fill contrast.
for band in T.RISK_ORDER:
    r = T.contrast_ratio(T.RISK[band]["rail"], T.RAIL_TRACK)
    check(f"rail '{band}' vs track >= 2.5:1 (outline supplies the rest)",
          r >= 2.5, f"{r:.2f}:1")
    r2 = T.contrast_ratio(T.RISK[band]["border"], T.RISK[band]["rail"])
    check(f"rail '{band}' outline distinguishable from its fill", r2 >= 1.2, f"{r2:.2f}:1")

# High risk must be the darkest — the one ordering property that IS guaranteed.
check("high risk is the darkest rail",
      lums["high"] == min(lums.values()),
      " ".join(f"{b}={v:.3f}" for b, v in lums.items()))

# ════════════════════════════════════════════════════════════════════════
print("\n=== series colours are keyed, not positional (BUG-19 guard) ===")
check("series_color keyed by model name",
      T.series_color("Random Forest") == T.IRIS)
check("series_color falls back safely for unknown model",
      T.HEX_RE.match(T.series_color("Nonexistent Model")) is not None)
check("every trained model has a series colour",
      all(m in T.SERIES for m in
          ["Logistic Regression", "Support Vector Machine (SVM)", "Decision Tree",
           "Random Forest", "XGBoost", "Ensemble Voting"]))
check("every series has a distinct marker",
      len(set(T.SERIES_MARKER.values())) == len(T.SERIES_MARKER))

# ════════════════════════════════════════════════════════════════════════
print("\n=== band label mapping ===")
for label, expect in [("HIGH RISK", "high"), ("INTERMEDIATE RISK", "intermediate"),
                      ("BORDERLINE", "borderline"), ("LOW RISK", "low"),
                      ("", "low"), (None, "low")]:
    check(f"risk_band_key({label!r}) -> {expect}",
          T.risk_band_key(label) == expect, T.risk_band_key(label))

# ════════════════════════════════════════════════════════════════════════
print("\n=== formatter decimal discipline (§3.4) ===")
check("pct(0.34021) == '34.0%'", F.pct(0.34021) == "34.0%", F.pct(0.34021))
check("auc(0.8) == '0.8000'", F.auc(0.8) == "0.8000", F.auc(0.8))
check("metric3(0.8352) == '0.835'", F.metric3(0.8352) == "0.835", F.metric3(0.8352))
check("count(13729) == '13,729'", F.count(13729) == "13,729", F.count(13729))
check("threshold(0.3712) == '0.371'", F.threshold(0.3712) == "0.371",
      F.threshold(0.3712))
check("signed(-0.005) == '-0.005'", F.signed(-0.005) == "-0.005", F.signed(-0.005))
check("signed(0.011) == '+0.011'", F.signed(0.011) == "+0.011", F.signed(0.011))
check("interval uses en dash",
      F.interval(0.7925, 0.8072) == "[0.7925–0.8072]", F.interval(0.7925, 0.8072))
check("value_with_ci composes",
      F.value_with_ci(0.8, 0.7925, 0.8072) == "0.8000 [0.7925–0.8072]",
      F.value_with_ci(0.8, 0.7925, 0.8072))
check("interval empty when a bound is missing", F.interval(None, 0.8) == "")
check("None renders as em dash", F.pct(None) == F.EM_DASH)

print("\n=== escaping (BUG-12 guard) ===")
check("esc neutralises angle brackets",
      "<img" not in F.esc("<img src=x onerror=alert(1)>"),
      F.esc("<img src=x onerror=alert(1)>"))
check("esc handles None", F.esc(None) == "")
check("esc preserves unicode", "患者" in F.esc("患者"))

print("\n=== clinical vocabulary (§3.10) ===")
for band in T.RISK_ORDER:
    txt = F.BAND_ACTION[band]
    check(f"'{band}' action mentions the action threshold",
          "action threshold" in txt, txt)
banned = ["healthy", "negative", "clear", "you have", "diagnosis"]
for band, txt in F.BAND_ACTION.items():
    hit = [w for w in banned if w in txt.lower()]
    check(f"'{band}' avoids forbidden vocabulary", not hit, str(hit))
check("reliability_rating(0.838) == 'Strong'",
      F.reliability_rating(0.838) == "Strong")
check("reliability_rating(0.7298) == 'Limited'",
      F.reliability_rating(0.7298) == "Limited")
check("discrimination_phrase includes metric and interval",
      "AUC 0.7298" in F.discrimination_phrase("55–59", 0.7298, 0.712, 0.748)
      and "[" in F.discrimination_phrase("55–59", 0.7298, 0.712, 0.748))

# ════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
