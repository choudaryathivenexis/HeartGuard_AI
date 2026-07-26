"""
Reference Rail geometry tests.

The rail's guarantees are arithmetic, so they are asserted as arithmetic rather than
eyeballed in a browser. The one that matters most:

    an out-of-range marker must land INSIDE the hatched span

If the marker were clamped to the rail end it would sit exactly on the envelope
boundary and look identical to a value that is merely at the limit — hiding the
extrapolation, which is the single thing this product exists to disclose (BUG-23).
"""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import rail as R
from ui import tokens as T

FAILURES: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


def well_formed(html: str) -> bool:
    """Rail output is a div tree; wrap and parse to confirm balanced markup."""
    try:
        ET.fromstring(f"<root>{html}</root>")
        return True
    except ET.ParseError:
        return False


def spans(html: str, cls: str) -> list[tuple[float, float]]:
    """Extract (left%, width%) for every element carrying `cls`."""
    out = []
    for m in re.finditer(r'class="([^"]*)"\s+style="([^"]*)"', html):
        if cls not in m.group(1):
            continue
        st = m.group(2)
        left = re.search(r"left:([\d.]+)%", st)
        width = re.search(r"width:([\d.]+)%", st)
        out.append((float(left.group(1)) if left else 0.0,
                    float(width.group(1)) if width else 0.0))
    return out


def marker_pos(html: str) -> float:
    m = re.search(r'class="hg-rail__marker[^"]*"\s+style="left:([\d.]+)%', html)
    return float(m.group(1)) if m else -1.0


# ════════════════════════════════════════════════════════════════════════
print("=== RailGeometry ===")
g = R.RailGeometry(0.0, 1.0)
check("pos maps domain start to 0%", g.pos(0.0) == 0.0)
check("pos maps domain end to 100%", g.pos(1.0) == 100.0)
check("pos is linear at the midpoint", abs(g.pos(0.5) - 50.0) < 1e-9)
check("pos clamps below the domain", g.pos(-1.0) == 0.0)
check("pos clamps above the domain", g.pos(2.0) == 100.0)
check("raw_pos does NOT clamp (used to detect out-of-domain)",
      g.raw_pos(2.0) == 200.0 and g.raw_pos(-1.0) == -100.0)
check("width is order-independent",
      abs(g.width(0.2, 0.8) - g.width(0.8, 0.2)) < 1e-9)
gz = R.RailGeometry(5.0, 5.0)
check("zero-span domain does not divide by zero",
      gz.span == 1.0 and 0 <= gz.pos(5.0) <= 100)

# ════════════════════════════════════════════════════════════════════════
print("\n=== envelope geometry: in range ===")
e = R.envelope_geometry(52, 30, 65, 40, 64)
check("in-range value is not extrapolated", not e.extrapolated)
check("in-range value inside p1-p99 is not sparse", not e.sparse)
check("envelope span is inset from both ends",
      e.env_left > 0.1 and e.env_left + e.env_width < 99.9,
      f"left={e.env_left:.2f} width={e.env_width:.2f}")
check("two invalid spans exist (the padding either side)",
      len(e.invalid_spans) == 2, str(e.invalid_spans))
check("marker sits inside the envelope",
      e.env_left < e.value_pos < e.env_left + e.env_width,
      f"value={e.value_pos:.2f} env=[{e.env_left:.2f},{e.env_left + e.env_width:.2f}]")

print("\n=== envelope geometry: sparse support ===")
s = R.envelope_geometry(64.5, 30, 65, 40, 64)
check("beyond p99 but inside min/max is SPARSE, not extrapolated",
      s.sparse and not s.extrapolated)

print("\n=== envelope geometry: extrapolated — the BUG-23 case ===")
for label, value, lo, hi in [("age 82 vs 30-65", 82, 30, 65),
                             ("age 19 vs 30-65", 19, 30, 65),
                             ("systolic 245 vs 60-240", 245, 60, 240)]:
    x = R.envelope_geometry(value, lo, hi)
    check(f"{label}: flagged as extrapolated", x.extrapolated)
    # The critical assertion: the marker must be in a hatched region, not pinned
    # to the envelope edge.
    in_hatch = any(left - 0.01 <= x.value_pos <= left + width + 0.01
                   for left, width in x.invalid_spans)
    check(f"{label}: marker lands INSIDE a hatched span", in_hatch,
          f"marker={x.value_pos:.2f} hatches={[(round(a,2),round(b,2)) for a,b in x.invalid_spans]}")
    check(f"{label}: marker is NOT clamped to the envelope edge",
          abs(x.value_pos - x.env_left) > 0.5
          and abs(x.value_pos - (x.env_left + x.env_width)) > 0.5,
          "a clamped marker would be indistinguishable from a value at the limit")
    check(f"{label}: domain grew to contain the value",
          x.geom.lo <= value <= x.geom.hi,
          f"domain=[{x.geom.lo:.1f},{x.geom.hi:.1f}] value={value}")

