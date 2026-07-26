"""
HeartGuard AI — The Reference Rail
==================================
The signature element. A horizontal measurement track that appears wherever the system
reports a value with a meaningful range, and the visual embodiment of the product's
thesis: **the reading and its tolerance are always shown together.**

The Caliper Mark is this element compressed into a monogram — same idea, two scales.

--------------------------------------------------------------------------
ANATOMY
--------------------------------------------------------------------------
    notch      ▼                        threshold, ABOVE the track, in ink
    strip   LOW │ BORDERLINE │ …        labels only, boundaries as hairlines
    track   ▓▓▓▓▓▓▓▓▓▓▲░░░░░░░░        fill = the measured value; hatch = invalid
    labels  0%     34.0%        100%    endpoints always present

--------------------------------------------------------------------------
FIVE CONTEXTS (§3.2)
--------------------------------------------------------------------------
    risk_rail       probability, four band zones, the active threshold
    envelope_rail   a patient value against the training min/max, p1-p99 shaded,
                    out-of-range hatched
    ci_rail         point estimate + 95% interval, optional reference line
    sweep_rail      the selected operating point against the candidate range
    subgroup_rails  one ci_rail per stratum against an overall reference

--------------------------------------------------------------------------
RULES, AND WHY EACH ONE EXISTS
--------------------------------------------------------------------------
* The threshold notch is drawn ABOVE the track and in ink, never in a risk colour. It
  is a decision boundary, not a value — colouring it would imply it was a reading.

* Band boundaries are hairlines. Filling the band zones would compete with the one
  fill that carries information: the measured value. The band strip is therefore
  purely typographic — labels at segment centres, the active one emphasised in its
  band colour, the rest muted.

* An out-of-range value is NEVER clamped to the edge. The domain expands to contain
  it and the invalid span is hatched, with the marker sitting inside the hatch. Pinning
  the marker to the rail end would hide the extrapolation, which is the single thing
  this product exists to disclose (BUG-23).

* Every rail carries numeric endpoints. A rail without labels is decoration.

* Geometry lives in `RailGeometry` / `envelope_geometry` as pure functions, separately
  testable, because "the marker is inside the hatched zone" is an arithmetic claim and
  should be asserted as one rather than eyeballed in a browser.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import tokens as T
from .format import esc, pct

# The hazard stripe is the only repeating pattern in the interface, which is what makes
# it unmistakable. Out-of-envelope IS the extrapolation condition, so it reuses the same
# treatment rather than inventing a second "invalid" language.
HATCH_CSS = (
    f"repeating-linear-gradient({T.HAZARD['angle']},"
    f"{T.HAZARD['stripe_a']} 0 2px,"
    f"transparent 2px 4px,"
    f"{T.HAZARD['stripe_b']} 4px 6px,"
    f"transparent 6px {T.HAZARD['pitch']})"
)


# ════════════════════════════════════════════════════════════════════════
# Geometry — pure, testable
# ════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class RailGeometry:
    """Maps a value domain onto 0-100% of the track."""
    lo: float
    hi: float

    @property
    def span(self) -> float:
        s = self.hi - self.lo
        return s if abs(s) > 1e-12 else 1.0

    def pos(self, value: float) -> float:
        """Percentage position of `value`, clamped to the track only for rendering."""
        return max(0.0, min(100.0, (float(value) - self.lo) / self.span * 100.0))

    def raw_pos(self, value: float) -> float:
        """Unclamped percentage — used to detect values outside the drawn domain."""
        return (float(value) - self.lo) / self.span * 100.0

    def width(self, a: float, b: float) -> float:
        return abs(self.pos(b) - self.pos(a))


@dataclass(frozen=True)
class EnvelopeGeometry:
    """
    Layout for a value measured against a supported envelope.

    `extrapolated` means the value is outside [env_lo, env_hi] — a genuine
    extrapolation. `sparse` means it is inside the observed range but beyond the
    1st-99th percentile, i.e. thin training support. These are different claims and are
    reported separately, matching `clinical_ui.check_applicability`.
    """
    geom: RailGeometry
    value: float
    env_lo: float
    env_hi: float
    p1: float | None
    p99: float | None
    extrapolated: bool
    sparse: bool

    @property
    def value_pos(self) -> float:
        return self.geom.pos(self.value)

    @property
    def env_left(self) -> float:
        return self.geom.pos(self.env_lo)

    @property
    def env_width(self) -> float:
        return self.geom.width(self.env_lo, self.env_hi)

    @property
    def invalid_spans(self) -> list[tuple[float, float]]:
        """(left%, width%) of every region outside the supported envelope."""
        out = []
        left_w = self.geom.pos(self.env_lo)
        if left_w > 0.01:
            out.append((0.0, left_w))
        right_start = self.geom.pos(self.env_hi)
        if right_start < 99.99:
            out.append((right_start, 100.0 - right_start))
        return out


def envelope_geometry(value: float, env_lo: float, env_hi: float,
                      p1: float | None = None, p99: float | None = None,
                      pad_frac: float = 0.12) -> EnvelopeGeometry:
    """
    Build the layout for an applicability rail.

    When the value falls outside the envelope the DOMAIN GROWS to contain it, so the
    marker lands in the hatched region instead of being clamped to the rail end.
    Clamping would conceal exactly the condition the rail exists to show.
    """
    value = float(value)
    env_lo, env_hi = float(env_lo), float(env_hi)
    env_span = max(env_hi - env_lo, 1e-9)
    pad = env_span * pad_frac

    lo = min(env_lo - pad, value - pad * 0.5)
    hi = max(env_hi + pad, value + pad * 0.5)

    extrapolated = value < env_lo or value > env_hi
    sparse = False
    if not extrapolated and p1 is not None and p99 is not None:
        sparse = value < float(p1) or value > float(p99)

    return EnvelopeGeometry(RailGeometry(lo, hi), value, env_lo, env_hi,
                            p1, p99, extrapolated, sparse)


# ════════════════════════════════════════════════════════════════════════
# Shared markup helpers
# ════════════════════════════════════════════════════════════════════════
def _notch(position: float, label: str | None = None) -> str:
    """Threshold marker above the track. Always ink — a boundary, not a reading."""
    lab = (f'<span class="hg-rail__notch-label">{esc(label)}</span>'
           if label else "")
    return (f'<div class="hg-rail__notch" style="left:{position:.3f}%;">'
            f'<span class="hg-rail__notch-tick"></span>{lab}</div>')


def _hatch(left: float, width: float) -> str:
    if width <= 0.01:
        return ""
    return (f'<div class="hg-rail__hatch" '
            f'style="left:{left:.3f}%;width:{width:.3f}%;background:{HATCH_CSS};"></div>')


def _labels(items: list[tuple[float, str, bool]]) -> str:
    """
    Numeric labels beneath the track.

    `primary=False` marks an intermediate label, which the responsive rules drop below
    480px. Endpoints are never dropped — a rail without endpoints is decoration.
    """
    parts = []
    for position, text, primary in items:
        cls = "hg-rail__lab" + ("" if primary else " hg-rail__lab--mid")
        align = ("transform:translateX(0);" if position <= 0.5 else
                 "transform:translateX(-100%);" if position >= 99.5 else
                 "transform:translateX(-50%);")
        parts.append(f'<span class="{cls}" style="left:{position:.3f}%;{align}">'
                     f'{esc(text)}</span>')
    return f'<div class="hg-rail__labels">{"".join(parts)}</div>'


def _wrap(inner: str, aria: str, extra_class: str = "") -> str:
    return (f'<div class="hg-rail {extra_class}" role="img" '
            f'aria-label="{esc(aria)}">{inner}</div>')


# ════════════════════════════════════════════════════════════════════════
# 1. Risk probability
# ════════════════════════════════════════════════════════════════════════
def risk_rail(prob: float, bands: tuple[float, float, float],
              threshold: float, band_key: str,
              animate: bool = True) -> str:
    """
    The hero rail: probability, four band zones, the active threshold as an ink notch.

    `bands` is (low_max, borderline_max, intermediate_max) — the same three boundaries
    the app already uses for classification, passed in rather than recomputed so the
    rail can never disagree with the verdict.
    """
    geom = RailGeometry(0.0, 1.0)
    low_max, border_max, inter_max = bands
    edges = [0.0, float(low_max), float(border_max), float(inter_max), 1.0]
    rail_colour = T.RISK[band_key]["rail"]

    # Band strip: labels only. Filling these zones would compete with the one fill
    # that carries information — the measured value.
    strip = []
    for i, name in enumerate(T.RISK_ORDER):
        a, b = edges[i], edges[i + 1]
        left, width = geom.pos(a), geom.width(a, b)
        if width < 4:
            continue
        active = (name == band_key)
        colour = T.RISK[name]["text"] if active else "var(--hg-text-subtle)"
        weight = T.WEIGHT["semibold"] if active else T.WEIGHT["regular"]
        strip.append(
            f'<span class="hg-rail__band" style="left:{left:.3f}%;width:{width:.3f}%;'
            f'color:{colour};font-weight:{weight};">{name.upper()}</span>')

    # Boundary hairlines through the track.
    ticks = "".join(
        f'<div class="hg-rail__tick" style="left:{geom.pos(e):.3f}%;"></div>'
        for e in edges[1:-1])

    fill_cls = "hg-rail__fill" + (" hg-rail__fill--anim" if animate else "")
    inner = (
        f'{_notch(geom.pos(threshold), "threshold")}'
        f'<div class="hg-rail__strip">{"".join(strip)}</div>'
        f'<div class="hg-rail__track">'
        f'{ticks}'
        f'<div class="{fill_cls}" style="width:{geom.pos(prob):.3f}%;'
        f'background:{rail_colour};"></div>'
        f'<div class="hg-rail__marker" style="left:{geom.pos(prob):.3f}%;'
        f'border-color:{rail_colour};"></div>'
        f'</div>'
        + _labels([
            (0.0, "0%", True),
            (geom.pos(threshold), pct(threshold), False),
            (100.0, "100%", True),
        ])
    )
    aria = (f"Risk {pct(prob)}, band {band_key}, "
            f"action threshold {pct(threshold)}")
    return _wrap(inner, aria, "hg-rail--risk")


# ════════════════════════════════════════════════════════════════════════
# 2. Applicability envelope
# ════════════════════════════════════════════════════════════════════════
def envelope_rail(value: float, env_lo: float, env_hi: float,
                  p1: float | None = None, p99: float | None = None,
                  label: str = "", unit: str = "",
                  fmt=None, compact: bool = False) -> str:
    """
    A patient value against the model's training envelope.

    The clearest expression of the product thesis: a clinician can see they are about
    to extrapolate BEFORE submitting, rather than being told afterwards.
    """
    g = envelope_geometry(value, env_lo, env_hi, p1, p99)
    f = fmt or (lambda v: f"{float(v):g}")

    hatches = "".join(_hatch(left, width) for left, width in g.invalid_spans)

    # p1-p99 shading marks where training support is dense. Distinct from the fill:
    # this is context, not a reading.
    dense = ""
    if p1 is not None and p99 is not None:
        dl, dw = g.geom.pos(float(p1)), g.geom.width(float(p1), float(p99))
        dense = (f'<div class="hg-rail__dense" '
                 f'style="left:{dl:.3f}%;width:{dw:.3f}%;"></div>')

    marker_colour = (T.HAZARD["stripe_b"] if g.extrapolated
                     else T.CSS["warning_text"] if g.sparse
                     else T.CSS["primary"])
    state_cls = ("hg-rail--invalid" if g.extrapolated
                 else "hg-rail--sparse" if g.sparse else "")

    head = ""
    if label:
        state = ("outside supported range" if g.extrapolated
                 else "sparse support" if g.sparse else "")
        badge = (f'<span class="hg-rail__state">{esc(state)}</span>' if state else "")
        head = (f'<div class="hg-rail__head">'
                f'<span class="hg-rail__name">{esc(label)}</span>'
                f'<span class="hg-rail__value">{esc(f(value))}'
                f'{(" " + esc(unit)) if unit else ""}</span>{badge}</div>')

    labels = [(g.env_left, f(env_lo), True), (g.env_left + g.env_width, f(env_hi), True)]
    if not compact:
        labels.append((g.value_pos, f(value), False))

    inner = (
        f'{head}'
        f'<div class="hg-rail__track hg-rail__track--env">'
        f'{hatches}{dense}'
        f'<div class="hg-rail__env" '
        f'style="left:{g.env_left:.3f}%;width:{g.env_width:.3f}%;"></div>'
        f'<div class="hg-rail__marker hg-rail__marker--pin" '
        f'style="left:{g.value_pos:.3f}%;border-color:{marker_colour};"></div>'
        f'</div>'
        + _labels(labels)
    )
    aria = (f"{label or 'Value'} {f(value)}{(' ' + unit) if unit else ''}. "
            f"Supported {f(env_lo)} to {f(env_hi)}. "
            + ("Outside the supported range — extrapolation."
               if g.extrapolated else
               "Beyond the typical range — sparse support." if g.sparse
               else "Within the supported range."))
    return _wrap(inner, aria, f"hg-rail--env {state_cls}")


# ════════════════════════════════════════════════════════════════════════
# 3. Confidence interval
# ════════════════════════════════════════════════════════════════════════
def ci_rail(value: float, ci_lo: float | None, ci_hi: float | None,
            domain: tuple[float, float] = (0.5, 1.0),
            reference: float | None = None, reference_label: str = "overall",
            label: str = "", fmt=None, colour: str | None = None) -> str:
    """
    A point estimate with its 95% interval, and an optional dashed reference.

    Metrics in this product are never shown as a bare point estimate — an AUC of
    0.8000 with an interval of [0.7925, 0.8072] is a different claim from 0.8000 alone,
    and overlapping intervals mean two models are not distinguishable.
    """
    from .format import auc as _auc
    f = fmt or _auc
    g = RailGeometry(*domain)
    c = colour or T.CSS["primary"]

    span = ""
    if ci_lo is not None and ci_hi is not None:
        left, width = g.pos(float(ci_lo)), g.width(float(ci_lo), float(ci_hi))
        span = (f'<div class="hg-rail__ci" '
                f'style="left:{left:.3f}%;width:{width:.3f}%;background:{c};"></div>')

    ref = ""
    if reference is not None:
        ref = (f'<div class="hg-rail__ref" style="left:{g.pos(float(reference)):.3f}%;">'
               f'<span class="hg-rail__ref-label">{esc(reference_label)}</span></div>')

    head = ""
    if label:
        ci_txt = (f' <span class="hg-rail__ci-text">[{f(ci_lo)}–{f(ci_hi)}]</span>'
                  if ci_lo is not None and ci_hi is not None else "")
        head = (f'<div class="hg-rail__head">'
                f'<span class="hg-rail__name">{esc(label)}</span>'
                f'<span class="hg-rail__value">{esc(f(value))}{ci_txt}</span></div>')

    inner = (
        f'{head}'
        f'<div class="hg-rail__track hg-rail__track--ci">'
        f'{ref}{span}'
        f'<div class="hg-rail__marker hg-rail__marker--point" '
        f'style="left:{g.pos(value):.3f}%;background:{c};"></div>'
        f'</div>'
        + _labels([(0.0, f(domain[0]), True), (100.0, f(domain[1]), True)])
    )
    aria = (f"{label or 'Metric'} {f(value)}"
            + (f", 95% confidence interval {f(ci_lo)} to {f(ci_hi)}"
               if ci_lo is not None else "")
            + (f", {reference_label} {f(reference)}" if reference is not None else ""))
    return _wrap(inner, aria, "hg-rail--ci")


# ════════════════════════════════════════════════════════════════════════
# 4. Threshold sweep
# ════════════════════════════════════════════════════════════════════════
def sweep_rail(selected: float, candidates: dict[str, float],
               domain: tuple[float, float] = (0.0, 1.0)) -> str:
    """
    The chosen operating point against every candidate that was considered.

    Shows that the threshold was selected from alternatives rather than asserted —
    Youden, F2 and the legacy 0.50 all appear as ticks so the choice is visibly
    a choice.
    """
    from .format import threshold as _thr
    g = RailGeometry(*domain)

    ticks, labels = [], [(0.0, _thr(domain[0]), True), (100.0, _thr(domain[1]), True)]
    # Filter BEFORE sorting: a None candidate made the sort key comparison raise
    # TypeError, so one missing operating point took the whole rail down. Candidates
    # come straight from results.json, where a degenerate model legitimately yields
    # None for youden_j or f2_optimal.
    usable = [(n, float(v)) for n, v in candidates.items() if v is not None]
    for name, value in sorted(usable, key=lambda kv: kv[1]):
        p = g.pos(float(value))
        is_sel = abs(float(value) - float(selected)) < 1e-9
        cls = "hg-rail__cand" + (" hg-rail__cand--sel" if is_sel else "")
        ticks.append(f'<div class="{cls}" style="left:{p:.3f}%;" '
                     f'title="{esc(name)} {_thr(value)}"></div>')

    inner = (
        f'{_notch(g.pos(selected), "in force")}'
        f'<div class="hg-rail__track hg-rail__track--sweep">'
        f'<div class="hg-rail__fill" style="width:{g.pos(selected):.3f}%;'
        f'background:{T.CSS["primary"]};opacity:.28;"></div>'
        f'{"".join(ticks)}'
        f'</div>'
        + _labels(labels + [(g.pos(selected), _thr(selected), False)])
    )
    aria = (f"Operating threshold {_thr(selected)} selected from "
            f"{len(usable)} candidates")
    return _wrap(inner, aria, "hg-rail--sweep")


# ════════════════════════════════════════════════════════════════════════
# 5. Subgroup comparison
# ════════════════════════════════════════════════════════════════════════
def subgroup_rails(levels: list[dict], overall: float | None = None,
                   domain: tuple[float, float] = (0.55, 0.90),
                   metric: str = "auc") -> str:
    """
    One CI rail per stratum against an overall reference line.

    Stacked rather than charted so each stratum keeps its own numeric label — the
    subgroup finding (AUC 0.65 in the highest-risk cholesterol group) was invisible
    precisely because only the aggregate was ever shown.
    """
    from .format import auc as _auc, count as _count
    rows = []
    for lv in levels:
        value = lv.get(metric)
        if value is None:
            continue
        lo, hi = lv.get(f"{metric}_ci_low"), lv.get(f"{metric}_ci_high")
        strength = ("low" if value >= 0.80 else
                    "borderline" if value >= 0.75 else "high")
        rows.append(
            f'<div class="hg-rail-row">'
            + ci_rail(value, lo, hi, domain=domain,
                      reference=overall, reference_label="overall",
                      label=f'{lv.get("level", "")}  (n={_count(lv.get("n"))})',
                      fmt=_auc, colour=T.RISK[strength]["rail"])
            + '</div>')
    return f'<div class="hg-rail-stack">{"".join(rows)}</div>'


__all__ = [
    "RailGeometry", "EnvelopeGeometry", "envelope_geometry",
    "risk_rail", "envelope_rail", "ci_rail", "sweep_rail", "subgroup_rails",
    "HATCH_CSS",
]
