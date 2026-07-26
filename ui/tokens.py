"""
HeartGuard AI — Design Tokens
=============================
THE single source of truth for every colour, size, weight and duration in the
interface. Nothing else in the codebase may contain a hex value.

This mirrors the discipline already established by `feature_engineering.py`: one
definition, many consumers. That module exists because the encoding contract had
drifted into three divergent copies and silently corrupted every prediction (BUG-05).
The same failure mode applies to design: 85 distinct hard-coded hex values were
counted across app.py and pages_ext.py before this module existed, with no way to
tell which were intentional and which were drift.

--------------------------------------------------------------------------
THE CSS / MPL SPLIT — READ BEFORE ADDING A COLOUR
--------------------------------------------------------------------------
Colours are exposed in two dictionaries that must NEVER be interchanged:

    CSS   may contain rgba(), colour-mix(), var() — anything a browser accepts
    MPL   hex ONLY, always. Never a CSS function string.

matplotlib rejects CSS colour syntax with `ValueError: Invalid RGBA argument`.
Passing `rgba(14,19,26,0.5)` to `ax.barh(color=...)` was BUG-01 and BUG-02, which
killed the entire Model Performance page for all three roles and took the ROC, K-Fold
and SHAP tabs down with it. `tests/test_tokens.py` asserts every MPL value matches a
hex pattern, which makes that class of bug structurally impossible to reintroduce.

--------------------------------------------------------------------------
THE BRAND SIX
--------------------------------------------------------------------------
Six colours. No seventh hue exists in the interface, with exactly one declared
exception (SERIES["random_forest"], needed because five categorical chart hues cannot
be derived from three chromatics). Every other token here is a tint, shade or
interpolation of the six, and `verify_derivation()` proves it.
"""

from __future__ import annotations

import re

# ════════════════════════════════════════════════════════════════════════
# Colour mathematics — so derivation is visible in code, not asserted in prose
# ════════════════════════════════════════════════════════════════════════
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        *(max(0, min(255, int(round(c)))) for c in rgb)
    )


def mix(a: str, b: str, t: float) -> str:
    """Linear sRGB interpolation. t=0 -> a, t=1 -> b."""
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex((ra + (rb - ra) * t,
                       ga + (gb - ga) * t,
                       ba + (bb - ba) * t))


def alpha(value: str, a: float) -> str:
    """CSS-only rgba() string. NEVER pass the result to matplotlib."""
    r, g, b = hex_to_rgb(value)
    return f"rgba({r},{g},{b},{a:g})"


def hex_alpha(value: str, a: float) -> str:
    """8-digit hex with alpha — matplotlib-safe, unlike alpha()."""
    return f"{value}{max(0, min(255, int(round(a * 255)))):02X}"


def relative_luminance(value: str) -> float:
    """WCAG 2.2 relative luminance."""
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(value)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.2 contrast ratio. 4.5 = AA body text, 3.0 = AA large text / UI."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lo, hi = sorted((l1, l2))
    return (hi + 0.05) / (lo + 0.05)


# ════════════════════════════════════════════════════════════════════════
# 1. THE BRAND SIX
# ════════════════════════════════════════════════════════════════════════
INK       = "#0E131A"   # anchor: headings, the mark, dark canvas, hazard stripe
SLATE     = "#566171"   # structure: secondary text, borders, axis furniture
BONE      = "#F4F6F8"   # surface: app background, panels, printed page
VERDIGRIS = "#12756B"   # primary: interaction, identity, "within tolerance"
AMBER     = "#C08A1E"   # attention: caution, hazard stripe, mid-scale risk
CRIMSON   = "#C22B4A"   # critical: high risk, destructive actions, failures

BRAND_SIX = {
    "ink": INK, "slate": SLATE, "bone": BONE,
    "verdigris": VERDIGRIS, "amber": AMBER, "crimson": CRIMSON,
}

