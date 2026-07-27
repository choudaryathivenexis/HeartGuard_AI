"""
Chart layer tests — Phase 7.

The point of this phase was to make BUG-01/02 structurally impossible rather than
merely fixed, so most of these assertions are about invariants, not appearance.

The most valuable test in the file is the last one. It reads the page modules as SOURCE
and fails if any colour literal — hex OR named — sits on a line that reaches matplotlib.
That is the guarantee; everything else is a property of the module that provides the
alternative. A test that only exercised ui/charts.py would have passed happily while
app.py carried 268 hard-coded hexes, which is exactly the state this phase started in.

Two of the bugs below were found by rendering figures and looking at them, and could not
have been found any other way:

  * the heatmaps chose cell-text colour from the underlying VALUE, tuned for a colormap
    that is light at its high end. Swapping in one that is dark there made the largest
    cell in every confusion matrix dark-on-dark;
  * the model bar charts assigned colour by SORTED RANK, so a model changed colour
    whenever its ranking did — BUG-19 reintroduced.
"""

from __future__ import annotations

import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ui import charts as C
from ui import tokens as T

FAILURES: list[str] = []
HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


def as_hex(rgba) -> str:
    r, g, b = (int(round(255 * c)) for c in tuple(rgba)[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


print("\n=== 1. the palette is matplotlib-safe in both themes ===")
for theme in ("light", "dark"):
    p = C.palette(theme)
    bad = {k: v for k, v in p.items() if not HEX6.match(v)}
    check(f"{theme}: every value is a 6-digit hex", not bad, str(bad))
    check(f"{theme}: no CSS colour function", not any(
        v.startswith(("rgb", "hsl", "var")) for v in p.values()))
    check(f"{theme}: no theme-suffixed keys leak to callers",
          not any(k.endswith("_dark") for k in p),
          str([k for k in p if k.endswith("_dark")]))

light, dark = C.palette("light"), C.palette("dark")
check("the two themes differ", light != dark)
check("both expose the same roles", set(light) == set(dark),
      str(set(light) ^ set(dark)))
# The roles the sweep actually depends on must all exist, or a page raises at render.
for role in ("fg", "fg_muted", "fg_subtle", "axis", "grid", "spine", "surface",
             "reference", "primary", "ink", "risk_low", "risk_borderline",
             "risk_intermediate", "risk_high"):
    check(f"role {role!r} exists in both themes", role in light and role in dark)

# fg must actually invert, or the dark theme is only pretending.
check("fg inverts between themes",
      T.relative_luminance(light["fg"]) < 0.5 < T.relative_luminance(dark["fg"]),
      f'light {light["fg"]} dark {dark["fg"]}')


print("\n=== 2. color() ===")
try:
    C.color("definitely-not-a-role")
    check("unknown role raises rather than falling back", False, "returned a value")
except KeyError as exc:
    check("unknown role raises rather than falling back", True)
    check("the error names the available roles", "available:" in str(exc))
check("known role resolves", HEX6.match(C.color("fg")) is not None)


print("\n=== 3. series colours are keyed by NAME, not position (BUG-19) ===")
for name, expected in T.SERIES.items():
    check(f"{name} keeps its colour", C.series_color(name) == expected)
check("every model has a DISTINCT colour",
      len(set(T.SERIES.values())) == len(T.SERIES),
      str(len(set(T.SERIES.values()))))
check("unknown model falls back to reference, not a wrap-around collision",
      C.series_color("Not A Model") == C.palette()["reference"])
# Reordering the models must not move any colour. This is the actual BUG-19 property.
reordered = list(reversed(list(T.SERIES)))
check("reordering the model list changes nothing",
      [C.series_color(m) for m in reordered] == [T.SERIES[m] for m in reordered])


print("\n=== 4. categorical ramp ===")
cat = C.categorical()
check("is the brand ramp", cat == list(T.CHART_CATEGORICAL))
check("all distinct", len(set(cat)) == len(cat))
check("all matplotlib-safe", all(HEX6.match(c) for c in cat))
check("cycles rather than inventing hues past its length",
      C.categorical(8)[:6] == cat and C.categorical(8)[6] == cat[0])
check("no risk hue is used as a categorical slot",
      not ({T.RISK["high"]["rail"], T.RISK["low"]["rail"]} & set(cat)),
      "a metric bar would read as a clinical band")


print("\n=== 5. colormaps ===")
for kind in ("sequential", "risk", "diverging"):
    m = C.cmap(kind)
    check(f"{kind}: builds", m is not None)
    check(f"{kind}: endpoints are the declared stops",
          as_hex(m(0.0)).upper() == C._CMAP_STOPS[kind][0].upper()
          and as_hex(m(1.0)).upper() == C._CMAP_STOPS[kind][-1].upper(),
          f"{as_hex(m(0.0))} .. {as_hex(m(1.0))}")
check("reverse actually reverses",
      as_hex(C.cmap("risk", True)(0.0)) == as_hex(C.cmap("risk")(1.0)))
try:
    C.cmap("RdYlGn")
    check("built-in names are rejected", False, "RdYlGn was accepted")
except KeyError:
    check("built-in names are rejected", True)

# sequential is the one used for magnitude, so it must survive greyscale.
seq = [T.relative_luminance(as_hex(C.cmap("sequential")(v)))
       for v in (0.0, 0.25, 0.5, 0.75, 1.0)]
check("sequential luminance is monotonically decreasing",
      all(a > b for a, b in zip(seq, seq[1:])), str([round(x, 3) for x in seq]))
div = [T.relative_luminance(as_hex(C.cmap("diverging")(v))) for v in (0.0, 0.5, 1.0)]
check("diverging is dark-light-dark and roughly symmetric",
      div[1] > div[0] and div[1] > div[2] and abs(div[0] - div[2]) < 0.06,
      str([round(x, 3) for x in div]))
# Recorded honestly rather than asserted away: the risk ramp is NOT luminance-monotone
# and cannot be inside the Brand Six. The docstring tells callers to use `sequential`
# for magnitude; this pins the fact so nobody "fixes" the docs later.
rsk = [T.relative_luminance(as_hex(C.cmap("risk")(v))) for v in (0.0, 0.5, 1.0)]
check("risk ramp is documented as non-monotone, and is",
      not all(a > b for a, b in zip(rsk, rsk[1:])), str([round(x, 3) for x in rsk]))
check("cmap docstring warns against using risk for magnitude",
      "wrong for magnitude" in (C.cmap.__doc__ or ""))


print("\n=== 6. on_color: text on a filled cell ===")
# Chosen from the BACKGROUND's luminance, never from the underlying value. Deciding
# from the value is what made every confusion matrix's largest cell dark-on-dark.
for kind in ("sequential", "risk", "diverging"):
    m = C.cmap(kind)
    worst = 21.0
    for v in [i / 20 for i in range(21)]:
        bg = as_hex(m(v))
        worst = min(worst, T.contrast_ratio(C.on_color(bg), bg))
    check(f"{kind}: text on every cell clears WCAG AA large-text (3:1)",
          worst >= 3.0, f"worst ratio {worst:.2f}")
check("accepts an RGBA tuple, which is what a cmap returns",
      C.on_color((0.05, 0.07, 0.1, 1.0)) == T.BONE)
check("dark background gets light ink", C.on_color(T.INK) == T.BONE)
check("light background gets dark ink", C.on_color(T.BONE) == T.INK)


print("\n=== 7. figures are transparent and disposed of ===")
before = len(plt.get_fignums())
fig, ax = C.figure(4, 2)
check("figure is transparent", fig.patch.get_alpha() == 0.0)
check("axes background is transparent",
      ax.get_facecolor()[3] == 0.0, str(ax.get_facecolor()))
check("only the two named spines are visible",
      [n for n, s in ax.spines.items() if s.get_visible()] == ["left", "bottom"],
      str([n for n, s in ax.spines.items() if s.get_visible()]))
check("gridlines sit behind the data", ax.get_axisbelow() is True)


class _Sink:
    called = False

    @staticmethod
    def pyplot(f, **kw):
        _Sink.called = True


import streamlit as _st
_real = _st.pyplot
C.st = _Sink
try:
    C.render(fig)
finally:
    C.st = _st
check("render() hands the figure to streamlit", _Sink.called)
# matplotlib keeps every unclosed figure in a global registry, and this app reruns per
# keystroke. A leak here is a leak per keypress.
check("render() closes the figure", len(plt.get_fignums()) == before,
      f"{len(plt.get_fignums())} open, expected {before}")


print("\n=== 8. THE INVARIANT: no colour literal reaches matplotlib ===")
# This is the assertion the phase exists to make true. Everything above tests the
# alternative that ui/charts.py provides; this tests that the pages actually use it.
MPL_KW = re.compile(
    r"(?:color|colors|facecolor|edgecolor|edgecolors|labelcolor|markerfacecolor|"
    r"markeredgecolor|ecolor)\s*=\s*['\"]([^'\"]+)['\"]")
CMAP_KW = re.compile(r"cmap\s*=\s*['\"]([^'\"]+)['\"]")
GET_CMAP = re.compile(r"(?:plt\.cm\.)?get_cmap\(")
# HTML strings carry their own colours and belong to Phases 8-10. They are excluded by
# shape, not by hope: every one of them is inside markup or an inline style.
HTMLISH = re.compile(
    r"<(?:div|span|p|b|td|tr|table|style|h[1-6])\b|background:|border:|"
    r"linear-gradient|unsafe_allow_html|color:#|kpi\(")
ALLOWED_LITERAL = {"none", "white"}   # 'white' only survives on the printed A4 page

for path in ("app.py", "pages_ext.py", "clinical_ui.py"):
    offences = []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        if HTMLISH.search(line):
            continue
        for value in MPL_KW.findall(line):
            if value.lower() in ALLOWED_LITERAL:
                # 'white' is legitimate ONLY in clinical_ui's PDF, which prints on A4.
                if value.lower() == "white" and path != "clinical_ui.py":
                    offences.append(f"{i}: color='white' outside the PDF")
                continue
            offences.append(f"{i}: {value}")
        for cm in CMAP_KW.findall(line):
            offences.append(f"{i}: built-in cmap {cm!r}")
        if GET_CMAP.search(line):
            offences.append(f"{i}: get_cmap() — removed in matplotlib 3.9")
    check(f"{path}: no colour literal reaches matplotlib", not offences,
          "; ".join(offences[:6]))

# And the pages must be reaching for the module that replaced them.
for path in ("app.py", "pages_ext.py", "clinical_ui.py"):
    src = open(path, encoding="utf-8").read()
    check(f"{path}: routes colour through ui.charts",
          "ucharts." in src and "from ui import charts as ucharts" in src)


print("\n=== 9. the PDF never follows the viewer's theme ===")
# A dark-mode user exporting a report would otherwise get near-white ink on white A4 —
# an unreadable file, produced silently, that they then hand to someone else.
src = open("clinical_ui.py", encoding="utf-8").read()
pdf_block = src[src.index("def _pdf_text_page"):src.index("def build_pdf_report")]
# Strip comments first. The block contains a comment explaining WHY color() must not be
# used here, and matching raw source flagged that prose as a violation — the same
# substring-matching mistake that broke the brand tests in Phase 1b and the component
# tests in Phase 4. Assert the code, not the words about the code.
pdf_code = "\n".join(l.split("#")[0] for l in pdf_block.split("\n"))
check("the PDF page pins palette('light')", "palette('light')" in pdf_code)
check("the PDF page never calls the theme-following color()",
      "ucharts.color(" not in pdf_code,
      "color() follows the viewer and is wrong on a printed page")
check("waterfall_figure accepts a theme so the PDF copy can be pinned",
      "theme=None" in src[src.index("def waterfall_figure"):][:400])
check("app.py pins the PDF waterfall to light",
      'theme="light"' in open("app.py", encoding="utf-8").read())


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
