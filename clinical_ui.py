"""
HeartGuard FYP — Clinical UI Components
=======================================
Reusable clinical presentation logic: per-patient explanation, counterfactual
simulation, population percentiles and PDF reporting.

Kept out of app.py deliberately — these are testable functions with no Streamlit
dependency except where explicitly noted, so they can be exercised without a browser.
"""

import io
import json
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

import feature_engineering as fe

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")


# ════════════════════════════════════════════════════════════════════════
# Model version identity
# ════════════════════════════════════════════════════════════════════════
def model_version_info():
    """
    Version identity for the currently loaded artifacts.

    Every prediction records this. Without it, retraining silently invalidates the
    interpretation of every historical row — the score stays in the database but the
    model that produced it is gone, so the record cannot be explained or audited.
    """
    path = os.path.join(MODELS_DIR, "manifest.json")
    if not os.path.exists(path):
        return {"version": "unknown", "manifest_sha": "", "trained_at": ""}
    try:
        with open(path) as f:
            m = json.load(f)
        trained = m.get("generated_at", "")
        ds_sha = (m.get("dataset", {}) or {}).get("sha256", "") or ""
        rows = (m.get("dataset", {}) or {}).get("rows_used_for_training", 0)
        # Human-readable, sortable, and tied to the exact data that produced it
        version = f"{trained.replace('-', '').replace(':', '').replace(' ', '-')}"
        return {
            "version": version,
            "manifest_sha": ds_sha[:16],
            "trained_at": trained,
            "rows": rows,
        }
    except Exception:
        return {"version": "unknown", "manifest_sha": "", "trained_at": ""}


