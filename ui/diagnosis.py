"""
The diagnosis page — §7.3, the highest-stakes screen in the application.

Everything here is presentation for one page, so it lives outside components.py for
the same reason ui/login.py does. What it must not do is decide anything: bands,
thresholds, applicability verdicts and counterfactual classifications all arrive
already computed. This module chooses where they sit and how loud they are.

THE ORDERING RULE
    §7.3 fixes a strict vertical priority and forbids visual weight from contradicting
    clinical priority. The extrapolation banner is first, always, never collapsed and
    never dismissible — because a risk figure rendered at 64px is authoritative-looking
    whether or not the model has ever seen a patient like this one, and the only
    defence is that the caveat is read first.

THE VOCABULARY RULE
    §3.10 fixes the clinical language. "Screening result", never "diagnosis". "Further
    testing indicated", never "you have heart disease". "Below the action threshold",
    never "healthy" or "clear". A tool with 0.856 sensitivity misses roughly one
    diseased patient in seven; no copy or colour here may imply otherwise.
"""
from __future__ import annotations

from . import rail as R
from . import tokens as T
from .format import esc, pct, metric3, count, signed_pct

__all__ = [
    "applicability_rails", "counterfactual_panel", "model_breakdown",
    "explainer_disclosure", "peer_percentile", "peer_withheld",
    "CONSTRAINED_FEATURES", "FEATURE_UNITS",
]

# The features the applicability guard constrains. Kept here rather than derived from
# whatever input_ranges.json happens to contain, so a retrain that adds a column
# cannot silently start rendering a rail for a feature the clinician never entered.
CONSTRAINED_FEATURES = ("age", "height", "weight", "ap_hi", "ap_lo", "bmi")

FEATURE_UNITS = {
    "age": "years", "height": "cm", "weight": "kg",
    "ap_hi": "mmHg", "ap_lo": "mmHg", "bmi": "kg/m²",
    "pulse_pressure": "mmHg",
}


# ════════════════════════════════════════════════════════════════════════
# Applicability — the clearest expression of the thesis
# ════════════════════════════════════════════════════════════════════════
def applicability_rails(env: dict, values: dict, labels: dict) -> str:
    """
    One miniature Reference Rail per constrained feature.

    Each shows the training min/max as the domain, the p1–p99 zone as supported
    territory, the hatched shoulders as sparse territory, and this patient's current
    value as the marker. Read as a block it answers the only question that matters
    before submitting: *is this patient one the model has actually seen?*

    `values` holds live widget values, so the markers move as the clinician types.
    This only works because the inputs are NOT inside an st.form — a form withholds
    its widget values until submit, which would render every marker at its default
    position while showing values the clinician had already changed. A marker that
    disagrees with the field above it is worse than no marker.
    """
    feats = (env or {}).get("features") or {}
    rows = []
    for key in CONSTRAINED_FEATURES:
        d = feats.get(key)
        if not d or key not in values:
            continue
        rows.append(
            '<div class="hg-rail-row">'
            + R.envelope_rail(
                float(values[key]),
                float(d["min"]), float(d["max"]),
                p1=float(d["p1"]), p99=float(d["p99"]),
                label=labels.get(key, key),
                unit=FEATURE_UNITS.get(key, ""),
                compact=True)
            + '</div>')
    if not rows:
        return ""
    return f'<div class="hg-rail-stack hg-applic">{"".join(rows)}</div>'


# ════════════════════════════════════════════════════════════════════════
# Counterfactuals
# ════════════════════════════════════════════════════════════════════════
_CF_TONE = {
    "benefit": ("hg-cf--benefit", "moves risk down"),
    "negligible": ("hg-cf--none", "no material change"),
    "paradoxical": ("hg-cf--para", "model limitation"),
}


