"""
Per-patient SHAP attribution: why this patient scored what they scored.

The ensemble has no SHAP explainer of its own, so the explanation is produced by a
SURROGATE — a tree model from the same ensemble. `resolve_explainer_model` returns
which model was used and whether it is a surrogate, and the caller is expected to say
so rather than imply the explanation came from the scoring model itself.
"""

from __future__ import annotations

import numpy as np


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