# ════════════════════════════════════════════════════════════════════════
print("\n=== risk_rail ===")
BANDS = (0.2293, 0.3481, 0.6999)
html = R.risk_rail(0.34, BANDS, 0.3481, "borderline")
check("well-formed markup", well_formed(html), html[:120])
check("carries an accessible description", 'role="img"' in html and "aria-label" in html)
check("notch is rendered", "hg-rail__notch" in html)
check("notch is ABOVE the track (declared before it in document order)",
      html.index("hg-rail__notch") < html.index("hg-rail__track"))
check("band strip present with four labels",
      all(b.upper() in html for b in T.RISK_ORDER))
check("three boundary hairlines", html.count("hg-rail__tick") == 3,
      str(html.count("hg-rail__tick")))
check("fill uses the ACTIVE band colour",
      T.RISK["borderline"]["rail"] in html)
check("endpoints are labelled", ">0%<" in html and ">100%<" in html)
check("fill width matches the probability",
      abs(spans(html, "hg-rail__fill")[0][1] - 34.0) < 0.01,
      str(spans(html, "hg-rail__fill")))

# The notch must never take a risk colour — it is a decision boundary, not a reading.
notch_html = html[html.index("hg-rail__notch"):html.index("hg-rail__strip")]
check("notch carries no risk colour",
      not any(T.RISK[b]["rail"] in notch_html for b in T.RISK_ORDER))

for band, prob in [("low", 0.10), ("borderline", 0.30), ("intermediate", 0.50),
                   ("high", 0.85)]:
    h = R.risk_rail(prob, BANDS, 0.3481, band)
    check(f"band '{band}' renders and colours its fill", T.RISK[band]["rail"] in h)

print("\n=== risk_rail: band zones are NOT filled ===")
# The fill belongs to the measured value only; filling the zones would compete with it.
h = R.risk_rail(0.34, BANDS, 0.3481, "borderline")
strip = h[h.index("hg-rail__strip"):h.index("hg-rail__track")]
check("band strip contains no background fill",
      "background:" not in strip, strip[:160])

# ════════════════════════════════════════════════════════════════════════
print("\n=== envelope_rail markup ===")
h = R.envelope_rail(82, 30, 65, 40, 64, label="Age", unit="years",
                    fmt=lambda v: f"{v:.0f}")
check("well-formed markup", well_formed(h))
check("hatch rendered for the invalid span", "hg-rail__hatch" in h)
check("hazard stripe used for the hatch",
      T.HAZARD["stripe_b"] in R.HATCH_CSS and T.HAZARD["stripe_a"] in R.HATCH_CSS)
check("state badge shown when extrapolating", "outside supported range" in h)
check("aria states the extrapolation explicitly",
      "extrapolation" in h.lower())
check("endpoints labelled with the envelope bounds", ">30<" in h and ">65<" in h)

h_ok = R.envelope_rail(52, 30, 65, 40, 64, label="Age", fmt=lambda v: f"{v:.0f}")
check("in-range rail shows no state badge", "hg-rail__state" not in h_ok)
check("in-range rail still hatches the padding either side",
      h_ok.count("hg-rail__hatch") == 2, str(h_ok.count("hg-rail__hatch")))
check("p1-p99 dense band rendered", "hg-rail__dense" in h_ok)

# ════════════════════════════════════════════════════════════════════════
print("\n=== ci_rail ===")
h = R.ci_rail(0.8000, 0.7925, 0.8072, domain=(0.55, 0.90),
              reference=0.7912, reference_label="clinical LR", label="Random Forest")
