"""
Where this estimate sits among comparable patients.

GATED ON APPLICABILITY by the caller. Ranking against an age-by-sex reference
distribution is meaningless when the patient's age has no stratum — an 82-year-old
would be silently compared against 60-65 year-olds and told they are typical.
"""

from __future__ import annotations

import json
import os

import numpy as np

from backend.config import MODELS_DIR
from . import features as fe


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
