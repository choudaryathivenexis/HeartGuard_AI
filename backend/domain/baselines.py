"""
HeartGuard FYP — Clinical Baseline Comparators
==============================================
"AUC 0.80" is meaningless on its own. A clinician's first question is not "how
accurate is it?" but "is it better than what I already use?" This module implements
the comparators needed to answer that.

Three baselines, in increasing sophistication:

  1. bp_staging_score       ACC/AHA 2017 blood-pressure category. The simplest real
                            triage rule — what a nurse does with a BP cuff alone.
  2. framingham_proxy       The Framingham 2008 General CVD equation, adapted to the
                            features this dataset provides. See CAVEATS below.
  3. clinical_logistic      Logistic regression on the seven classic risk factors.
                            This is the FAIR comparison — identical inputs to the ML
                            models, so any difference is attributable to the method
                            rather than to the data.

--------------------------------------------------------------------------
CAVEATS — read before quoting any Framingham number
--------------------------------------------------------------------------
The Framingham implementation here is a PROXY, not the validated instrument. Two
inputs it requires are absent from this dataset and had to be substituted:

  * total cholesterol (mg/dL) — the dataset provides only an ordinal category, so
    each level is mapped to the midpoint of its clinical band (180 / 220 / 260).
    Real within-band variance is lost.
  * HDL cholesterol — absent entirely. Replaced with sex-specific population means.
    Because this is constant within sex, it shifts the score but contributes no
    discriminative information.

Both substitutions HANDICAP the proxy relative to true Framingham. Any margin the ML
models show over it is therefore an upper bound on the real margin, and must be
reported as such. `clinical_logistic` is the comparison to lead with, because it is
handicapped identically.

A third mismatch applies to all baselines: Framingham and SCORE2 estimate 10-year
*incident* cardiovascular risk, whereas this dataset's `cardio` target records
*prevalent* disease at examination. AUC is rank-based so discrimination remains
interpretable, but absolute risk values from the proxy are not calibrated to this
outcome and are not presented as if they were.
"""

import numpy as np
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ── Ordinal cholesterol -> representative total cholesterol (mg/dL) ──────
# Clinical bands: desirable <200, borderline high 200-239, high >=240.
CHOLESTEROL_MGDL_MIDPOINT = {0: 180.0, 1: 220.0, 2: 260.0}

# Population mean HDL by sex (mg/dL). Not in the dataset; constant within sex, so it
# contributes no ranking information — documented in the module docstring.
HDL_MEAN_BY_SEX = {1: 44.0, 0: 55.0}   # 1 = male, 0 = female

# Framingham 2008 General CVD coefficients (D'Agostino et al., Circulation 2008).
FRAMINGHAM = {
    "male": {
        "ln_age": 3.06117, "ln_tc": 1.12370, "ln_hdl": -0.93263,
        "ln_sbp_untreated": 1.93303, "smoker": 0.65451, "diabetes": 0.57367,
        "mean": 23.9802, "s0": 0.88936,
    },
    "female": {
        "ln_age": 2.32888, "ln_tc": 1.20904, "ln_hdl": -0.70833,
        "ln_sbp_untreated": 2.76157, "smoker": 0.52873, "diabetes": 0.69154,
        "mean": 26.1931, "s0": 0.95012,
    },
}

# Classic risk factors a conventional clinical model would use. Deliberately excludes
# the engineered features so this represents "what a clinician-statistician would
# build", not "the ML feature set with a linear model on top".
CLINICAL_RISK_FACTORS = ["age", "gender", "ap_hi", "cholesterol", "gluc",
                         "smoke", "bmi"]