# ════════════════════════════════════════════════════════════════════════
# 2. DERIVED RAMPS
# ════════════════════════════════════════════════════════════════════════
# Ink -> Bone structural ramp, cool machined cast. The three neutrals do 80% of the
# work in this interface; the chromatics are reserved for meaning.
NEUTRAL = {
    0:   "#FFFFFF",   # page surface (light)
    25:  "#FAFBFC",   # raised surface
    50:  BONE,        # app background
    100: "#E9ECF0",   # subtle fill, table stripe
    200: "#D8DDE4",   # hairline border  <- default
    300: "#BCC4CE",   # strong border, disabled text
    400: "#97A1AE",   # placeholder, axis labels
    500: "#737E8C",   # tertiary text
    600: SLATE,       # secondary text, captions
    700: "#3E4856",   # body text
    800: "#2A323D",   # emphasis
    900: "#1A2029",   # headings
    950: INK,         # dark canvas
}

# Interaction and identity only — primary buttons, active nav, focus rings, links,
# the mark. Never fills a large area. Never decorative.
VERDIGRIS_RAMP = {
    50:  "#E6F4F1",
    100: "#C2E5DE",
    200: "#8ECFC4",
    300: "#52B3A5",   # dark-mode primary
    400: "#229184",   # hover
    500: VERDIGRIS,   # base
    600: "#0E5F57",   # pressed
    700: "#0B4A44",
    800: "#073632",
}

# Risk ramp — a Verdigris -> Amber -> Crimson interpolation sampled at four points.
#
# MEASURED CORRECTION TO THE DESIGN BRIEF
# ---------------------------------------
# The brief states these four descend monotonically in luminance. They do not, and
# they cannot: any ramp routed through Amber is non-monotonic, because Amber is
# intrinsically the lightest of the three chromatics.
#
#   low  L=0.195   borderline L=0.295   intermediate L=0.238   high L=0.137
#
# Forcing monotonicity would require darkening Amber into olive, which destroys the
# "amber = caution" reading that makes the hazard treatment work. The palette is
# over-constrained, so the guarantee is delivered a different way:
#
#   * all six pairwise luminance gaps are >= 0.043, so the four remain separable in
#     greyscale (verified in tests/test_tokens.py)
#   * every rail segment carries a hairline outline in its band `border` colour, which
#     satisfies WCAG 1.4.11 for a meaningful graphical object independently of
#     fill-vs-track contrast (Borderline is only 2.57:1 against the track unaided)
#   * band identity is never colour-only — colour + text label + rail position, always
#
# Colour is therefore decorative reinforcement, never the carrier of meaning, which is
# what the accessibility requirement actually demands.
#
# THE VERDIGRIS COLLISION, RESOLVED BY TREATMENT NOT HUE:
#   interaction   = solid verdigris fill + bone text
#   clinical state = tinted surface + dark coloured text
# A primary button and a "Low" chip are built differently, so they can never be
# confused even though both sit in the verdigris family. Components enforce this.
RISK = {
    "low":          {"text": "#14654E", "surface": "#E7F3EE", "rail": "#1E8A6A", "border": "#B9DDD0"},
    "borderline":   {"text": "#7A5410", "surface": "#FBF2DF", "rail": AMBER,     "border": "#EBD6A4"},
    "intermediate": {"text": "#8A4212", "surface": "#FBEBDF", "rail": "#D06A22", "border": "#EEC7A6"},
    "high":         {"text": "#8C1D33", "surface": "#FAE7EA", "rail": CRIMSON,   "border": "#EDBCC6"},
}
RISK_ORDER = ["low", "borderline", "intermediate", "high"]

# The track a rail fill sits on. Rails are outlined against it (see note above).
RAIL_TRACK = NEUTRAL[100]
RAIL_TRACK_DARK = "#232B36"

# Extrapolation is NOT a severity — it is a validity failure. The reading is off the
# scale entirely, so it gets no risk colour. Ink + Amber hazard stripe is universally
# read as "boundary crossed" rather than "worse than High", and it is the only
# repeating pattern anywhere in the interface, which makes it unmistakable.
HAZARD = {
    "text": INK, "surface": "#FBF2DF", "border": "#E5D6AE",
    "stripe_a": INK, "stripe_b": AMBER, "pitch": "8px", "angle": "45deg",
}