check("well-formed markup", well_formed(h))
check("interval span rendered", "hg-rail__ci" in h)
check("reference line rendered", "hg-rail__ref" in h)
check("interval text uses an en dash", "–" in h)
check("value and interval both present", "0.8000" in h and "0.7925" in h)
check("aria mentions the confidence interval", "confidence interval" in h)
h_noci = R.ci_rail(0.80, None, None, label="No CI")
check("missing interval degrades without crashing",
      well_formed(h_noci) and "hg-rail__ci\"" not in h_noci)

# ════════════════════════════════════════════════════════════════════════
print("\n=== sweep_rail ===")
CAND = {"rule_out": 0.229, "recommended": 0.348, "rule_in": 0.700,
        "youden_j": 0.452, "f2_optimal": 0.301, "legacy_half": 0.500}
h = R.sweep_rail(0.348, CAND)
check("well-formed markup", well_formed(h))
check("one tick per candidate", h.count("hg-rail__cand") == len(CAND) + 1,
      f"{h.count('hg-rail__cand')} vs {len(CAND)} (+1 for the selected modifier)")
check("selected candidate is emphasised", "hg-rail__cand--sel" in h)
check("notch marks the point in force", "in force" in h)
check("candidate names appear as tooltips", "legacy_half" in h)
h_none = R.sweep_rail(0.35, {"a": None, "b": 0.4})
check("None candidate is skipped rather than crashing", well_formed(h_none))

# ════════════════════════════════════════════════════════════════════════
print("\n=== subgroup_rails ===")
LEVELS = [
    {"level": "Under 45", "n": 2015, "auc": 0.8382, "auc_ci_low": 0.819, "auc_ci_high": 0.859},
    {"level": "45-54", "n": 5462, "auc": 0.7854, "auc_ci_low": 0.774, "auc_ci_high": 0.798},
    {"level": "55-59", "n": 3167, "auc": 0.7298, "auc_ci_low": 0.712, "auc_ci_high": 0.748},
    {"level": "60 and over", "n": 3085, "auc": 0.7330, "auc_ci_low": 0.713, "auc_ci_high": 0.751},
]
h = R.subgroup_rails(LEVELS, overall=0.8000)
check("well-formed markup", well_formed(h))
check("one row per stratum", h.count("hg-rail-row") == len(LEVELS))
check("every stratum labelled with its n", all(f'n={lv["n"]:,}' in h for lv in LEVELS))
# Count the exact class: each reference also emits hg-rail__ref-label, so a
# substring count double-counts.
check("overall reference appears on each row",
      h.count(chr(39)+chr(39)+chr(39)) == 0 and h.count("class=\"hg-rail__ref\"") == len(LEVELS),
      str(h.count("class=\"hg-rail__ref\"")))
# Strong strata get the low-risk rail colour, weak ones the high-risk colour, so
# reliability is legible without reading the numbers.
check("strong stratum (0.838) coloured as strong",
      T.RISK["low"]["rail"] in h)
check("weak stratum (0.730) coloured as weak",
      T.RISK["high"]["rail"] in h)
h_empty = R.subgroup_rails([], overall=0.8)
check("empty stratum list renders nothing rather than crashing",
      well_formed(h_empty) and "hg-rail-row" not in h_empty)

# ════════════════════════════════════════════════════════════════════════
print("\n=== no hex literals leak into rail markup ===")
# Every colour must come from tokens. A stray literal here would defeat the single
# source of truth the whole ui/ package exists to enforce.
all_html = "".join([
    R.risk_rail(0.34, BANDS, 0.348, "borderline"),
    R.envelope_rail(82, 30, 65, 40, 64, label="Age"),
    R.ci_rail(0.8, 0.79, 0.81, label="RF", reference=0.79),
    R.sweep_rail(0.348, CAND),
])
token_hexes = set()
for d in (T.CSS, T.MPL, T.CSS_DARK):
    token_hexes |= {v.upper() for v in d.values() if v.startswith("#")}
for band in T.RISK_ORDER:
    token_hexes |= {v.upper() for v in T.RISK[band].values()}
token_hexes |= {T.HAZARD["stripe_a"].upper(), T.HAZARD["stripe_b"].upper(),
                T.INK.upper(), T.AMBER.upper()}
found = {m.upper() for m in re.findall(r"#[0-9A-Fa-f]{6}", all_html)}
stray = found - token_hexes
check("every hex in rail markup comes from tokens", not stray, str(stray))
check("rail markup uses CSS custom properties", "var(--hg-" in all_html)

print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