# ════════════════════════════════════════════════════════════════════════
# 1. Blood-pressure staging rule (ACC/AHA 2017)
# ════════════════════════════════════════════════════════════════════════
def bp_staging_score(df):
    """
    Ordinal risk score from blood-pressure category alone.

    0 Normal          <120 / <80
    1 Elevated        120-129 / <80
    2 Stage 1 HTN     130-139 or 80-89
    3 Stage 2 HTN     >=140 or >=90
    4 Hypertensive crisis  >180 or >120

    Included because the ablation analysis showed blood pressure alone accounts for
    the large majority of achievable discrimination. If a single-cuff rule performs
    close to the ML model, that is the finding — and it should be reported, not buried.
    """
    sbp = df["ap_hi"].astype(float)
    dbp = df["ap_lo"].astype(float)
    score = np.zeros(len(df), dtype=float)
    score = np.where((sbp >= 120) & (sbp < 130) & (dbp < 80), 1.0, score)
    score = np.where(((sbp >= 130) & (sbp < 140)) | ((dbp >= 80) & (dbp < 90)),
                     2.0, score)
    score = np.where((sbp >= 140) | (dbp >= 90), 3.0, score)
    score = np.where((sbp > 180) | (dbp > 120), 4.0, score)
    return score


# ════════════════════════════════════════════════════════════════════════
# 2. Framingham 2008 General CVD — proxy implementation
# ════════════════════════════════════════════════════════════════════════
def framingham_proxy(df):
    """
    10-year general CVD risk per Framingham 2008, using substituted lipid inputs.

    Returns a probability in [0, 1]. See module docstring for the substitutions and
    why they handicap this comparator.
    """
    age = df["age"].astype(float).clip(30, 79)     # equation validated 30-74
    sbp = df["ap_hi"].astype(float).clip(90, 200)
    tc = df["cholesterol"].map(CHOLESTEROL_MGDL_MIDPOINT).astype(float)
    male = df["gender"].astype(int) == 1
    hdl = np.where(male, HDL_MEAN_BY_SEX[1], HDL_MEAN_BY_SEX[0])
    smoker = df["smoke"].astype(float)
    # No diabetes field; "well above normal" glucose is the closest available proxy.
    diabetes = (df["gluc"].astype(int) >= 2).astype(float)

    risk = np.zeros(len(df), dtype=float)
    for key, mask in (("male", male.values), ("female", (~male).values)):
        if not mask.any():
            continue
        c = FRAMINGHAM[key]
        lp = (c["ln_age"] * np.log(age.values[mask])
              + c["ln_tc"] * np.log(tc.values[mask])
              + c["ln_hdl"] * np.log(hdl[mask])
              + c["ln_sbp_untreated"] * np.log(sbp.values[mask])
              + c["smoker"] * smoker.values[mask]
              + c["diabetes"] * diabetes.values[mask])
        risk[mask] = 1.0 - np.power(c["s0"], np.exp(lp - c["mean"]))
    return np.clip(risk, 0.0, 1.0)


# ════════════════════════════════════════════════════════════════════════
# 3. Conventional clinical logistic regression
# ════════════════════════════════════════════════════════════════════════
def fit_clinical_logistic(X_train, y_train, features=None):
    """
    Logistic regression on the classic risk factors only.

    THIS IS THE COMPARISON THAT MATTERS. It sees the same data the ML models see (a
    subset, in fact), is handicapped by the same missing lipids, and predicts the same
    outcome — so any AUC difference is attributable to the modelling approach rather
    than to an unfair information advantage.
    """
    feats = [f for f in (features or CLINICAL_RISK_FACTORS) if f in X_train.columns]
    pipe = Pipeline([("scaler", StandardScaler()),
                     ("model", LogisticRegression(max_iter=2000, random_state=42))])
    pipe.fit(X_train[feats], y_train)
    return pipe, feats