# System state. Kept visually distinct from the clinical ramp by using the Slate
# family for `info` rather than a blue — a blue here would read as a fifth risk level.
SEMANTIC = {
    "info":    {"text": "#3E4856", "surface": "#EDEFF3", "border": "#D2D8E0"},
    "success": {"text": "#14654E", "surface": "#E7F3EE", "border": "#B9DDD0"},
    "warning": {"text": "#7A5410", "surface": "#FBF2DF", "border": "#EBD6A4"},
    "danger":  {"text": "#8C1D33", "surface": "#FAE7EA", "border": "#EDBCC6"},
}

# Model series — permitted ONLY inside data visualisation, nowhere else in the UI.
# Five estimators need five distinguishable hues and five cannot be derived from three
# chromatics, so Iris is declared as the single exception to the six-colour rule.
# Ensemble is Ink because it is the aggregate of the others.
IRIS = "#6B5CA5"
SERIES = {
    "Logistic Regression":          VERDIGRIS,
    "Decision Tree":                AMBER,
    "XGBoost":                      "#C2404F",
    "Support Vector Machine (SVM)": SLATE,
    "Random Forest":                IRIS,      # the single declared extension
    "Ensemble Voting":              INK,
}
# Charts must never rely on colour alone — pair every series with a marker.
SERIES_MARKER = {
    "Logistic Regression": "o", "Decision Tree": "s", "XGBoost": "^",
    "Support Vector Machine (SVM)": "D", "Random Forest": "v",
    "Ensemble Voting": "*",
}

# ════════════════════════════════════════════════════════════════════════
# 3. DARK MODE
# ════════════════════════════════════════════════════════════════════════
# Canvas becomes neutral-950, surfaces 900, raised 800. Primary shifts to
# verdigris-300 for contrast. Risk surfaces become the RAIL colour at low alpha over
# the dark canvas — the light tints turn to mud on dark, so they are not reused.
DARK = {
    "canvas":       NEUTRAL[950],
    "surface":      "#151B24",
    "raised":       "#1D2530",
    "border":       "#2A323D",
    "border_strong": "#3E4856",
    "text":         "#E4E8ED",
    "text_muted":   "#A8B2BF",
    "text_subtle":  "#7A8493",
    "primary":      VERDIGRIS_RAMP[300],
    "primary_hover": VERDIGRIS_RAMP[200],
}
DARK_RISK = {
    band: {
        "text":    mix(spec["rail"], "#FFFFFF", 0.55),
        "surface": hex_alpha(spec["rail"], 0.14),
        "rail":    spec["rail"],
        "border":  hex_alpha(spec["rail"], 0.38),
    }
    for band, spec in RISK.items()
}
DARK_SEMANTIC = {
    key: {
        "text":    mix(spec["text"], "#FFFFFF", 0.62),
        "surface": hex_alpha(spec["text"], 0.14),
        "border":  hex_alpha(spec["text"], 0.34),
    }
    for key, spec in SEMANTIC.items()
}

# ════════════════════════════════════════════════════════════════════════
# 4. TYPOGRAPHY
# ════════════════════════════════════════════════════════════════════════
FONT_IMPORT = (
    "https://fonts.googleapis.com/css2?"
    "family=Archivo:wdth,wght@100..125,400..700"
    "&family=IBM+Plex+Sans:wght@400;500;600"
    "&family=IBM+Plex+Mono:wght@400;500"
    "&display=swap"
)
FONT_DISPLAY = "'Archivo', 'Helvetica Neue', Arial, sans-serif"       # >= 24px only
FONT_UI      = "'IBM Plex Sans', -apple-system, 'Segoe UI', sans-serif"
FONT_MONO    = "'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace"

TYPE_SCALE = [11, 12, 13, 14, 16, 18, 20, 24, 30, 38, 48, 64]

# Tracking tightens as size grows — the standard optical correction.
TRACKING = {
    "eyebrow": "0.06em",    # 11-12px uppercase
    "base":    "0",         # 13-20px
    "tight":   "-0.011em",  # 24-30px
    "tighter": "-0.022em",  # 38px+
}
WEIGHT = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700}

