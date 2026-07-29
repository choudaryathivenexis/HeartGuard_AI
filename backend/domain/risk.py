"""
Clinical risk logic: operating points, risk bands, and the verdict for a probability.

This is the layer that decides what a number MEANS. It holds no Flask, no HTML and no
database access, so it can be reasoned about and tested on its own — which matters more
here than anywhere else in the application, because these are the rules that decide
whether a patient is told to seek further testing.
"""
from __future__ import annotations

from backend import config
from backend.domain import artifacts
from backend.ml import features as fe

__all__ = [
    "risk_threshold", "stratified_threshold", "risk_bands", "classify",
    "subgroup_performance", "patient_subgroup_reliability",
    "BAND_LOW", "BAND_BORDERLINE", "BAND_INTERMEDIATE", "BAND_HIGH", "BAND_ORDER",
]

BAND_LOW = "low"
BAND_BORDERLINE = "borderline"
BAND_INTERMEDIATE = "intermediate"
BAND_HIGH = "high"
BAND_ORDER = [BAND_LOW, BAND_BORDERLINE, BAND_INTERMEDIATE, BAND_HIGH]

BAND_LABELS = {
    BAND_LOW: "LOW RISK",
    BAND_BORDERLINE: "BORDERLINE",
    BAND_INTERMEDIATE: "INTERMEDIATE RISK",
    BAND_HIGH: "HIGH RISK",
}

# Wording is clinical and deliberately avoids diagnostic language. A screening tool
# triages; it does not diagnose, and it never tells a patient they are healthy.
BAND_ACTIONS = {
    BAND_LOW: ("No significant cardiovascular risk pattern detected. "
               "Routine review."),
    BAND_BORDERLINE: ("Below the screening action threshold. Lifestyle advice and "
                      "re-assessment advised."),
    BAND_INTERMEDIATE: ("Above the screening action threshold. Further "
                        "cardiovascular testing indicated."),
    BAND_HIGH: ("Strong cardiovascular risk pattern. Immediate clinical review "
                "advised."),
}


def _override() -> float | None:
    """An administrator's explicit threshold, if one is set. It wins over everything."""
    value = config.get_setting("risk_threshold")
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def risk_threshold(model_name: str = config.ENSEMBLE_NAME) -> float:
    """
    The decision threshold for a model.

    Resolution order: administrator override, then the model's derived operating
    point, then 0.5.

    WHY NOT 0.5. That is the default for a balanced-accuracy objective. This is a
    SCREENING tool — it triages patients into further testing rather than diagnosing
    them, so a missed case costs far more than a false alarm. At 0.50 the model missed
    31% of diseased patients. The shipped thresholds come from the holdout ROC, taken
    as the highest threshold still achieving at least 85% sensitivity, which more than
    halves the miss rate (157 -> 74 per 1,000).
    """
    forced = _override()
    if forced is not None:
        return forced
    models = artifacts.load_thresholds().get("models", {})
    entry = models.get(model_name) or models.get(config.ENSEMBLE_NAME)
    if entry and entry.get("recommended") is not None:
        return float(entry["recommended"])
    return 0.5


def stratified_threshold(model_name: str, age: float) -> float:
    """
    The age-band operating point for this patient.

    WHY AGE-STRATIFIED. Baseline cardiovascular risk runs from 28% under 45 to 65%
    over 60 in this cohort, so a single global cut-point delivers unequal care: 63%
    sensitivity for under-45s, while flagging 95% of over-60s (specificity 0.106 —
    useless as triage). Per-band thresholds equalise sensitivity near 85% across bands
    and restore usable specificity in the older ones. Framingham, SCORE2 and QRISK3 are
    all age-stratified for the same reason.

    An administrator override still wins.
    """
    forced = _override()
    if forced is not None:
        return forced
    strat = artifacts.load_thresholds().get("stratified", {})
    bands = strat.get(model_name) or strat.get(config.ENSEMBLE_NAME) or {}
    for info in bands.values():
        if info.get("age_min", 0) <= age < info.get("age_max", 999):
            return float(info["threshold"])
    return risk_threshold(model_name)


def risk_bands(model_name: str = config.ENSEMBLE_NAME,
               active_threshold: float | None = None) -> tuple[float, float, float]:
    """
    The three cut-points separating the four bands.

    A bare HIGH/LOW verdict throws away most of the clinical information in a
    probability. The bands map to distinct actions:

        Low           below the rule-out point (>=95% sensitivity) — confidently excluded
        Borderline    between rule-out and the action threshold    — monitor / lifestyle
        Intermediate  above the action threshold                   — further testing
        High          above the rule-in point (>=90% specificity)  — escalate

    The middle boundary tracks whatever threshold is actually in force — an override or
    the patient's age-stratified value. Without that, the displayed band can contradict
    the binary verdict sitting next to it.
    """
    models = artifacts.load_thresholds().get("models", {})
    entry = models.get(model_name) or models.get(config.ENSEMBLE_NAME)
    if entry and entry.get("risk_bands"):
        b = entry["risk_bands"]
        low = float(b["low_max"])
        border = float(b["borderline_max"])
        inter = float(b["intermediate_max"])
    else:
        t = risk_threshold(model_name)
        low, border, inter = max(t - 0.15, 0.05), t, min(t + 0.20, 0.95)

    active = (active_threshold if active_threshold is not None
              else risk_threshold(model_name))
    if abs(active - border) > 1e-9:
        border = active
        low = min(low, border)
        inter = max(inter, border)
    return low, border, inter


def classify(prob: float, model_name: str = config.ENSEMBLE_NAME,
             active_threshold: float | None = None) -> dict:
    """
    The full verdict for a probability: band key, display label and recommended action.

    Returns a dict rather than a tuple because call sites read these by name in
    templates. The colour is NOT included: colour is a presentation decision and lives
    in the design tokens, keyed off `band`.
    """
    low, border, inter = risk_bands(model_name, active_threshold)
    if prob < low:
        key = BAND_LOW
    elif prob < border:
        key = BAND_BORDERLINE
    elif prob < inter:
        key = BAND_INTERMEDIATE
    else:
        key = BAND_HIGH
    return {
        "band": key,
        "label": BAND_LABELS[key],
        "action": BAND_ACTIONS[key],
        "bands": (low, border, inter),
    }


def subgroup_performance(model_name: str = config.ENSEMBLE_NAME) -> dict:
    """Measured per-subgroup performance recorded at training time."""
    data = artifacts.load_results(include_virtual=True)
    entry = data.get(model_name) or data.get(config.ENSEMBLE_NAME) or {}
    return entry.get("subgroups", {})


def patient_subgroup_reliability(age: float,
                                 model_name: str = config.ENSEMBLE_NAME) -> dict | None:
    """
    How well the model performs for THIS kind of patient.

    Aggregate AUC hides that discrimination varies from 0.84 (under 45) to 0.73
    (55-59). A clinician cannot calibrate their trust in a score without knowing how
    well it does for the age band in front of them, so the band-level figure is
    surfaced on every result.
    """
    label = fe.age_band_label(age)
    for level in subgroup_performance(model_name).get("Age band", []):
        if level.get("level") == label:
            return level
    return None
