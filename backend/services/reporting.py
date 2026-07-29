"""
Assessment reports: the session-safe result payload, the clinical PDF and the text
export.

REPORTS ARE REBUILT FROM THE STORED ROW, NOT FROM THE SESSION.
A report is a clinical record. Rebuilding it from the persisted prediction means the
document always reflects what was actually saved, it can be re-downloaded weeks later,
and a stale session cannot produce a PDF that disagrees with the database.
"""
from __future__ import annotations

from backend import config
from backend.domain import artifacts
from backend.domain import risk as risk_domain
from backend.ml import explain
from backend.ml import figures
from backend.ml import pdf
from backend.ml import percentile
from backend.ml import features as fe
from backend.ml import registry
from backend import repositories as db
from backend.services import screening as screening_service
from shared import formatting as fmt

__all__ = ["to_session", "build_pdf", "build_text", "row_to_context"]

_INDICATOR_LABELS = [
    ("age", "Age (years)"), ("gender", "Gender"), ("height", "Height (cm)"),
    ("weight", "Weight (kg)"), ("ap_hi", "Systolic BP (mmHg)"),
    ("ap_lo", "Diastolic BP (mmHg)"), ("cholesterol", "Cholesterol"),
    ("gluc", "Glucose"), ("smoke", "Smoker"), ("alco", "Alcohol"),
    ("active", "Physically active"),
]
_CATEGORICAL = {
    "gender": {1: "Female", 2: "Male", 0: "Female"},
    "cholesterol": {1: "Normal", 2: "Above normal", 3: "Well above normal"},
    "gluc": {1: "Normal", 2: "Above normal", 3: "Well above normal"},
    "smoke": {0: "No", 1: "Yes"}, "alco": {0: "No", 1: "Yes"},
    "active": {0: "No", 1: "Yes"},
}


def display_value(field: str, value) -> str:
    table = _CATEGORICAL.get(field)
    if table:
        try:
            return table.get(int(value), str(value))
        except (TypeError, ValueError):
            return str(value)
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def to_session(result: dict) -> dict:
    """
    Strip a scoring result down to what a session cookie can carry.

    numpy arrays (the scaled feature matrix, the SHAP values) are dropped: they do not
    serialise, and the result page re-derives anything it needs from the stored row.
    """
    keep = ("patient_code", "patient_name", "final_prob", "final_pred", "threshold",
            "band", "band_label", "band_action", "band_edges", "used_label",
            "age_band", "extrapolated", "app_notes", "percentile", "pct_label",
            "pct_n", "link_error", "notes")
    payload = {k: result.get(k) for k in keep}
    payload["inputs"] = result.get("inputs", {})
    payload["app_warn"] = [
        {"label": w["label"], "value": w["value"], "severity": w["severity"],
         "supported": list(w["supported"])}
        for w in result.get("app_warn", [])
    ]
    payload["probs"] = result.get("probs", {})
    payload["member_thresholds"] = result.get("member_thresholds", {})
    sub = result.get("sub_rel") or {}
    payload["sub_rel"] = {k: sub.get(k) for k in ("level", "auc", "n", "ci_low",
                                                  "ci_high")} if sub else None
    payload["thr_meta"] = result.get("thr_meta") or {}
    payload["shap_available"] = result.get("shap") is not None
    payload["counterfactuals"] = result.get("counterfactuals")
    payload["cf_model"] = result.get("cf_model")
    return payload


def row_to_context(pred_id: int, user: dict) -> tuple[dict | None, str | None]:
    """
    Rebuild everything a report needs from one stored prediction.

    Access is checked here rather than in the route: a Doctor may only export their own
    assessments. Doing it at the service boundary means every future caller inherits
    the rule instead of having to remember it.
    """
    rows = db.get_predictions() if user["role"] != "Doctor" \
        else db.get_predictions(user_id=user["id"])
    row = next((r for r in rows if r["id"] == pred_id), None)
    if row is None:
        return None, "assessment not found or not yours to export"

    inputs = {f: row[f] for f, _ in _INDICATOR_LABELS}
    model_used = row.get("model_used") or config.ENSEMBLE_NAME
    threshold = row.get("threshold_used")
    if threshold is None:
        threshold = risk_domain.stratified_threshold(model_used, row["age"])
    prob = float(row["probability"])
    verdict = risk_domain.classify(prob, model_used, active_threshold=threshold)

    return {
        "row": row, "inputs": inputs, "model_used": model_used,
        "threshold": float(threshold), "prob": prob, "verdict": verdict,
        "sub_rel": risk_domain.patient_subgroup_reliability(row["age"], model_used),
        "thr_meta": artifacts.load_thresholds().get("models", {}).get(model_used, {}),
    }, None


def _waterfall(ctx: dict):
    """
    Rebuild the SHAP figure for the PDF.

    Pinned to the light theme: this copy is printed on white A4, and a chart drawn for
    a dark surface exports as near-white on white.
    """
    reg = registry.get_registry()
    models = registry.active_models()
    if not reg.ready or not models:
        return None
    try:
        name, _surrogate = explain.resolve_explainer_model(ctx["model_used"], models)
        model = models.get(name)
        if model is None:
            return None
        features = fe.build_feature_row(**ctx["inputs"])
        scaled = reg.scaler.transform([features])
        names = screening_service.feature_names()
        vals, base, err = explain.explain_patient(model, scaled, names)
        if err:
            return None
        return figures.waterfall_figure(vals, base, names, features, ctx["prob"],
                                   theme="light")
    except Exception:
        return None