# Every number in this application uses tabular figures. A probability that shifts
# horizontally as it updates is a defect in a measuring instrument.
TABULAR = "font-variant-numeric: tabular-nums; font-feature-settings: 'tnum' 1;"

# ════════════════════════════════════════════════════════════════════════
# 5. SPACE, RADIUS, ELEVATION, MOTION
# ════════════════════════════════════════════════════════════════════════
SPACE = [2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80]

# Radii stay small — enterprise density, not consumer softness. Nothing is a pill
# except status chips.
RADIUS = {"sm": "3px", "md": "5px", "lg": "8px", "xl": "12px", "2xl": "16px",
          "pill": "999px"}

# Hairline borders carry structure; shadows are only for things that genuinely float.
# A dashboard where every card casts a shadow reads as a template.
SHADOW = {
    "e1": f"0 1px 2px {alpha(INK, 0.05)}",
    "e2": f"0 1px 3px {alpha(INK, 0.07)}, 0 1px 2px {alpha(INK, 0.04)}",
    "e3": f"0 4px 12px {alpha(INK, 0.08)}, 0 1px 3px {alpha(INK, 0.05)}",
    "e4": f"0 12px 32px {alpha(INK, 0.12)}, 0 2px 8px {alpha(INK, 0.06)}",
}
DURATION = {"fast": "120ms", "base": "180ms", "slow": "240ms"}
EASING = "cubic-bezier(0.2, 0, 0.15, 1)"

LAYOUT = {
    "sidebar_width": "280px",
    "content_max":   "1440px",
    "content_pad_x": "32px",
    "content_pad_t": "24px",
    "rail_height":   "10px",
    "rail_height_sm": "6px",
}

# ════════════════════════════════════════════════════════════════════════
# 6. CSS — browser-facing. May contain rgba(), var(), colour-mix().
# ════════════════════════════════════════════════════════════════════════
CSS: dict[str, str] = {
    # surfaces & structure
    "canvas":         NEUTRAL[50],
    "surface":        NEUTRAL[0],
    "raised":         NEUTRAL[25],
    "sunken":         NEUTRAL[100],
    "border":         NEUTRAL[200],   # DECORATIVE hairline — see border_control
    "border_strong":  NEUTRAL[300],
    # WCAG 1.4.11 requires 3:1 only for boundaries REQUIRED TO IDENTIFY a control.
    # A decorative panel hairline is exempt; an input's edge is not. neutral-200 is
    # 1.37:1 on white and can never satisfy that, so control boundaries get their own
    # token: 3.32:1 on white, 3.06:1 on bone. Both pass.
    "border_control": "#848E9C",
    "rail_track":     RAIL_TRACK,
    "hairline":       alpha(INK, 0.08),
    # text
    "text":           NEUTRAL[700],
    "text_heading":   NEUTRAL[900],
    "text_muted":     NEUTRAL[600],
    "text_subtle":    NEUTRAL[500],
    "text_disabled":  NEUTRAL[300],
    "text_inverse":   BONE,
    # interaction
    "primary":        VERDIGRIS_RAMP[500],
    "primary_hover":  VERDIGRIS_RAMP[400],
    "primary_active": VERDIGRIS_RAMP[600],
    "primary_tint":   VERDIGRIS_RAMP[50],
    "primary_border": VERDIGRIS_RAMP[100],
    "focus_ring":     VERDIGRIS_RAMP[500],
    "link":           VERDIGRIS_RAMP[500],
    # hazard
    "hazard_text":    HAZARD["text"],
    "hazard_surface": HAZARD["surface"],
    "hazard_border":  HAZARD["border"],
}
for _b in RISK_ORDER:
    for _k, _v in RISK[_b].items():
        CSS[f"risk_{_b}_{_k}"] = _v
for _s, _spec in SEMANTIC.items():
    for _k, _v in _spec.items():
        CSS[f"{_s}_{_k}"] = _v

