"""
What would change this estimate?

This is what turns a risk score into a care plan: a clinician can see that "BP to 130
plus 5 kg" moves this patient across the action threshold, and discuss that rather than
quoting a percentage.

Every row is classified so the interface never presents a model artifact as advice:

    benefit      risk falls by more than the noise floor
    negligible   change smaller than NEGLIGIBLE_DELTA, no material effect
    paradoxical  risk RISES for an intervention clinical evidence says should lower it,
                 surfaced explicitly as a model limitation and never as a recommendation
"""

from __future__ import annotations

import numpy as np

from . import features as fe


# ════════════════════════════════════════════════════════════════════════
# Counterfactual "what-if" simulation
# ════════════════════════════════════════════════════════════════════════
# Scenarios are restricted to MODIFIABLE risk factors. Offering to change age or sex
# would be meaningless as a care plan, and implying they are adjustable is misleading.
MODIFIABLE = ["weight", "ap_hi", "ap_lo", "smoke", "alco", "active", "cholesterol"]


# Changes smaller than this are model wobble, not clinical signal. Reporting a
# direction for them would invite a clinician to act on noise.
NEGLIGIBLE_DELTA = 0.015


# Direction each intervention is expected to move risk, per established cardiovascular
# evidence. Used to detect when the MODEL contradicts clinical consensus so the
# contradiction can be surfaced rather than presented as advice.
EXPECTED_DIRECTION = "decrease"


def score_variant(models, scaler, weights, base_inputs, overrides):
    """Re-score the patient with some inputs replaced. Returns a probability."""
    merged = dict(base_inputs)
    merged.update(overrides)
    row = fe.build_feature_row(**merged)
    scaled = scaler.transform([row])
    if weights:
        return float(sum(weights.get(n, 0.0) * m.predict_proba(scaled)[0][1]
                         for n, m in models.items()))
    return float(np.mean([m.predict_proba(scaled)[0][1] for m in models.values()]))


def standard_scenarios(base_inputs):
    """
    Clinically standard interventions, each expressed as an input override.

    Only offered when applicable to this patient — proposing "quit smoking" to a
    non-smoker is noise, and proposing a 5 kg loss at BMI 19 is unsafe.

    IMPORTANT — BLOOD PRESSURE SCENARIOS MOVE BOTH VALUES TOGETHER.
    An earlier version offered "diastolic to 80" in isolation. Lowering ap_lo while
    holding ap_hi fixed WIDENS pulse pressure (a derived feature), which the model
    correctly reads as higher risk — so the simulator recommended lowering diastolic
    BP and reported a risk INCREASE. The model was right; the scenario was fiction.
    No antihypertensive lowers diastolic alone. Scenarios now scale both pressures
    together, preserving a physiologically plausible pulse pressure.
    """
    out = []
    w = base_inputs["weight"]
    h = base_inputs["height"]
    bmi = fe.compute_bmi(w, h)
    sbp, dbp = float(base_inputs["ap_hi"]), float(base_inputs["ap_lo"])

    # Recognised clinical BP targets as (systolic, diastolic) PAIRS.
    #
    # An earlier version derived diastolic by holding pulse pressure constant, which
    # produced targets like 130/66 and 120/60 — physiologically odd, and the model
    # scored them non-monotonically (140 appeared to help more than 130). Real
    # antihypertensive therapy lowers both pressures toward a recognised pair, so the
    # scenarios now use those pairs directly: ACC/AHA stage-1 control, the guideline
    # target, and optimal.
    BP_TARGETS = [(140, 85, "140/85 (stage-1 control)"),
                  (130, 80, "130/80 (guideline target)"),
                  (120, 75, "120/75 (optimal)")]

    if bmi > 25 and w - 5 >= 45:
        out.append(("Lose 5 kg", {"weight": w - 5}))
    if bmi > 28 and w - 10 >= 45:
        out.append(("Lose 10 kg", {"weight": w - 10}))
    for t_sbp, t_dbp, tlabel in BP_TARGETS:
        # Only offer a target that is an actual improvement on both components
        if sbp > t_sbp or dbp > t_dbp:
            out.append((f"Blood pressure to {tlabel}",
                        {"ap_hi": float(min(sbp, t_sbp)),
                         "ap_lo": float(min(dbp, t_dbp))}))
    if int(base_inputs["smoke"]) == 1:
        out.append(("Stop smoking", {"smoke": 0}))
    if int(base_inputs["alco"]) == 1:
        out.append(("Stop alcohol", {"alco": 0}))
    if int(base_inputs["active"]) == 0:
        out.append(("Become physically active", {"active": 1}))
    if int(base_inputs["cholesterol"]) > 0:
        out.append(("Cholesterol to normal range", {"cholesterol": 0}))
    return out


def counterfactual_table(models, scaler, weights, base_inputs, baseline_prob):
    """
    Effect of each applicable intervention, individually and combined.

    This is what turns a risk score into a care plan: a clinician can see that
    "BP to 130 plus 5 kg" moves this patient across the action threshold, and discuss
    that rather than quoting a percentage.

    Every row is classified so the UI never presents a model artifact as advice:

      benefit      risk falls by more than the noise floor
      negligible   change smaller than NEGLIGIBLE_DELTA — no material effect
      paradoxical  risk RISES for an intervention clinical evidence says should
                   lower it. Surfaced explicitly as a model limitation, never as a
                   recommendation.
    """
    rows = []
    beneficial = []          # (fieldset, delta, override) for the combined scenario
    for label, ov in standard_scenarios(base_inputs):
        p = score_variant(models, scaler, weights, base_inputs, ov)
        delta = p - baseline_prob
        if abs(delta) < NEGLIGIBLE_DELTA:
            verdict = "negligible"
        elif delta < 0:
            verdict = "benefit"
            beneficial.append((frozenset(ov.keys()), delta, ov))
        else:
            verdict = "paradoxical"
        rows.append({"Intervention": label, "New risk": p,
                     "Change": delta, "Verdict": verdict})

    rows.sort(key=lambda r: r["Change"])

    # Build the combined scenario from MUTUALLY COMPATIBLE interventions only.
    # The blood-pressure targets (140 / 130 / 120) are alternatives, not additive —
    # naively merging them would apply whichever came last and label the result as
    # three stacked improvements. Keep the single best override per field-set.
    best_per_fieldset = {}
    for fields, delta, ov in beneficial:
        if fields not in best_per_fieldset or delta < best_per_fieldset[fields][0]:
            best_per_fieldset[fields] = (delta, ov)

    if len(best_per_fieldset) > 1:
        combined = {}
        for _, ov in best_per_fieldset.values():
            combined.update(ov)
        p = score_variant(models, scaler, weights, base_inputs, combined)
        rows.append({
            "Intervention": f"ALL {len(best_per_fieldset)} combined "
                            f"(best option per risk factor)",
            "New risk": p,
            "Change": p - baseline_prob,
            "Verdict": "benefit" if p < baseline_prob - NEGLIGIBLE_DELTA else "negligible",
        })
    return rows


def sensitivity_curve(models, scaler, weights, base_inputs, field, values):
    """Risk across a swept range of one input — shows where the cliff edges are."""
    return [score_variant(models, scaler, weights, base_inputs, {field: v})
            for v in values]