# ════════════════════════════════════════════════════════════════════════
# Feature-group ladder for incremental-value analysis
# ════════════════════════════════════════════════════════════════════════
# Groups are ordered the way a clinician acquires them: demographics are free, a BP
# cuff is nearly free, height/weight need a scale, and cholesterol/glucose need a
# blood draw. The marginal AUC of each rung answers "is the next test worth ordering?"
FEATURE_LADDER = [
    ("Demographics only",      ["age", "gender", "age_group"]),
    ("+ Blood pressure",       ["age", "gender", "age_group",
                                "ap_hi", "ap_lo", "pulse_pressure"]),
    ("+ Body metrics",         ["age", "gender", "age_group",
                                "ap_hi", "ap_lo", "pulse_pressure",
                                "height", "weight", "bmi"]),
    ("+ Cholesterol & glucose", ["age", "gender", "age_group",
                                 "ap_hi", "ap_lo", "pulse_pressure",
                                 "height", "weight", "bmi",
                                 "cholesterol", "gluc", "high_risk_flag"]),
    ("+ Lifestyle (all features)", None),   # None => every feature
]


def interaction_features(df):
    """
    Clinically motivated interaction terms.

    Tests whether the linear models are leaving joint effects on the table — risk from
    hypertension plausibly compounds with age and with metabolic burden. Tree models
    can represent these implicitly; logistic regression cannot. If these add nothing,
    that is evidence the ceiling is informational rather than functional.
    """
    out = pd.DataFrame(index=df.index)
    if {"age", "ap_hi"} <= set(df.columns):
        out["age_x_sbp"] = df["age"] * df["ap_hi"] / 100.0
    if {"bmi", "ap_hi"} <= set(df.columns):
        out["bmi_x_sbp"] = df["bmi"] * df["ap_hi"] / 100.0
    if {"cholesterol", "ap_hi"} <= set(df.columns):
        out["chol_x_sbp"] = df["cholesterol"] * df["ap_hi"] / 100.0
    if {"age", "cholesterol"} <= set(df.columns):
        out["age_x_chol"] = df["age"] * df["cholesterol"]
    if {"cholesterol", "gluc"} <= set(df.columns):
        out["metabolic_burden"] = df["cholesterol"] + df["gluc"]
    if {"ap_hi", "ap_lo"} <= set(df.columns):
        # Mean arterial pressure - a standard derived haemodynamic measure
        out["map_mmhg"] = (df["ap_hi"] + 2 * df["ap_lo"]) / 3.0
    return out


# ════════════════════════════════════════════════════════════════════════
# Paired bootstrap test for a difference in AUC
# ════════════════════════════════════════════════════════════════════════
def paired_auc_difference(y_true, prob_a, prob_b, n_boot=500, seed=42):
    """
    Bootstrap CI for AUC(a) - AUC(b) on the SAME patients.

    Pairing matters: comparing two independent CIs is not a test of difference, and
    two overlapping intervals can still correspond to a highly significant paired
    difference. Resampling patients (not predictions) preserves the correlation
    between the two models' errors.

    Returns dict with the observed difference, its 95% CI, and a two-sided p-value
    approximated from the bootstrap distribution.
    """
    from sklearn.metrics import roc_auc_score
    y_true = np.asarray(y_true)
    prob_a = np.asarray(prob_a)
    prob_b = np.asarray(prob_b)
    observed = roc_auc_score(y_true, prob_a) - roc_auc_score(y_true, prob_b)

    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y_true), len(y_true))
        if len(np.unique(y_true[idx])) < 2:
            continue
        diffs.append(roc_auc_score(y_true[idx], prob_a[idx])
                     - roc_auc_score(y_true[idx], prob_b[idx]))
    if not diffs:
        return {"difference": round(float(observed), 6), "ci_low": None,
                "ci_high": None, "p_value": None, "significant": None}

    diffs = np.asarray(diffs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    # Two-sided p from the proportion of bootstrap samples crossing zero
    p = 2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return {
        "difference": round(float(observed), 6),
        "ci_low": round(float(lo), 6),
        "ci_high": round(float(hi), 6),
        "p_value": round(float(min(p, 1.0)), 6),
        "significant": bool(lo > 0 or hi < 0),
    }