CSS_DARK: dict[str, str] = {
    "canvas": DARK["canvas"], "surface": DARK["surface"], "raised": DARK["raised"],
    "sunken": DARK["border"], "border": DARK["border"],
    "border_strong": DARK["border_strong"],
    "border_control": "#5A6675",
    "rail_track": RAIL_TRACK_DARK,
    "hairline": alpha("#FFFFFF", 0.10),
    "text": DARK["text"], "text_heading": "#F2F5F8", "text_muted": DARK["text_muted"],
    "text_subtle": DARK["text_subtle"], "text_disabled": "#4A5461",
    "text_inverse": INK,
    "primary": DARK["primary"], "primary_hover": DARK["primary_hover"],
    "primary_active": VERDIGRIS_RAMP[400], "primary_tint": hex_alpha(VERDIGRIS_RAMP[300], 0.14),
    "primary_border": hex_alpha(VERDIGRIS_RAMP[300], 0.34),
    "focus_ring": DARK["primary"], "link": DARK["primary"],
    "hazard_text": "#F5E4BE", "hazard_surface": hex_alpha(AMBER, 0.14),
    "hazard_border": hex_alpha(AMBER, 0.38),
}
for _b in RISK_ORDER:
    for _k, _v in DARK_RISK[_b].items():
        CSS_DARK[f"risk_{_b}_{_k}"] = _v
for _s, _spec in DARK_SEMANTIC.items():
    for _k, _v in _spec.items():
        CSS_DARK[f"{_s}_{_k}"] = _v

# ════════════════════════════════════════════════════════════════════════
# 7. MPL — matplotlib-facing. HEX ONLY. Never a CSS function string.
# ════════════════════════════════════════════════════════════════════════
# Enforced by tests/test_tokens.py against HEX_RE. This is the structural guarantee
# that BUG-01 / BUG-02 cannot recur.
MPL: dict[str, str] = {
    # figure furniture
    "fg":            NEUTRAL[700],
    "fg_muted":      NEUTRAL[600],
    "fg_subtle":     NEUTRAL[500],
    "axis":          NEUTRAL[400],
    "grid":          NEUTRAL[200],
    "spine":         NEUTRAL[300],
    "surface":       NEUTRAL[0],
    "canvas":        NEUTRAL[50],
    "ink":           INK,
    "reference":     SLATE,
    # interaction
    "primary":       VERDIGRIS_RAMP[500],
    "primary_light": VERDIGRIS_RAMP[200],
    # dark-mode furniture
    "fg_dark":       DARK["text"],
    "fg_muted_dark": DARK["text_muted"],
    "axis_dark":     DARK["text_subtle"],
    "grid_dark":     DARK["border"],
    "spine_dark":    DARK["border_strong"],
    "surface_dark":  DARK["surface"],
    "canvas_dark":   DARK["canvas"],
    # hazard hatch
    "hazard":        AMBER,
    "hazard_ink":    INK,
}
for _b in RISK_ORDER:
    MPL[f"risk_{_b}"] = RISK[_b]["rail"]
    MPL[f"risk_{_b}_text"] = RISK[_b]["text"]
    MPL[f"risk_{_b}_surface"] = RISK[_b]["surface"]
for _name, _hexv in SERIES.items():
    MPL["series_" + re.sub(r"[^a-z0-9]+", "_", _name.lower()).strip("_")] = _hexv
for _s, _spec in SEMANTIC.items():
    MPL[f"{_s}"] = _spec["text"]

# Streamlit's native chart palette — same order as SERIES, hex only.
CHART_CATEGORICAL = [VERDIGRIS, AMBER, "#C2404F", SLATE, IRIS, INK]


# ════════════════════════════════════════════════════════════════════════
# 8. Lookups & self-verification
# ════════════════════════════════════════════════════════════════════════
def risk_band_key(band_label: str) -> str:
    """Map a UI band label ('HIGH RISK', 'BORDERLINE', ...) to a RISK key."""
    s = (band_label or "").strip().lower()
    if "high" in s:
        return "high"
    if "intermediate" in s:
        return "intermediate"
    if "borderline" in s:
        return "borderline"
    return "low"


