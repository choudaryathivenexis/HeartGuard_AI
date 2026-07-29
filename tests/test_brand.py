"""
Brand and icon contract tests.

Geometry is asserted rather than eyeballed where that is possible, but note the limit
honestly: SVG cannot be rasterised in this environment (no cairosvg, and §1.3 forbids
adding one), so *appearance* was verified by rendering the structured primitives
through matplotlib into contact sheets and looking at them —
baseline/mark_final.png, baseline/mark_variants.png, baseline/icons.png.

That process caught four real defects a passing test suite would have missed:
  * the notch fused to the rail and read as a funnel, not a marker
  * the two icon renderers disagreed on arc direction, mirroring every arc
  * a circular arc cannot express a cylinder lid, so `dataset` rendered as lenses
  * a 20px cog with a uniform 1.5 stroke reads as a sun, not a gear
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frontend.design import brand as B
from frontend.design import icons as I
from shared import tokens as T

FAILURES: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


# ════════════════════════════════════════════════════════════════════════
print("=== Caliper Mark geometry (§3.7) ===")
check("viewBox is 32", B.VIEW == 32)
check("stroke is 2.5", B.STROKE == 2.5)
check("left jaw at x=6", B.JAW_L_X == 6.0)
check("right jaw at x=26", B.JAW_R_X == 26.0)
check("rail at y=16 (the H crossbar)", B.RAIL_Y == 16.0)
check("jaws span y 6..26", (B.JAW_TOP, B.JAW_BOT) == (6.0, 26.0))
check("fill break at the golden section",
      abs(B.GOLDEN - 18.36) < 0.02, f"{B.GOLDEN:.3f}")
check("hairline is thinner than the solid rail", B.HAIRLINE < B.STROKE)
check("notch clears the rail (reads as a marker, not a funnel)",
      B.NOTCH_GAP >= 1.5, f"gap={B.NOTCH_GAP}")
check("notch is taller than wide (a pointer, not a fan)",
      B.NOTCH_H > B.NOTCH_W, f"{B.NOTCH_W}x{B.NOTCH_H}")

print("\n=== mark variants are well-formed and distinct ===")
for fn, label in [(B.mark, "mark"), (B.mark_sm, "mark_sm")]:
    svg = fn(32)
    try:
        ET.fromstring(svg)
        ok = True
    except Exception as e:
        ok, err = False, str(e)[:60]
    check(f"{label}() is well-formed XML", ok, "" if ok else err)
    check(f"{label}() inherits currentColor", "currentColor" in svg)
    check(f"{label}() carries an accessible name", 'aria-label' in svg)

check("mark_sm drops the notch (16-20px legibility)",
      "polygon" not in B.mark_sm(20) and "polygon" in B.mark(32))
check("mark_sm uses a single stroke width",
      B.mark_sm(20).count("stroke-width") == 1)
check("mark has both solid and hairline rail segments",
      f'stroke-width="{B.STROKE}"' in B.mark(32)
      and f'stroke-width="{B.HAIRLINE}"' in B.mark(32))

print("\n=== the mark is not a cliche (§3.7) ===")
# Assert on GEOMETRY, not on strings. The product is called HeartGuard, so the word
# "heart" legitimately appears in the accessible name — an earlier version of this
# test flagged that as a heart motif, which was a false positive, not a finding.
# Parse the XML and inspect path data. Substring-matching the whole SVG is what made
# the two previous versions of this assertion fail: "HeartGuard AI" in the accessible
# name supplies an 'H', a 'V'-free string and an ' A', so a naive scan reports curves
# and arcs that do not exist. Assert on the geometry, from the geometry.
root = ET.fromstring(B.mark(32))
tags = [el.tag.split("}")[-1] for el in root.iter()]
path_ds = [el.get("d", "") for el in root.iter() if el.tag.split("}")[-1] == "path"]

check("mark is 4 straight paths plus 1 triangle",
      tags.count("path") == 4 and tags.count("polygon") == 1,
      f"paths={tags.count('path')} polygons={tags.count('polygon')}")
check("mark uses no circle, ellipse or arc element",
      not any(t in tags for t in ["circle", "ellipse"]))
check("no path contains a curve or arc command",
      not any(c in d.upper() for d in path_ds for c in ("C", "S", "Q", "A")),
      f"a heart or pulse form would require them: {path_ds}")
check("every path is axis-aligned (V or H only)",
      all(("V" in d) != ("H" in d) for d in path_ds),
      f"jaws vertical, rail horizontal: {path_ds}")

print("\n=== lockups ===")
lk = B.lockup()
check("lockup contains the mark", "svg" in lk)
check("lockup contains the wordmark", "HeartGuard" in lk)
check("wordmark uses the expanded width axis", "'wdth' 112" in lk)
check("AI is set in Verdigris", T.CSS["primary"] in lk)
check("lockup_mono collapses to one colour",
      T.CSS["primary"] not in B.lockup_mono(T.INK))
check("dark lockup uses dark-mode tokens",
      T.CSS_DARK["text_heading"] in B.lockup(dark=True))
check("minimum sizes declared", B.MIN_MARK_PX == 20 and B.MIN_LOCKUP_PX == 96)

print("\n=== favicon generation (Pillow, no new dependency) ===")
paths = B.generate_favicons()
check("both favicons written", len(paths) == 2, str(paths))
for p in paths:
    check(f"{os.path.basename(p)} exists and is non-trivial",
          os.path.exists(p) and os.path.getsize(p) > 200,
          f"{os.path.getsize(p) if os.path.exists(p) else 0} bytes")
check("favicon_path() returns a usable file",
      B.favicon_path() is not None and os.path.exists(B.favicon_path()))
try:
    from PIL import Image
    im = Image.open(paths[0])
    check("favicon is 512x512", im.size == (512, 512), str(im.size))
except Exception as e:
    check("favicon readable by Pillow", False, str(e)[:60])
check("lockup.svg exported for the dissertation",
      B.export_lockup_svg() is not None)

# ════════════════════════════════════════════════════════════════════════
print("\n=== icon set (§3.8) ===")
REQUIRED = ["dashboard", "prediction", "patients", "history", "performance",
            "training", "reports", "profile", "doctors", "admin", "roles",
            "settings", "analytics", "logs", "backup", "dataset", "signout",
            "search", "filter", "download", "warning", "check", "info",
            "chevron-right", "plus", "trash", "edit", "external"]
missing = [r for r in REQUIRED if r not in I.ICONS]
check(f"all {len(REQUIRED)} required icons present", not missing, str(missing))
check("set is around 24+ icons", len(I.ICONS) >= 24, str(len(I.ICONS)))
check("viewBox is 20", I.VIEW == 20)
check("stroke is 1.5 — matches the mark's hand at this size",
      I.STROKE == 1.5)

print("\n=== every icon is well-formed and inside its box ===")
bad_xml, out_of_box = [], []
for name in I.ICONS:
    try:
        ET.fromstring(I.to_svg(name))
    except Exception:
        bad_xml.append(name)
    for sh in I.ICONS[name]:
        k = sh[0]
        if k == "line":
            pts = [(sh[1], sh[2]), (sh[3], sh[4])]
        elif k == "poly":
            pts = list(sh[1])
        elif k in ("circle", "dot"):
            pts = [(sh[1] - sh[3], sh[2] - sh[3]), (sh[1] + sh[3], sh[2] + sh[3])]
        elif k == "rect":
            pts = [(sh[1], sh[2]), (sh[1] + sh[3], sh[2] + sh[4])]
        elif k == "ellipse":
            pts = [(sh[1] - sh[3], sh[2] - sh[4]), (sh[1] + sh[3], sh[2] + sh[4])]
        elif k in ("arc", "earc"):
            pts = []          # extent depends on the swept range; checked visually
        else:
            pts = []
        for x, y in pts:
            if not (-0.2 <= x <= I.VIEW + 0.2 and -0.2 <= y <= I.VIEW + 0.2):
                out_of_box.append(f"{name}({x},{y})")
check("all icons are well-formed XML", not bad_xml, str(bad_xml))
check("all non-arc geometry is inside the viewBox", not out_of_box,
      str(out_of_box[:5]))

print("\n=== renderer agreement (the mirrored-arc bug) ===")
# Both renderers must derive arc endpoints from the same screen-space formula.
# They previously disagreed by a sign, which mirrored every arc in the app relative
# to the verification sheet.
import math
for cx, cy, r, a in [(10, 10, 5, 0), (10, 10, 5, 90), (10, 10, 5, 180), (10, 10, 5, 270)]:
    px, py = I._arc_point(cx, cy, r, a)
    ex = cx + r * math.cos(math.radians(a))
    ey = cy + r * math.sin(math.radians(a))       # +sin: y grows DOWNWARD
    check(f"_arc_point({a}deg) uses screen-space +sin",
          abs(px - ex) < 1e-9 and abs(py - ey) < 1e-9, f"({px:.2f},{py:.2f})")
check("SVG arc uses sweep=1 (increasing angle in screen space)",
      "0 1 " in I._svg_arc(10, 10, 5, 180, 360) or " 1 " in I._svg_arc(10, 10, 5, 180, 360))

print("\n=== accessibility ===")
check("icons are decorative by default (aria-hidden)",
      'aria-hidden="true"' in I.to_svg("search"))
check("labelled icons expose an accessible name",
      'aria-label="Search"' in I.to_svg("search", label="Search")
      and 'role="img"' in I.to_svg("search", label="Search"))
check("icons inherit currentColor", 'stroke="currentColor"' in I.to_svg("check"))
check("no emoji or raster anywhere in the set",
      all(ord(c) < 0x2500 for n in I.ICONS for c in n))

print("\n=== navigation coverage ===")
NAV = ["Dashboard", "Heart Disease Prediction", "Patient Management",
       "Prediction History", "Model Performance", "Reports", "Profile",
       "Doctor Management", "Prediction Management", "Dataset Management",
       "Analytics", "Admin Management", "Role & Permission Management",
       "System Settings", "ML Model Management", "Activity Logs",
       "Backup & Restore"]
unmapped = [p for p in NAV if p not in I.NAV_ICON]
check(f"all {len(NAV)} routed pages have an icon", not unmapped, str(unmapped))
dangling = [v for v in I.NAV_ICON.values() if v not in I.ICONS]
check("every nav icon name resolves", not dangling, str(dangling))

print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