# ════════════════════════════════════════════════════════════════════════
# Population percentile
# ════════════════════════════════════════════════════════════════════════
def load_risk_distribution():
    path = os.path.join(MODELS_DIR, "risk_distribution.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_input_ranges():
    path = os.path.join(MODELS_DIR, "input_ranges.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# Fields checked against the training envelope, with clinician-facing names.
# Derived features are included deliberately (BUG-26): every raw input can sit inside
# its own range while their COMBINATION lands far outside anything the model saw.
# 90/180 passes both BP checks individually and yields a pulse pressure of -90 against
# a training range of 5-140.
_ENVELOPE_CHECK = {
    "age": "Age",
    "ap_hi": "Systolic BP",
    "ap_lo": "Diastolic BP",
    "weight": "Weight",
    "height": "Height",
    "bmi": "BMI",
    "pulse_pressure": "Pulse pressure",
}


def check_applicability(inputs):
    """
    Is this patient inside the population the model was fitted on?

    WHY THIS EXISTS
    ---------------
    The input form accepts ages 1-120. The training data spans 30-65. An 82-year-old
    was receiving a confident risk score, an age-stratified threshold, a peer
    percentile and a generated care plan from a model that had never seen anyone over
    65 — with nothing anywhere indicating extrapolation. A risk score is only as valid
    as the population it was estimated on, so scope has to be stated, not assumed.

    Returns (warnings, is_extrapolated) where each warning is a dict with the field,
    the submitted value, the supported range and a severity:

      hard   outside the observed min/max — genuine extrapolation, do not rely on
      soft   inside min/max but beyond the 1st-99th percentile — sparse support
    """
    env = load_input_ranges().get("features", {})
    if not env:
        return [], False

    derived = {
        "bmi": fe.compute_bmi(inputs["weight"], inputs["height"])
        if {"weight", "height"} <= set(inputs) else None,
        "pulse_pressure": (inputs["ap_hi"] - inputs["ap_lo"])
        if {"ap_hi", "ap_lo"} <= set(inputs) else None,
    }
    warnings_out = []
    for field, label in _ENVELOPE_CHECK.items():
        if field not in env:
            continue
        value = derived.get(field, inputs.get(field))
        if value is None:
            continue
        value = float(value)
        r = env[field]
        if value < r["min"] or value > r["max"]:
            warnings_out.append({
                "field": field, "label": label, "value": value,
                "supported": (r["min"], r["max"]), "severity": "hard",
            })
        elif value < r["p1"] or value > r["p99"]:
            warnings_out.append({
                "field": field, "label": label, "value": value,
                "supported": (r["p1"], r["p99"]), "severity": "soft",
            })
    is_extrapolated = any(w["severity"] == "hard" for w in warnings_out)
    return warnings_out, is_extrapolated


def risk_percentile(prob, age, gender):
    """
    Where this risk sits among peers of the same age band and sex.

    Peer-relative rather than cohort-relative on purpose: age dominates absolute risk,
    so comparing a 68-year-old against the whole cohort would say almost nothing about
    whether they are unusual *for their age*.

    Returns (percentile, stratum_label, stratum_n) or (None, None, None).
    """
    dist = load_risk_distribution()
    if not dist:
        return None, None, None
    band = fe.age_band_label(age)
    sex = "Male" if int(gender) == 1 else "Female"
    key = f"{band}|{sex}"
    entry = dist.get("strata", {}).get(key)
    label = f"{band}, {sex.lower()}"
    if entry is None:
        entry = dist.get("strata", {}).get("ALL")
        label = "whole cohort"
    if entry is None:
        return None, None, None
    vals = entry["values"]
    pct = int(np.searchsorted(vals, prob, side="right"))
    return max(1, min(99, pct)), label, entry.get("n", 0)


# ════════════════════════════════════════════════════════════════════════
# Per-patient explanation
# ════════════════════════════════════════════════════════════════════════
# Fast-explainable models. SVM (CalibratedClassifierCV) needs KernelExplainer, which
# is far too slow for an interactive form, so it borrows a tree explanation and the UI
# says so explicitly rather than implying the numbers came from the scoring model.
TREE_MODELS = ["Random Forest", "XGBoost", "Decision Tree"]
MODEL_FILES = {
    "Logistic Regression": "logistic_regression.pkl",
    "Support Vector Machine (SVM)": "svm.pkl",
    "Decision Tree": "decision_tree.pkl",
    "Random Forest": "random_forest.pkl",
    "XGBoost": "xgboost.pkl",
}


def resolve_explainer_model(model_choice, available):
    """
    Which model will provide the explanation, and whether that differs from the scorer.

    Returns (model_name, is_surrogate). A surrogate is used for the ensemble and for
    SVM; the caller must disclose it.
    """
    if model_choice in TREE_MODELS and model_choice in available:
        return model_choice, False
    if model_choice == "Logistic Regression" and model_choice in available:
        return model_choice, False
    for m in TREE_MODELS:
        if m in available:
            return m, True
    return (list(available)[0], True) if available else (None, True)


def explain_patient(model, feats_scaled, feature_names, background=None):
    """
    SHAP values for ONE patient.

    FIXES A LONG-STANDING DEFECT: the diagnosis page previously showed global
    `feature_importances_` — a static, model-level ranking identical for every
    patient — captioned "Top Risk Factors" directly beneath that patient's score.
    It read as personalised reasoning while containing none.

    Returns (shap_values_1d, base_value, error_or_None).
    """
    try:
        import shap
    except ImportError:
        return None, None, "SHAP not installed"

    try:
        if hasattr(model, "feature_importances_"):
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(feats_scaled)
            base = explainer.expected_value
            if isinstance(sv, list):                     # older API: per-class list
                sv, base = sv[1], (base[1] if np.ndim(base) else base)
            sv = np.asarray(sv)
            if sv.ndim == 3:                             # (n, features, classes)
                sv = sv[..., 1]
            row = np.asarray(sv)[0]
            base = float(np.ravel(base)[0]) if np.ndim(base) else float(base)
            return row, base, None

        if hasattr(model, "coef_"):
            bg = background if background is not None else np.zeros_like(feats_scaled)
            explainer = shap.LinearExplainer(model, bg)
            sv = np.asarray(explainer.shap_values(feats_scaled))
            if sv.ndim == 3:
                sv = sv[..., 1]
            base = float(np.ravel(explainer.expected_value)[0])
            return sv[0], base, None

        return None, None, "Model type not fast-explainable"
    except Exception as exc:
        return None, None, str(exc)


def waterfall_figure(shap_row, base_value, feature_names, raw_values,
                     final_prob, top_n=10, unit="mg/dL"):
    """
    Per-patient SHAP waterfall: which of THIS patient's values drove THIS score.

    Contributions are in log-odds (the model's native output space); the probability is
    shown separately rather than implying the bars sum to it, which would be wrong.
    """
    order = np.argsort(np.abs(shap_row))[::-1][:top_n]
    labels, vals, contrib = [], [], []
    for i in order:
        name = feature_names[i]
        raw = raw_values[i]
        if name == "cholesterol":
            shown = fe.ordinal_labels_with_units("cholesterol", unit).get(
                int(raw), str(raw)).split(" (")[0]
        elif name == "gluc":
            shown = fe.ordinal_labels_with_units("gluc", unit).get(
                int(raw), str(raw)).split(" (")[0]
        elif name == "gender":
            shown = "Male" if int(raw) == 1 else "Female"
        elif name in ("smoke", "alco", "active", "high_risk_flag"):
            shown = "Yes" if int(raw) == 1 else "No"
        else:
            shown = f"{raw:g}"
        labels.append(f"{fe.label_for(name)} = {shown}")
        vals.append(raw)
        contrib.append(float(shap_row[i]))

    fig, ax = plt.subplots(figsize=(7.6, max(3.2, 0.42 * len(labels) + 1.1)),
                           facecolor='#0d1117')
    ax.set_facecolor('#161b22')
    colors = ['#ef4444' if c > 0 else '#3b82f6' for c in contrib]
    bars = ax.barh(labels[::-1], contrib[::-1], color=colors[::-1], height=0.62)
    ax.axvline(0, color='#94a3b8', lw=1.1)
    span = max(abs(min(contrib)), abs(max(contrib))) or 1.0
    for bar, c in zip(bars, contrib[::-1]):
        off = span * 0.035
        ax.text(bar.get_width() + (off if c > 0 else -off),
                bar.get_y() + bar.get_height() / 2,
                f"{c:+.3f}", va='center',
                ha='left' if c > 0 else 'right',
                color='#c9d1d9', fontsize=7.6, fontweight='700')
    ax.set_xlim(-span * 1.38, span * 1.38)
    ax.set_xlabel("Contribution to risk (log-odds)  —  red increases, blue decreases",
                  color='#c9d1d9', fontsize=8.4)
    ax.set_title(f"Why this patient scored {final_prob:.1%}",
                 color='#c9d1d9', fontsize=10, fontweight='700', pad=10)
    ax.tick_params(colors='#c9d1d9', labelsize=8)
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_color('#30363d')
    ax.grid(True, axis='x', color='#21262d', ls='--', lw=0.5, alpha=0.6)
    plt.tight_layout()
    return fig


# ════════════════════════════════════════════════════════════════════════
# Counterfactual "what-if" simulation
# ════════════════════════════════════════════════════════════════════════
# Scenarios are restricted to MODIFIABLE risk factors. Offering to change age or sex
# would be meaningless as a care plan, and implying they are adjustable is misleading.
MODIFIABLE = ["weight", "ap_hi", "ap_lo", "smoke", "alco", "active", "cholesterol"]


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


# Changes smaller than this are model wobble, not clinical signal. Reporting a
# direction for them would invite a clinician to act on noise.
NEGLIGIBLE_DELTA = 0.015

# Direction each intervention is expected to move risk, per established cardiovascular
# evidence. Used to detect when the MODEL contradicts clinical consensus so the
# contradiction can be surfaced rather than presented as advice.
EXPECTED_DIRECTION = "decrease"


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


# ════════════════════════════════════════════════════════════════════════
# PDF report
# ════════════════════════════════════════════════════════════════════════
def _pdf_text_page(pdf, title, lines, footer=None):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor='white')   # A4 portrait
    fig.text(0.08, 0.955, "HeartGuard AI", fontsize=19, fontweight='bold',
             color='#b91c1c')
    fig.text(0.08, 0.932, title, fontsize=11.5, color='#334155')
    fig.text(0.08, 0.921, "_" * 92, fontsize=8, color='#cbd5e1')
    y = 0.885
    for line in lines:
        if line.startswith("## "):
            y -= 0.012
            fig.text(0.08, y, line[3:], fontsize=10.5, fontweight='bold',
                     color='#0f172a')
            y -= 0.019
        elif line == "---":
            fig.text(0.08, y + 0.004, "_" * 92, fontsize=8, color='#e2e8f0')
            y -= 0.016
        else:
            fig.text(0.08, y, line, fontsize=8.8, color='#1e293b',
                     family='DejaVu Sans')
            y -= 0.0163
        if y < 0.06:
            break
    if footer:
        fig.text(0.08, 0.032, footer, fontsize=7, color='#64748b')
    pdf.savefig(fig, facecolor='white')
    plt.close(fig)


def build_pdf_report(meta, indicators, prediction, operating, reliability,
                     waterfall_fig=None, counterfactuals=None, percentile=None):
    """
    Multi-page clinical PDF, built with matplotlib's PdfPages.

    matplotlib rather than reportlab/fpdf deliberately: neither is installed, and
    matplotlib is already a hard dependency. Adding a PDF library for one feature
    would break `pip install -r requirements.txt` on a marker's machine for no gain,
    and the SHAP figure is a matplotlib object already — it embeds natively at vector
    quality instead of being rasterised.
    """
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        lines = [
            "## PATIENT",
            f"Patient ID        : {meta.get('patient_id', '')}",
            f"Patient Name      : {meta.get('patient_name', '')}",
            f"Assessment Date   : {meta.get('timestamp', '')}",
            f"Assessed By       : {meta.get('clinician', '')} ({meta.get('role', '')})",
            "---",
            "## CLINICAL INDICATORS",
        ]
        lines += [f"{k:<20}: {v}" for k, v in indicators.items()]
        lines += [
            "---",
            "## AI RISK ASSESSMENT",
            f"{'Model':<20}: {prediction.get('model', '')}",
            f"{'Model Version':<20}: {prediction.get('version', '')}",
            f"{'Risk Probability':<20}: {prediction.get('probability', 0):.2%}",
            f"{'Risk Band':<20}: {prediction.get('band', '')}",
            f"{'Recommendation':<20}: {prediction.get('action', '')}",
        ]
        if percentile:
            lines.append(f"{'Peer Comparison':<20}: higher than "
                         f"{percentile['pct']}% of patients ({percentile['label']})")
        lines += [
            "---",
            "## OPERATING POINT (age-stratified)",
            f"{'Age Band':<20}: {operating.get('band', '')}",
            f"{'Threshold':<20}: {operating.get('threshold', 0):.3f}",
            f"{'Sensitivity':<20}: {operating.get('sensitivity', 0):.1%}",
            f"{'Specificity':<20}: {operating.get('specificity', 0):.1%}",
            f"{'PPV / NPV':<20}: {operating.get('ppv', 0):.1%} / {operating.get('npv', 0):.1%}",
            "",
            "This threshold is tuned for SCREENING sensitivity, not diagnostic",
            "accuracy. It deliberately flags more patients for follow-up in order",
            "to reduce missed cases. A positive result indicates the need for",
            "further testing, NOT the presence of disease.",
        ]
        if reliability:
            lines += [
                "---",
                "## MODEL RELIABILITY FOR THIS PATIENT GROUP",
                f"{'Discrimination':<20}: AUC {reliability.get('auc', 0):.3f}"
                + (f" (95% CI {reliability['auc_ci_low']:.3f}-{reliability['auc_ci_high']:.3f})"
                   if reliability.get('auc_ci_low') is not None else ""),
                f"{'Calibration gap':<20}: {reliability.get('calibration_gap', 0):+.3f}",
                f"{'Measured on':<20}: {reliability.get('n', 0):,} held-out patients",
            ]
            if reliability.get("auc", 1) < 0.75:
                lines += ["",
                          "CAUTION: the model discriminates less well in this age band",
                          "than overall. Weight clinical judgement more heavily."]
        lines += [
            "---",
            "## NOTES",
            meta.get("notes", "") or "None",
        ]
        _pdf_text_page(
            pdf, "Cardiovascular Risk Assessment Report", lines,
            footer=("AI-generated clinical decision support. Not a diagnosis. "
                    "Final determination must be made by a licensed professional."))

        if waterfall_fig is not None:
            waterfall_fig.patch.set_facecolor('white')
            for ax in waterfall_fig.get_axes():
                ax.set_facecolor('white')
                ax.title.set_color('#0f172a')
                ax.xaxis.label.set_color('#334155')
                for t in ax.get_xticklabels() + ax.get_yticklabels():
                    t.set_color('#334155')
                for txt in ax.texts:
                    txt.set_color('#334155')
            pdf.savefig(waterfall_fig, facecolor='white', bbox_inches='tight')

        if counterfactuals:
            cf_lines = ["## MODIFIABLE RISK FACTORS",
                        "Projected effect of each intervention on this patient's",
                        "risk score. Computed by re-scoring the model with the",
                        "indicated value changed; not a clinical guarantee.",
                        "",
                        f"{'Intervention':<34}{'New risk':>10}{'Change':>10}",
                        "-" * 54]
            for r in counterfactuals:
                cf_lines.append(f"{r['Intervention']:<34}{r['New risk']:>9.1%}"
                                f"{r['Change']:>+10.1%}")
            _pdf_text_page(pdf, "Care Planning — What-If Analysis", cf_lines)

        d = pdf.infodict()
        d["Title"] = f"HeartGuard Risk Assessment — {meta.get('patient_id', '')}"
        d["Author"] = meta.get("clinician", "HeartGuard AI")
        d["Subject"] = "Cardiovascular risk assessment (clinical decision support)"
        d["Creator"] = f"HeartGuard AI {prediction.get('version', '')}"

    buf.seek(0)
    return buf