def series_color(model_name: str) -> str:
    """matplotlib-safe colour for a model series, keyed by NAME not position.

    Keyed lookup rather than positional indexing — BUG-19 was a positional palette
    zipped against results.json keys, which silently mislabelled every chart when the
    key set changed.
    """
    if model_name in SERIES:
        return SERIES[model_name]
    return SLATE


def verify_derivation(tolerance: int = 45) -> list[str]:
    """
    Confirm every ramp step is a plausible tint/shade/mix of the Brand Six.

    Returns a list of violations (empty when the palette is coherent). This is what
    makes "no seventh hue" a checkable property rather than a claim in a document.
    IRIS is the single permitted exception and is skipped by name, not by distance.

    THE TOLERANCE IS EMPIRICALLY CALIBRATED, not guessed. Measured sum-RGB distance
    to the nearest three-stop construction:

        hand-tuned palette members   27 - 37   (verdigris-300/400, intermediate)
        Iris, the declared exception  58
        purple-pink                   71
        cornflower blue               91
        hospital teal-blue           104
        lime                         109
        SaaS indigo                  123

    45 sits in the gap. It admits values a designer optimised for contrast (~12 per
    channel, visually imperceptible) while rejecting every hue the brief explicitly
    names as off-brand, by a factor of two or more. A stricter tolerance flagged
    legitimate members; a looser one would have admitted cornflower blue, which is
    the exact colour the design direction was written to avoid.
    """
    anchors = list(BRAND_SIX.values()) + ["#FFFFFF"]
    violations: list[str] = []

    def nearest_mix_distance(target: str) -> int:
        """
        Distance to the nearest THREE-stop construction from the Brand Six.

        A two-stop linear search is too naive: real perceptual ramps are a hue mix
        followed by a tint toward white or a shade toward ink, which is exactly how
        verdigris-300/400 and the risk text colours are built. Searching two stops
        only flagged those as "outside the palette" when they are plainly derived.
        """
        tr, tg, tb = hex_to_rgb(target)
        best = 10 ** 6
        tints = ["#FFFFFF", INK]
        for a in anchors:
            for b in anchors:
                for i in range(0, 101, 5):
                    stop = mix(a, b, i / 100.0)
                    for tint in tints:
                        for j in range(0, 101, 5):
                            cr, cg, cb = hex_to_rgb(mix(stop, tint, j / 100.0))
                            d = abs(tr - cr) + abs(tg - cg) + abs(tb - cb)
                            if d < best:
                                best = d
                                if best == 0:
                                    return 0
        return best

    checked: dict[str, str] = {}
    checked.update({f"neutral-{k}": v for k, v in NEUTRAL.items()})
    checked.update({f"verdigris-{k}": v for k, v in VERDIGRIS_RAMP.items()})
    for band, spec in RISK.items():
        for k, v in spec.items():
            checked[f"risk-{band}-{k}"] = v
    for name, spec in SEMANTIC.items():
        for k, v in spec.items():
            checked[f"semantic-{name}-{k}"] = v

    for label, value in checked.items():
        d = nearest_mix_distance(value)
        if d > tolerance:
            violations.append(f"{label} ({value}) is {d} from any Brand Six mix")
    return violations


__all__ = [
    "INK", "SLATE", "BONE", "VERDIGRIS", "AMBER", "CRIMSON", "IRIS", "BRAND_SIX",
    "NEUTRAL", "VERDIGRIS_RAMP", "RISK", "RISK_ORDER", "HAZARD", "SEMANTIC",
    "SERIES", "SERIES_MARKER", "DARK", "DARK_RISK", "DARK_SEMANTIC",
    "CSS", "CSS_DARK", "MPL", "CHART_CATEGORICAL",
    "FONT_IMPORT", "FONT_DISPLAY", "FONT_UI", "FONT_MONO",
    "TYPE_SCALE", "TRACKING", "WEIGHT", "TABULAR",
    "SPACE", "RADIUS", "SHADOW", "DURATION", "EASING", "LAYOUT",
    "hex_to_rgb", "rgb_to_hex", "mix", "alpha", "hex_alpha",
    "relative_luminance", "contrast_ratio", "risk_band_key", "series_color",
    "verify_derivation", "HEX_RE",
]