def counterfactual_panel(rows: list[dict], baseline: float, threshold: float,
                         model_name: str) -> str:
    """
    What would change this patient's score.

    Three presentation rules, each enforcing something the engine already decided:

    1. A `negligible` row shows **no direction and no arrow**. The engine classifies
       anything under its noise floor as immaterial; rendering a signed delta beside
       it would let a clinician read −0.3% as a reason to act.
    2. A `paradoxical` row is labelled a model limitation, never a recommendation. The
       model raising predicted risk for an intervention the evidence says lowers it is
       a fact about the model, and presenting it as advice would be the single most
       dangerous thing this page could do.
    3. Crossing the action threshold is called out explicitly, because that — not the
       size of the delta — is what changes the clinical decision.
    """
    if not rows:
        return ""
    out = []
    for r in rows:
        verdict = r.get("Verdict", "negligible")
        cls, note = _CF_TONE.get(verdict, _CF_TONE["negligible"])
        new = float(r["New risk"])
        crosses = (baseline >= threshold) and (new < threshold)

        if verdict == "negligible":
            # No sign, no arrow, no colour. The engine says this is noise.
            delta_html = '<span class="hg-cf__delta hg-cf__delta--none">—</span>'
        else:
            delta_html = (f'<span class="hg-cf__delta">'
                          f'{esc(signed_pct(r["Change"]))}</span>')

        flag = ('<span class="hg-cf__cross">crosses the action threshold</span>'
                if crosses else "")
        out.append(
            f'<div class="hg-cf__row {cls}">'
            f'<span class="hg-cf__name">{esc(r["Intervention"])}</span>'
            f'<span class="hg-cf__new">{esc(pct(new))}</span>'
            f'{delta_html}'
            f'<span class="hg-cf__note">{esc(note)}{flag}</span>'
            f'</div>')

    para = any(r.get("Verdict") == "paradoxical" for r in rows)
    foot = (
        '<p class="hg-cf__foot">Simulated on the monotonically constrained gradient '
        f'boosting model ({esc(model_name)}), not the ensemble, so a change in a '
        'protective direction cannot register as increased risk through an '
        'unconstrained member. Figures are model estimates for discussion, not '
        'predicted outcomes.</p>')
    if para:
        foot += (
            '<p class="hg-cf__foot hg-cf__foot--warn">Rows marked <b>model '
            'limitation</b> show risk rising for a change that clinical evidence says '
            'should lower it. That is a property of the model, not advice.</p>')

    return (f'<div class="hg-cf">'
            f'<div class="hg-cf__head">'
            f'<span class="hg-cf__name">Change</span>'
            f'<span class="hg-cf__new">New risk</span>'
            f'<span class="hg-cf__delta">Δ</span>'
            f'<span class="hg-cf__note"></span></div>'
            f'{"".join(out)}{foot}</div>')


# ════════════════════════════════════════════════════════════════════════
# Supporting panels
# ════════════════════════════════════════════════════════════════════════
def model_breakdown(probs: dict, preds: dict, thresholds: dict) -> str:
    """
    Each member model's probability against ITS OWN operating point.

    Comparing every model to one shared cut-point was the original BUG-18: models with
    different calibration were being judged by the same number, so "3 of 5 agree" was
    an artifact of the threshold rather than a measure of agreement.
    """
    rows = []
    for name in sorted(probs, key=lambda k: -probs[k]):
        p = probs[name]
        thr = thresholds.get(name, 0.5)
        flagged = preds.get(name) == 1
        rows.append(
            f'<div class="hg-mb__row">'
            f'<span class="hg-mb__dot" style="background:{T.SERIES.get(name, T.SLATE)};"'
            f' aria-hidden="true"></span>'
            f'<span class="hg-mb__name">{esc(name)}</span>'
            f'<span class="hg-mb__p">{esc(pct(p))}</span>'
            f'<span class="hg-mb__thr">at {esc(metric3(thr))}</span>'
            f'<span class="hg-mb__v {"is-flag" if flagged else ""}">'
            f'{"flags" if flagged else "does not flag"}</span>'
            f'</div>')
    return f'<div class="hg-mb">{"".join(rows)}</div>'


def explainer_disclosure(scorer: str, explainer: str, is_surrogate: bool) -> str:
    """
    Say plainly when the explanation does not come from the scoring model.

    A SHAP waterfall captioned as this patient's reasoning, computed on a different
    estimator than the one that produced the number above it, is a quiet lie. The
    engine already reports the substitution; this makes it visible.
    """
    if not is_surrogate:
        return ""
    return (f'<p class="hg-note">Contributions computed on '
            f'<b>{esc(explainer)}</b> as a surrogate — {esc(scorer)} does not expose a '
            f'tractable explainer. The two agree closely in ranking but the magnitudes '
            f'belong to the surrogate.</p>')


def peer_percentile(percentile: int, label: str, n: int) -> str:
    return (f'<div class="hg-peer">'
            f'<span class="hg-peer__k">Peer comparison</span>'
            f'<span class="hg-peer__v">Higher risk than {esc(str(percentile))}% of '
            f'patients in the same group</span>'
            f'<span class="hg-peer__n">{esc(label)} · n={esc(count(n))}</span>'
            f'</div>')


def peer_withheld() -> str:
    """
    An empty slot with a reason, which §7.3 prefers to a number that lies.

    searchsorted against an age×sex reference distribution is meaningless when the
    patient's age has no stratum: an 82-year-old would be ranked against 60–65 year
    olds and told they are typical.
    """
    return ('<div class="hg-peer hg-peer--void">'
            '<span class="hg-peer__k">Peer comparison</span>'
            '<span class="hg-peer__v">Withheld</span>'
            '<span class="hg-peer__n">No reference population for this patient '
            'inside the training envelope.</span></div>')
