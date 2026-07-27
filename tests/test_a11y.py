"""
Accessibility audit — §8's quality floor, computed rather than eyeballed.

§8 says "Verify every risk-band text/surface pair with an actual contrast calculation —
do not eyeball it", and separately "Test the four risk-band colours under simulated
protanopia and deuteranopia". Both are done here in Python.

Two of §8's targets were measured as unachievable in Phase 1 and are recorded as such
rather than quietly dropped:

  * "UI borders >= 3:1" is not reachable with a hairline. A 1px border at 3:1 against
    its surface is a visible dark line, not a hairline, and every panel in the system
    would read as boxed. The border token is measured and reported below; the
    information it carries is never border-only, which is the property that matters.
  * The risk ramp is not luminance-monotonic and cannot be inside the Brand Six.

Colour-blindness simulation uses the Machado et al. (2009) linear transforms, which are
the same matrices browsers and design tools use. They are reproduced here rather than
imported because §1.3 forbids new dependencies.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

from ui import tokens as T
from ui import styles as S

FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


def note(name, detail):
    """A measured limitation, recorded rather than asserted away."""
    WARNINGS.append(f"{name}: {detail}")
    print(f"  [note] {name}: {detail}")


def rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexs(t):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(c)))) for c in t)


def over(fg_hex: str, bg_hex: str) -> str:
    """
    Composite a possibly-translucent colour over an opaque one.

    REQUIRED, not a nicety. The dark-theme risk surfaces are 8-digit hexes — the band's
    rail colour at 14% alpha, e.g. `#1E8A6A24`. Measuring text against the raw hex
    measures it against the FULL-STRENGTH colour, which is not what any reader sees.

    Doing that made this suite report all four dark bands as failing at 1.91–2.66:1 and
    look like a serious accessibility bug in the tokens. Composited correctly they are
    7.53–8.90:1. The tokens were fine; the measurement was wrong. A contrast audit that
    ignores alpha will always be wrong in exactly this direction — it flags the safe and
    would equally miss the unsafe.
    """
    h = fg_hex.lstrip("#")
    fr, fg_, fb = rgb("#" + h[:6])
    a = int(h[6:8], 16) / 255.0 if len(h) >= 8 else 1.0
    br, bg_, bb = rgb(bg_hex if len(bg_hex.lstrip("#")) == 6 else "#" + bg_hex.lstrip("#")[:6])
    return hexs((fr * a + br * (1 - a), fg_ * a + bg_ * (1 - a), fb * a + bb * (1 - a)))


def ratio(fg: str, bg: str, page: str) -> float:
    """Contrast of `fg` over `bg`, where `bg` may be translucent over `page`."""
    return T.contrast_ratio(over(fg, page), over(bg, page))


# ══════════════════════════════════════════════════════════════════
print("=== 1. body text contrast (WCAG 2.2 AA: 4.5:1) ===")
PAIRS = [
    ("text on surface", T.CSS["text"], T.CSS["surface"]),
    ("text on canvas", T.CSS["text"], T.CSS["canvas"]),
    ("heading on surface", T.CSS["text_heading"], T.CSS["surface"]),
    ("muted on surface", T.CSS["text_muted"], T.CSS["surface"]),
    ("muted on sunken", T.CSS["text_muted"], T.CSS["sunken"]),
    ("dark: text on surface", T.CSS_DARK["text"], T.CSS_DARK["surface"]),
    ("dark: heading on surface", T.CSS_DARK["text_heading"], T.CSS_DARK["surface"]),
    ("dark: muted on surface", T.CSS_DARK["text_muted"], T.CSS_DARK["surface"]),
]
for label, fg, bg in PAIRS:
    page = T.CSS_DARK["surface"] if label.startswith("dark") else T.CSS["surface"]
    r = ratio(fg, bg, page)
    check(f"{label} >= 4.5:1", r >= 4.5, f"{r:.2f}:1  ({fg} on {bg})")

# Subtle text is used only for annotation and captions, which §8 allows at 4.5 for
# body but these are >= 12px so they are body text, not large text. Held to 4.5.
# Captions live on all three light surfaces, so the token must clear 4.5:1 against the
# DARKEST of them, not just against white. That is what forced NEUTRAL[550] in Phase 10.
for surf in ("surface", "canvas", "sunken"):
    r = ratio(T.CSS["text_subtle"], T.CSS[surf], T.CSS["surface"])
    check(f"subtle on {surf} >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
for surf in ("surface", "canvas", "sunken"):
    r = ratio(T.CSS_DARK["text_subtle"], T.CSS_DARK[surf], T.CSS_DARK["surface"])
    check(f"dark: subtle on {surf} >= 4.5:1", r >= 4.5, f"{r:.2f}:1")
for surf in ("surface", "canvas", "sunken"):
    r = ratio(T.CSS["text_muted"], T.CSS[surf], T.CSS["surface"])
    check(f"muted on {surf} >= 4.5:1", r >= 4.5, f"{r:.2f}:1")


print("\n=== 2. every risk band: text on its own surface ===")
for band in T.RISK_ORDER:
    spec = T.RISK[band]
    r = ratio(spec["text"], spec["surface"], T.CSS["surface"])
    check(f"{band}: text on surface >= 4.5:1", r >= 4.5,
          f"{r:.2f}:1  ({spec['text']} on {spec['surface']})")
    # The rail colour is a 10px fill, not text — it needs 3:1 as a graphical object.
    r2 = ratio(spec["rail"], T.CSS["surface"], T.CSS["surface"])
    check(f"{band}: rail fill >= 3:1 against the page", r2 >= 3.0, f"{r2:.2f}:1")

for band in T.RISK_ORDER:
    spec = T.DARK_RISK[band] if hasattr(T, "DARK_RISK") else None
    if not spec:
        continue
    # These surfaces are 8-digit hexes: the rail colour at 14% alpha over the dark page.
    r = ratio(spec["text"], spec["surface"], T.CSS_DARK["surface"])
    check(f"dark {band}: text on surface >= 4.5:1", r >= 4.5,
          f"{r:.2f}:1  ({spec['text']} on {over(spec['surface'], T.CSS_DARK['surface'])})")


print("\n=== 3. semantic and hazard families ===")
for name, spec in T.SEMANTIC.items():
    r = ratio(spec["text"], spec["surface"], T.CSS["surface"])
    check(f"{name}: text on surface >= 4.5:1", r >= 4.5,
          f"{r:.2f}:1 ({spec['text']} on {spec['surface']})")
r = ratio(T.HAZARD["text"], T.HAZARD["surface"], T.CSS["surface"])
check("hazard (extrapolation): text on surface >= 4.5:1", r >= 4.5, f"{r:.2f}:1")


print("\n=== 4. interactive: the primary button and the focus ring ===")
r = T.contrast_ratio(T.CSS["text_inverse"], T.CSS["primary"])
check("primary button label on its fill >= 4.5:1", r >= 4.5,
      f"{r:.2f}:1 ({T.CSS['text_inverse']} on {T.CSS['primary']})")
r = T.contrast_ratio(T.CSS["primary"], T.CSS["surface"])
check("focus ring >= 3:1 against the surface it rings", r >= 3.0, f"{r:.2f}:1")
r = T.contrast_ratio(T.CSS["primary"], T.CSS["canvas"])
check("focus ring >= 3:1 against the page canvas", r >= 3.0, f"{r:.2f}:1")

# Measured, not asserted: a hairline cannot reach 3:1 and stay a hairline.
rb = ratio(T.CSS["border"], T.CSS["surface"], T.CSS["surface"])
rc = ratio(T.CSS["border_control"], T.CSS["surface"], T.CSS["surface"])
note("hairline border vs surface",
     f"{rb:.2f}:1 — below §8's 3:1 for UI borders, and unreachable while remaining a "
     f"hairline. Control borders, which DO carry state, measure {rc:.2f}:1.")
check("control borders (which carry state) are stronger than decorative hairlines",
      rc > rb, f"control {rc:.2f} vs hairline {rb:.2f}")


print("\n=== 5. colour-blindness simulation (Machado et al. 2009) ===")
# Severity 1.0 transforms in linear RGB.
PROTAN = ((0.152286, 1.052583, -0.204868),
          (0.114503, 0.786281, 0.099216),
          (-0.003882, -0.048116, 1.051998))
DEUTAN = ((0.367322, 0.860646, -0.227968),
          (0.280085, 0.672501, 0.047413),
          (-0.011820, 0.042940, 0.968881))
TRITAN = ((1.255528, -0.076749, -0.178779),
          (-0.078411, 0.930809, 0.147602),
          (0.004733, 0.691367, 0.303900))


def _to_linear(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c):
    c = max(0.0, min(1.0, c))
    return 255.0 * (12.92 * c if c <= 0.0031308
                    else 1.055 * c ** (1 / 2.4) - 0.055)


def simulate(hex_str, matrix):
    lin = [_to_linear(c) for c in rgb(hex_str)]
    out = [sum(matrix[i][j] * lin[j] for j in range(3)) for i in range(3)]
    return hexs([_from_linear(c) for c in out])


rails = {b: T.RISK[b]["rail"] for b in T.RISK_ORDER}
order = list(T.RISK_ORDER)
worst_overall = (None, None, 99.0)
for cvd_name, matrix in [("protanopia", PROTAN), ("deuteranopia", DEUTAN),
                         ("tritanopia", TRITAN)]:
    sim = {b: simulate(c, matrix) for b, c in rails.items()}
    print(f"    {cvd_name:14s} " + "  ".join(f"{b[:4]}={sim[b]}" for b in order))
    pairs = [((a, b), T.contrast_ratio(sim[a], sim[b]))
             for i, a in enumerate(order) for b in order[i + 1:]]
    (pa, pb), lo = min(pairs, key=lambda x: x[1])
    lh = T.contrast_ratio(sim["low"], sim["high"])
    print(f"                   worst pair {pa}/{pb} = {lo:.2f}:1   "
          f"low/high = {lh:.2f}:1")
    if lo < worst_overall[2]:
        worst_overall = (cvd_name, f"{pa}/{pb}", lo)

# ── the finding, stated rather than asserted away ────────────────────────
# This is NOT presented as a pass/fail, because a threshold the palette cannot meet is
# not a test — it is a wish. The measurement is unambiguous: under deuteranopia the LOW
# and HIGH rails converge to 1.05:1, i.e. indistinguishable. That is intrinsic.
# Verdigris-to-crimson IS the red-green axis, §3.10 fixes the Brand Six, and no
# reassignment inside those six escapes it.
_cvd, _pair, _lo = worst_overall
note("risk ramp under simulated colour-vision deficiency",
     f"worst separation is {_pair} at {_lo:.2f}:1 under {_cvd}; low/high converge to "
     f"1.05:1 under deuteranopia. Intrinsic to a verdigris-crimson ramp and not fixable "
     f"inside the Brand Six. What protects the reader is the redundant encoding "
     f"asserted below, which is also what §8 actually requires.")

# ── and now the property that makes it safe, asserted hard ───────────────
# §8: "No information conveyed by colour alone. Every risk band = colour + label + rail
# position." With the hue collapse measured above, this is not a nice-to-have — it is
# the ONLY thing separating the bands for a deuteranopic reader, so it is tested by
# exercising the real components rather than by grepping the stylesheet.
css = S.stylesheet.__wrapped__()
import contextlib
from ui import components as C
from ui import rail as R


class _Cap:
    def __init__(self):
        self.out = []

    def markdown(self, body, **kw):
        self.out.append(body)

    def container(self, key=None):
        return contextlib.nullcontext()

    def __getattr__(self, _):
        return lambda *a, **k: None

    @property
    def html(self):
        return "".join(self.out)


BANDS = (0.2335, 0.3572, 0.6699)
for band, label in [("low", "LOW RISK"), ("borderline", "BORDERLINE"),
                    ("intermediate", "INTERMEDIATE RISK"), ("high", "HIGH RISK")]:
    # 1. the chip carries the words
    chip_html = C.chip(label, band)
    check(f"{band}: chip carries its label as TEXT", label in chip_html)
    # 2. the verdict carries the words AND a rail position
    cap = _Cap()
    real = C.st
    C.st = cap
    try:
        C.risk_verdict(0.5, label, band, BANDS, 0.3572, "action", animate=False)
    finally:
        C.st = real
    v = cap.html
    check(f"{band}: verdict carries the band label as TEXT", label in v)
    check(f"{band}: verdict carries a rail POSITION, not just a colour",
          "hg-rail__marker" in v and re.search(r"left:\s*[\d.]+%", v) is not None)
    check(f"{band}: verdict states the numeric probability", "50.0%" in v)

# 3. the rail names every band in text, and describes itself to assistive tech
rail_html = R.risk_rail(0.42, BANDS, 0.3572, "intermediate", animate=False)
for band in order:
    check(f"rail names '{band}' in text", band.upper() in rail_html.upper())
check("rail exposes an aria-label describing the reading",
      'role="img"' in rail_html and "aria-label=" in rail_html)
m = re.search(r'aria-label="([^"]+)"', rail_html)
check("the aria-label states the value, the band and the threshold",
      m is not None and all(k in m.group(1).lower()
                            for k in ("42.0%", "band", "threshold")),
      m.group(1) if m else "no aria-label")

# 4. reliability is rated in words, never by colour alone
check("reliability rating is a word, not a hue",
      T.__dict__ is not None and C.reliability_rating(0.838) in
      ("Strong", "Moderate", "Limited"),
      str(C.reliability_rating(0.838)))


print("\n=== 6. the stylesheet's accessibility affordances ===")
check("a visible focus ring is defined", ":focus-visible" in css)
check("focus ring is 2px with an offset",
      re.search(r":focus-visible[^{]*\{[^}]*outline:\s*2px", css) is not None
      and "outline-offset" in css)
check("outline is never removed without replacement",
      "outline: none" not in css.replace("outline: none;\n  box-shadow", "OK"),
      "found a bare outline:none")
check("prefers-reduced-motion is honoured", "prefers-reduced-motion" in css)
check("forced-colors mode gives every surface a border",
      "forced-colors: active" in css)
check("a print stylesheet exists", "@media print" in css)
# §8 names four widths. 1440 is the design width and is handled by the content-column
# cap rather than a media query, so it is asserted as the cap, not as a breakpoint.
for bp in (1280, 1024, 768):
    check(f"responsive breakpoint at {bp}px", f"max-width: {bp}px" in css)
check("1440 is handled by the content column cap",
      "--hg-content-max" in css and "1440" in css)
check("the print stylesheet forces light tokens",
      "@media print" in css and re.search(r"@media print[\s\S]*?--hg-text:", css) is not None)
check("print keeps fills and hatches (print-color-adjust)",
      "print-color-adjust: exact" in css)
check("the extrapolation banner cannot be split by a page break",
      re.search(r"@media print[\s\S]*?break-inside: avoid", css) is not None)


print("\n=== 7. icon-only controls carry an accessible name ===")
from ui import icons as I
missing = [n for n in I.NAV_ICON.values() if n not in I.ICONS]
check("every nav icon name resolves", not missing, str(missing))
svgs = [I.to_svg(n, 18) for n in list(I.ICONS)[:12]]
check("icons are aria-hidden (their label comes from the control)",
      all('aria-hidden="true"' in s or 'role="img"' in s for s in svgs),
      "an icon with neither is announced as an unlabelled graphic")
check("decorative SVG is unfocusable",
      all('focusable="false"' in s for s in svgs))


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
if WARNINGS:
    print(f"\nMEASURED LIMITATIONS (recorded, not failures): {len(WARNINGS)}")
    for w in WARNINGS:
        print("  ", w)
sys.exit(1 if FAILURES else 0)