def build_pdf(pred_id: int, user: dict) -> tuple[bytes | None, str | None]:
    ctx, error = row_to_context(pred_id, user)
    if error:
        return None, error
    row, thr_meta = ctx["row"], ctx["thr_meta"]
    sub = ctx["sub_rel"] or {}

    def or_zero(value):
        # dict.get with a default returns None when the key is PRESENT and None, which
        # it is for any model whose threshold profile lacks NPV — and the report
        # formats every rate with :.1%.
        return 0.0 if value is None else value

    try:
        # NAMED `peer`, not `percentile`. A local called `percentile` shadows the
        # imported MODULE of that name for the whole function — Python fixes scope at
        # compile time, so `percentile.risk_percentile(...)` on the next line resolved
        # against the local `None` and raised AttributeError. It was swallowed by the
        # except below and returned as a failed report, so every PDF for a
        # non-extrapolated patient silently refused to build.
        peer = None
        if not row.get("extrapolated"):
            value, label, n = percentile.risk_percentile(
                ctx["prob"], row["age"], row["gender"])
            if value is not None:
                peer = {"pct": value, "label": label, "n": n}

        data = pdf.build_pdf_report(
            meta={"patient_id": row.get("patient_ref") or "",
                  "patient_name": row.get("patient_name") or "",
                  "timestamp": row.get("timestamp") or "",
                  "clinician": row.get("doctor_name") or user["fullname"],
                  "role": user["role"],
                  "model": ctx["model_used"],
                  "model_version": row.get("model_version") or ""},
            # A DICT, not a list of pairs — build_pdf_report iterates `.items()`.
            indicators={label: display_value(field, ctx["inputs"][field])
                        for field, label in _INDICATOR_LABELS},
            prediction={"probability": ctx["prob"],
                        "band": ctx["verdict"]["label"],
                        "action": ctx["verdict"]["action"],
                        "model": ctx["model_used"],
                        "version": row.get("model_version") or "",
                        "threshold": ctx["threshold"],
                        "flagged": bool(row.get("predicted_class"))},
            operating={"threshold": ctx["threshold"],
                       "band": row.get("risk_band") or ctx["verdict"]["label"],
                       "sensitivity": or_zero(thr_meta.get("sensitivity")),
                       "specificity": or_zero(thr_meta.get("specificity")),
                       "ppv": or_zero(thr_meta.get("ppv")),
                       "npv": or_zero(thr_meta.get("npv"))},
            # Key names are the report builder's, not this module's: auc_ci_low /
            # auc_ci_high / calibration_gap. Getting one wrong raises a KeyError that a
            # bare `except` would turn into a permanently broken download button.
            reliability={"auc": or_zero(sub.get("auc")),
                         "n": sub.get("n") or 0,
                         "level": sub.get("level") or "",
                         "auc_ci_low": sub.get("ci_low"),
                         "auc_ci_high": sub.get("ci_high"),
                         "calibration_gap": or_zero(sub.get("calibration_gap"))},
            waterfall_fig=_waterfall(ctx),
            counterfactuals=None,
            percentile=peer)
        # The builder hands back a BytesIO. Normalise to bytes here so callers get one
        # predictable type and nobody has to remember which end of the seam they are on.
        return (data.getvalue() if hasattr(data, "getvalue") else data), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def build_text(pred_id: int, user: dict) -> tuple[str | None, str | None]:
    ctx, error = row_to_context(pred_id, user)
    if error:
        return None, error
    row = ctx["row"]
    sub = ctx["sub_rel"] or {}
    rule = "-" * 66

    lines = [
        "HEARTGUARD AI - CARDIOVASCULAR SCREENING REPORT", rule,
        f"Patient code      : {row.get('patient_ref') or '-'}",
        f"Patient name      : {row.get('patient_name') or '-'}",
        f"Assessment date   : {row.get('timestamp') or '-'}",
        f"Assessed by       : {row.get('doctor_name') or user['fullname']} ({user['role']})",
        f"Model             : {ctx['model_used']}  {row.get('model_version') or ''}",
        "", "CLINICAL INDICATORS", rule,
    ]
    lines += [f"{label:<24}: {display_value(field, ctx['inputs'][field])}"
              for field, label in _INDICATOR_LABELS]
    lines += [
        "", "SCREENING RESULT", rule,
        f"{'Estimated risk':<24}: {fmt.pct(ctx['prob'])}",
        f"{'Risk band':<24}: {ctx['verdict']['label']}",
        f"{'Action threshold':<24}: {fmt.threshold(ctx['threshold'])}",
        f"{'Above threshold':<24}: {'yes' if row.get('predicted_class') else 'no'}",
        f"{'Recommended action':<24}: {ctx['verdict']['action']}",
    ]
    if sub.get("auc") is not None:
        lines += ["", "MODEL RELIABILITY FOR THIS PATIENT", rule,
                  f"{'Age band':<24}: {sub.get('level')}",
                  f"{'Discrimination (AUC)':<24}: {fmt.auc(sub.get('auc'))}",
                  f"{'Measured on':<24}: {fmt.count(sub.get('n'))} held-out patients"]
    if row.get("extrapolated"):
        lines += ["", "APPLICABILITY", rule,
                  "One or more indicators fall outside the range the model was fitted",
                  "on. The estimate is an extrapolation and the peer comparison is",
                  "withheld.", f"Detail: {row.get('applicability_notes') or '-'}"]
    if row.get("notes"):
        lines += ["", "CLINICAL NOTES", rule, str(row["notes"])]
    lines += ["", rule,
              "This is a screening aid, not a diagnosis. It estimates risk from",
              "eleven indicators and does not replace clinical judgement.", ""]
    return "\n".join(lines), None
