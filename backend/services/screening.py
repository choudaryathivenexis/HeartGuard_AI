"""
Screening service: score one patient, explain the score, persist the assessment.

This is the clinical core of the application and the one place a prediction is
produced. It takes plain values in and returns a plain dict out — no Flask, no request
object, no HTML — so the same call works from a route, a test, or a future API.

THE ORDER OF THE GUARDS IS THE POINT
    1. identity      — refuse without a patient code and name
    2. physiology    — refuse impossible measurements (90/180 is not a blood pressure)
    3. applicability — WARN on values the model was not fitted on, and score anyway

Two and three are different things and were once conflated. Extrapolation means "a real
patient the model has not seen" and earns a caveat; invalid physiology means "not a
possible measurement" and must be refused outright — it previously returned a confident
LOW RISK verdict.
"""
from __future__ import annotations

import json
import os

import numpy as np

from backend import config
from backend.domain import artifacts
from backend.domain import risk as risk_domain
from backend.ml import applicability
from backend.ml import counterfactuals
from backend.ml import explain
from backend.ml import percentile
from backend.ml import versioning
from backend.ml import features as fe
from backend.ml import registry
from backend import repositories as db

__all__ = ["DIAGNOSTIC_FIELDS", "feature_names", "run_assessment", "model_choices"]

# The eleven clinical indicators the model consumes, in form order.
DIAGNOSTIC_FIELDS = ["age", "gender", "height", "weight", "ap_hi", "ap_lo",
                    "cholesterol", "gluc", "smoke", "alco", "active"]


