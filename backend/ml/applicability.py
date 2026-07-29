"""
Is this patient one the model has actually seen?

A risk estimate is only valid for the population the model was fitted on. This module
answers that question BEFORE a score is shown, because a hard extrapolation invalidates
the peer comparison and the care plan, not just the number.

Distinct from `features.validate_physiology`, which rejects impossible measurements.
Extrapolation means "a real patient outside the training range" and earns a caveat;
invalid physiology means "not a possible measurement" and is refused outright.
"""

from __future__ import annotations

import json
import os

from backend.config import MODELS_DIR
from . import features as fe


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


def load_input_ranges():
    path = os.path.join(MODELS_DIR, "input_ranges.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


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