def feature_names() -> list[str]:
    """Engineered feature names, preferring the list frozen at training time."""
    try:
        path = os.path.join(config.MODELS_DIR, "features.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return list(fe.FEATURE_ORDER)


def model_choices() -> list[str]:
    """Selectable scoring models, ensemble first."""
    return [config.ENSEMBLE_NAME] + list(registry.active_models().keys())


def _explain(inputs: dict, feats_scaled, final_prob: float, model_choice: str,
             scaler, models: dict) -> dict:
    """
    Per-patient SHAP attribution and the counterfactual table.

    Counterfactuals are routed through the MONOTONIC XGBOOST, never the ensemble. That
    is not a preference: XGBoost carries monotone_constraints, so a change in a
    protective direction cannot raise its predicted risk. Averaging it with
    unconstrained members reintroduces exactly the paradoxical rows the constraint
    exists to prevent, and the panel would then report "lower your blood pressure" as
    an increase in risk. With no constrained model available it reports nothing, because
    a paradoxical row is indistinguishable from a real model limitation.
    """
    out = {"shap": None, "shap_error": None, "explainer": None,
           "explainer_surrogate": False, "counterfactuals": None, "cf_model": None}
    names = feature_names()
    try:
        exp_name, surrogate = explain.resolve_explainer_model(model_choice, models)
        out["explainer"], out["explainer_surrogate"] = exp_name, surrogate
        model = models.get(exp_name)
        if model is not None:
            vals, base, err = explain.explain_patient(model, feats_scaled, names)
            if err:
                out["shap_error"] = err
            else:
                out["shap"] = (vals, base)
    except Exception as exc:
        out["shap_error"] = type(exc).__name__

    if "XGBoost" in models:
        out["cf_model"] = "XGBoost"
        try:
            out["counterfactuals"] = counterfactuals.counterfactual_table(
                {"XGBoost": models["XGBoost"]}, scaler, {"XGBoost": 1.0},
                inputs, final_prob)
        except Exception:
            out["counterfactuals"] = None
    return out


def run_assessment(user: dict, values: dict, model_choice: str,
                   notes: str = "", with_explanation: bool = True) -> dict:
    """
    Score a patient and persist the assessment.

    `values` carries the eleven indicators plus `patient_code` and `patient_name`.
    Returns a result dict; on refusal it carries `refused` and `errors` and nothing was
    written to the database.
    """
    code = (values.get("patient_code") or "").strip()
    name = (values.get("patient_name") or "").strip()
    if not code or not name:
        return {"refused": "identity",
                "errors": ["Patient code and patient name are both required."]}

    reg = registry.get_registry()
    models = registry.active_models()
    if not reg.ready or not models:
        return {"refused": "no_model",
                "errors": ["No scoring model is available. Train the models first."]}

    try:
        inputs = {k: values[k] for k in DIAGNOSTIC_FIELDS}
    except KeyError as missing:
        return {"refused": "identity",
                "errors": [f"Missing clinical indicator: {missing.args[0]}"]}

    physiology_errors = fe.validate_physiology(inputs)
    if physiology_errors:
        return {"refused": "physiology", "errors": physiology_errors}

    warnings, extrapolated = applicability.check_applicability(inputs)
    applicability_notes = "; ".join(
        f"{w['label']}={w['value']:g} outside {w['supported'][0]:g}-"
        f"{w['supported'][1]:g} ({w['severity']})" for w in warnings)

    # Engineered features come from the shared module so training and inference cannot
    # drift apart — three divergent copies of this encoding once corrupted every
    # prediction silently.
    feature_row = fe.build_feature_row(**inputs)
    feats_scaled = reg.scaler.transform([feature_row])

    age = inputs["age"]
    probs = {n: float(m.predict_proba(feats_scaled)[0][1]) for n, m in models.items()}
    member_thresholds = {n: risk_domain.stratified_threshold(n, age) for n in probs}
    member_preds = {n: int(p >= member_thresholds[n]) for n, p in probs.items()}

    if config.ENSEMBLE_NAME.split()[0] in model_choice or model_choice not in probs:
        final_prob = float(np.mean(list(probs.values())))
        used = config.ENSEMBLE_NAME
    else:
        final_prob = probs[model_choice]
        used = model_choice

    threshold = risk_domain.stratified_threshold(used, age)
    verdict = risk_domain.classify(final_prob, used, active_threshold=threshold)
    version = versioning.model_version_info()

    # Linking to a patient entity must never be able to lose the assessment: if the
    # upsert fails the prediction is still written, unlinked, with the reason recorded.
    link_error = None
    try:
        patient_ref = db.upsert_patient(code, name, inputs["gender"], user["id"])
    except Exception as exc:
        patient_ref, link_error = None, type(exc).__name__

    db.add_prediction(
        user["id"], inputs["age"], inputs["gender"], inputs["height"],
        inputs["weight"], inputs["ap_hi"], inputs["ap_lo"], inputs["cholesterol"],
        inputs["gluc"], inputs["smoke"], inputs["alco"], inputs["active"],
        int(final_prob >= threshold), final_prob, used, name, notes,
        patient_ref=patient_ref,
        model_version=version["version"],
        model_manifest_sha=version["manifest_sha"],
        threshold_used=threshold,
        risk_band=verdict["label"],
        extrapolated=int(extrapolated),
        applicability_notes=applicability_notes)

    # Peer comparison is GATED on applicability. searchsorted against an age-by-sex
    # reference distribution is meaningless when the patient's age has no stratum: an
    # 82-year-old would be silently ranked against 60-65 year-olds and told they are
    # typical. Withheld rather than approximated.
    # NAMED `pct_value`, not `percentile`. A local called `percentile` shadows the
    # imported MODULE of that name for the whole function, so the very next line
    # resolved `percentile.risk_percentile` against the local `None` and raised
    # AttributeError — crashing every assessment of a patient INSIDE the training
    # range, which is almost all of them.
    pct_value = pct_label = pct_n = None
    if not extrapolated:
        pct_value, pct_label, pct_n = percentile.risk_percentile(
            final_prob, age, inputs["gender"])

    result = {
        "refused": None,
        "inputs": inputs,
        "patient_code": code,
        "patient_name": name,
        "notes": notes,
        "probs": probs,
        "preds": member_preds,
        "member_thresholds": member_thresholds,
        "final_prob": final_prob,
        "final_pred": int(final_prob >= threshold),
        "used_label": used,
        "model_choice": model_choice,
        "threshold": threshold,
        "band": verdict["band"],
        "band_label": verdict["label"],
        "band_action": verdict["action"],
        "band_edges": verdict["bands"],
        "thr_meta": artifacts.load_thresholds().get("models", {}).get(used, {}),
        "sub_rel": risk_domain.patient_subgroup_reliability(age, used),
        "age_band": fe.age_band_label(age),
        "version": version,
        "patient_ref": patient_ref,
        "link_error": link_error,
        "app_warn": warnings,
        "extrapolated": extrapolated,
        "app_notes": applicability_notes,
        "percentile": pct_value,
        "pct_label": pct_label,
        "pct_n": pct_n,
        "features": feature_row,
        "feats_scaled": feats_scaled,
    }
    if with_explanation:
        result.update(_explain(inputs, feats_scaled, final_prob, model_choice,
                               reg.scaler, models))
    return result
