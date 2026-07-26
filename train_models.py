"""
HeartGuard FYP - Professional Model Training Pipeline
======================================================
Preprocessing Steps:
  1. Load & initial inspection
  2. Duplicate row removal          (BEFORE age rounding - see BUG-06)
  3. Age conversion (days -> years)
  4. Physiologically impossible value removal (domain rules, 0-indexed ordinals)
  5. Feature engineering (shared module - single source of truth)
  6. Train / Test split (stratified, 80/20)
  7. Median imputation              (medians from TRAIN split only)
  8. High-correlation feature pruning (correlations from TRAIN split only)
  9. StandardScaler normalization   (fit on TRAIN split only)
 10. Train 5 classifiers with adaptive class weighting
 11. Evaluate on holdout + measure calibration (Brier / ECE)
 12. K-Fold Cross Validation on the TRAINING SPLIT ONLY, via a leak-free Pipeline

Design notes (see TASK.md Run 3 for the evidence behind each):
  * Ordinal columns are 0-indexed in this dataset (0/1/2), NOT 1/2/3.
  * IQR winsorization was REMOVED - the domain filter already bounds every field, and
    clipping on top of it destroyed real clinical signal (181 severe hypertensives with
    an 89% cardio rate were being flattened to the cap).
  * All fitted preprocessing happens AFTER the train/test split. Nothing is fitted on
    data that later appears in the holdout.
  * Class weighting is adaptive: enabled only when the measured imbalance exceeds 1.5x.
"""

import pandas as pd
import numpy as np
import pickle
import os
import json
import time
import hashlib
import platform

from sklearn.base import clone
from sklearn.model_selection import (train_test_split, StratifiedKFold,
                                     cross_validate, cross_val_predict)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.calibration import CalibratedClassifierCV
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, roc_auc_score,
    classification_report, confusion_matrix,
    f1_score, precision_score, recall_score,
    roc_curve, precision_recall_curve, average_precision_score,
    brier_score_loss,
)

import feature_engineering as fe
import clinical_baselines as cb

try:
    from xgboost import XGBClassifier
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Minimum fraction of rows the domain filter must retain. Falling below this means the
# filter rules disagree with the dataset's encoding - which is exactly how BUG-03
# silently destroyed 89.8% of the data for months.
MIN_RETENTION_RATIO = 0.80


# -------------------------------------------------------------
# HELPER - calibration metrics
# -------------------------------------------------------------
def _expected_calibration_error(y_true, y_prob, n_bins=10):
    """
    Expected Calibration Error - mean gap between predicted confidence and observed
    frequency, weighted by bin population. Lower is better; 0 is perfect calibration.
    """
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi if hi < 1.0 else y_prob <= hi)
        if mask.sum():
            ece += mask.mean() * abs(y_true[mask].mean() - y_prob[mask].mean())
    return float(ece)


def _reliability_curve(y_true, y_prob, n_bins=10):
    """Binned (mean predicted, observed frequency) pairs for a reliability diagram."""
    y_true = np.asarray(y_true)
    y_prob = np.asarray(y_prob)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    pred, obs, counts = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi if hi < 1.0 else y_prob <= hi)
        if mask.sum():
            pred.append(round(float(y_prob[mask].mean()), 5))
            obs.append(round(float(y_true[mask].mean()), 5))
            counts.append(int(mask.sum()))
    return {"mean_predicted": pred, "observed_frequency": obs, "count": counts}


# =============================================================
# THRESHOLD SELECTION  (Run 4 - see TASK.md)
# =============================================================
# The app previously classified at a hardcoded 0.50. That is the default for a
# *balanced accuracy* objective, not for a *screening* objective, and on this data it
# missed 31% of diseased patients (sensitivity 0.692).
#
# Screening triages people into further testing; it does not diagnose. A false positive
# costs one follow-up appointment. A false negative sends home someone with undetected
# cardiovascular disease. Those costs are wildly asymmetric, so the operating point must
# be chosen against a clinical objective rather than inherited from argmax convention.
#
# Three operating points are derived per model, directly from the holdout ROC:
#
#   rule_out    highest threshold still achieving >= RULE_OUT_SENSITIVITY.
#               Below it, disease is confidently excluded.
#   recommended highest threshold still achieving >= SCREENING_TARGET_SENSITIVITY.
#               This is the action threshold the app classifies at.
#   rule_in     lowest threshold achieving >= RULE_IN_SPECIFICITY.
#               Above it, disease is likely enough to escalate directly.
#
# Youden's J and F2 are also reported for comparison, and a decision-curve net-benefit
# analysis justifies the choice in the terms a clinical reviewer expects.

SCREENING_TARGET_SENSITIVITY = 0.85   # action threshold - miss no more than ~15%
RULE_OUT_SENSITIVITY         = 0.95   # confident exclusion
RULE_IN_SPECIFICITY          = 0.90   # confident escalation


def _confusion_at(y_true, y_prob, t):
    """Sensitivity / specificity / PPV / NPV at a given probability threshold."""
    y_true = np.asarray(y_true)
    pred = (np.asarray(y_prob) >= t).astype(int)
    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())
    n  = max(len(y_true), 1)
    return {
        "threshold":   round(float(t), 4),
        "sensitivity": round(tp / max(tp + fn, 1), 6),
        "specificity": round(tn / max(tn + fp, 1), 6),
        "ppv":         round(tp / max(tp + fp, 1), 6),
        "npv":         round(tn / max(tn + fn, 1), 6),
        "accuracy":    round((tp + tn) / n, 6),
        "missed_per_1000": round(fn / n * 1000, 1),
        "flagged_rate":    round((tp + fp) / n, 6),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def _threshold_for_sensitivity(y_true, y_prob, target):
    """Highest threshold that still achieves >= target sensitivity."""
    fpr, tpr, thr = roc_curve(y_true, y_prob)
    ok = np.where(tpr >= target)[0]
    if len(ok) == 0:
        return 0.0
    # roc_curve returns thresholds descending; among qualifying points take the largest
    return float(np.clip(thr[ok].max(), 0.0, 1.0))


def _threshold_for_specificity(y_true, y_prob, target):
    """Lowest threshold that achieves >= target specificity."""
    fpr, tpr, thr = roc_curve(y_true, y_prob)
    ok = np.where((1.0 - fpr) >= target)[0]
    if len(ok) == 0:
        return 1.0
    return float(np.clip(thr[ok].min(), 0.0, 1.0))


def _youden_threshold(y_true, y_prob):
    fpr, tpr, thr = roc_curve(y_true, y_prob)
    j = tpr - fpr
    return float(np.clip(thr[int(np.argmax(j))], 0.0, 1.0))


def _fbeta_threshold(y_true, y_prob, beta=2.0):
    """Threshold maximising F-beta; beta=2 weights recall 2x precision."""
    best_t, best_f = 0.5, -1.0
    for t in np.arange(0.05, 0.96, 0.01):
        c = _confusion_at(y_true, y_prob, t)
        p, r = c["ppv"], c["sensitivity"]
        if p + r == 0:
            continue
        f = (1 + beta**2) * p * r / (beta**2 * p + r)
        if f > best_f:
            best_f, best_t = f, float(t)
    return best_t


def _net_benefit(y_true, y_prob, pt):
    """
    Decision-curve net benefit at threshold probability pt (Vickers & Elkin).

        NB = TP/n - (FP/n) * (pt / (1 - pt))

    The odds term encodes how many false positives a clinician will tolerate per true
    positive found. Compared against 'treat all' and 'treat none' strategies.
    """
    if pt <= 0.0 or pt >= 1.0:
        return None
    y_true = np.asarray(y_true)
    pred = (np.asarray(y_prob) >= pt).astype(int)
    n = max(len(y_true), 1)
    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    return round(tp / n - (fp / n) * (pt / (1 - pt)), 6)


def _build_threshold_profile(y_true, y_prob):
    """Full operating-point analysis for one model, persisted into results.json."""
    prevalence = float(np.asarray(y_true).mean())

    t_rule_out    = _threshold_for_sensitivity(y_true, y_prob, RULE_OUT_SENSITIVITY)
    t_recommended = _threshold_for_sensitivity(y_true, y_prob, SCREENING_TARGET_SENSITIVITY)
    t_rule_in     = _threshold_for_specificity(y_true, y_prob, RULE_IN_SPECIFICITY)
    t_youden      = _youden_threshold(y_true, y_prob)
    t_f2          = _fbeta_threshold(y_true, y_prob, beta=2.0)

    # Guard against pathological ordering (can happen on degenerate models)
    if not (t_rule_out <= t_recommended <= t_rule_in):
        t_rule_out    = min(t_rule_out, t_recommended)
        t_rule_in     = max(t_rule_in, t_recommended)

    sweep = [_confusion_at(y_true, y_prob, t) for t in np.arange(0.05, 0.96, 0.01)]

    nb_points = []
    for pt in np.arange(0.05, 0.71, 0.01):
        nb_model = _net_benefit(y_true, y_prob, pt)
        nb_all   = round(prevalence - (1 - prevalence) * (pt / (1 - pt)), 6)
        nb_points.append({
            "pt": round(float(pt), 3),
            "model": nb_model,
            "treat_all": nb_all,
            "treat_none": 0.0,
        })

    return {
        "policy": {
            "criterion": "target_sensitivity",
            "target_sensitivity": SCREENING_TARGET_SENSITIVITY,
            "rule_out_sensitivity": RULE_OUT_SENSITIVITY,
            "rule_in_specificity": RULE_IN_SPECIFICITY,
            "rationale": ("Screening triages patients into further testing rather than "
                          "diagnosing them, so a missed case costs far more than a "
                          "false alarm. The operating point is chosen to bound the "
                          "miss rate, not to maximise accuracy."),
        },
        "operating_points": {
            "rule_out":    _confusion_at(y_true, y_prob, t_rule_out),
            "recommended": _confusion_at(y_true, y_prob, t_recommended),
            "rule_in":     _confusion_at(y_true, y_prob, t_rule_in),
            "youden_j":    _confusion_at(y_true, y_prob, t_youden),
            "f2_optimal":  _confusion_at(y_true, y_prob, t_f2),
            "legacy_half": _confusion_at(y_true, y_prob, 0.50),
        },
        "risk_bands": {
            "low_max":          round(float(t_rule_out), 4),
            "borderline_max":   round(float(t_recommended), 4),
            "intermediate_max": round(float(t_rule_in), 4),
        },
        "sweep": sweep,
        "net_benefit": nb_points,
    }


# =============================================================
# SUBGROUP ANALYSIS  (Run 5)
# =============================================================
# Aggregate AUC hides that discrimination varies substantially across clinical strata.
#
# IMPORTANT INTERPRETATION NOTE, measured and recorded here so nobody re-derives the
# wrong conclusion later: the within-stratum AUC drop on this data is RANGE
# RESTRICTION, not model weakness. Stratifying on a strong predictor removes that
# predictor's variance from within the stratum, so ranking inside a homogeneous group
# is inherently harder. This was tested directly - models trained only on each weak
# stratum performed WORSE than the global model (age 55-60: -0.013, cholesterol
# "well above": -0.033). Building specialist models is therefore the wrong response.
#
# What IS a real defect is applying one threshold to strata whose baseline risk ranges
# from 28% to 76%. At a single global cut-point the model achieved 63% sensitivity
# under 45 while flagging 95% of the over-60s. That is unequal care, and it is fixed
# by stratified operating points rather than by more modelling.

def _bootstrap_auc_ci(y_true, y_prob, n_boot=300, seed=42):
    """Percentile bootstrap CI for AUC - a point estimate alone hides stratum noise."""
    y_true = np.asarray(y_true); y_prob = np.asarray(y_prob)
    if len(np.unique(y_true)) < 2:
        return (None, None)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y_true), len(y_true))
        if len(np.unique(y_true[idx])) > 1:
            vals.append(roc_auc_score(y_true[idx], y_prob[idx]))
    if not vals:
        return (None, None)
    return (round(float(np.percentile(vals, 2.5)), 6),
            round(float(np.percentile(vals, 97.5)), 6))


def _subgroup_report(y_true, y_prob, subgroup_frame, threshold_fn):
    """
    Per-subgroup discrimination, calibration and operating characteristics.

    threshold_fn(row_index_mask) -> the threshold the app would actually apply to
    those patients, so the reported sensitivity/specificity reflect real behaviour
    rather than a hypothetical shared cut-point.
    """
    y_true = np.asarray(y_true); y_prob = np.asarray(y_prob)
    report = {}
    for dim in subgroup_frame.columns:
        levels = []
        for level in sorted(subgroup_frame[dim].dropna().unique().tolist()):
            mask = (subgroup_frame[dim] == level).values
            n = int(mask.sum())
            if n < fe.MIN_SUBGROUP_N or len(np.unique(y_true[mask])) < 2:
                continue
            yy, pp = y_true[mask], y_prob[mask]
            t = threshold_fn(mask)
            c = _confusion_at(yy, pp, t)
            lo, hi = _bootstrap_auc_ci(yy, pp)
            levels.append({
                "level": str(level),
                "n": n,
                "prevalence": round(float(yy.mean()), 6),
                "auc": round(float(roc_auc_score(yy, pp)), 6),
                "auc_ci_low": lo,
                "auc_ci_high": hi,
                "brier": round(float(brier_score_loss(yy, pp)), 6),
                "ece": round(_expected_calibration_error(yy, pp), 6),
                "mean_predicted": round(float(pp.mean()), 6),
                "calibration_gap": round(float(pp.mean() - yy.mean()), 6),
                "threshold_applied": round(float(t), 4),
                "sensitivity": c["sensitivity"],
                "specificity": c["specificity"],
                "ppv": c["ppv"],
                "npv": c["npv"],
                "flagged_rate": c["flagged_rate"],
                "missed_per_1000": c["missed_per_1000"],
            })
        if levels:
            report[dim] = levels
    return report


def _stratified_thresholds(y_true, y_prob, age_values, target):
    """
    One operating point per age band, each achieving the target sensitivity locally.

    Equalises sensitivity across age bands - the 'equal opportunity' fairness
    criterion - and restores usable specificity in the older bands, where a global
    cut-point degenerated into flagging almost everyone.
    """
    y_true = np.asarray(y_true); y_prob = np.asarray(y_prob)
    age_values = np.asarray(age_values)
    out = {}
    for i, (lo, hi, label) in enumerate(fe.AGE_BANDS):
        mask = (age_values >= lo) & (age_values < hi)
        if mask.sum() < fe.MIN_SUBGROUP_N or len(np.unique(y_true[mask])) < 2:
            continue
        t = _threshold_for_sensitivity(y_true[mask], y_prob[mask], target)
        out[label] = {
            "band_index": i,
            "age_min": lo,
            "age_max": hi,
            "threshold": round(float(t), 4),
            "n_derivation": int(mask.sum()),
        }
    return out


# =============================================================
# CLINICAL BENCHMARK & INCREMENTAL FEATURE VALUE  (Run 6)
# =============================================================
# Two questions this pipeline could not previously answer:
#
#   1. "Is it better than what a clinician already uses?"  An AUC with no reference
#      point is uninterpretable. Three comparators are now scored on the same holdout:
#      a Framingham 2008 proxy, an ACC/AHA blood-pressure staging rule, and logistic
#      regression on the seven classic risk factors. The last is the fair comparison -
#      identical inputs, identical handicaps, so any margin is attributable to method.
#
#   2. "Would more modelling help, or more data?"  A feature ladder measures the
#      marginal AUC of each clinical acquisition step, and the recorded ceiling
#      experiments show that neither hyperparameter search (+0.0024) nor interaction
#      terms (-0.0003 on trees) moves the number. The bound is informational.
#
# Both are persisted to models/benchmarks.json and surfaced in the UI, so the honest
# framing travels with the results instead of living only in a report.

def _model_factory():
    """The deployed model family, for ablation runs that must reflect production."""
    if XGB_AVAILABLE:
        return XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                             subsample=0.8, colsample_bytree=0.8,
                             eval_metric="logloss", random_state=42)
    return GradientBoostingClassifier(n_estimators=300, max_depth=5,
                                      learning_rate=0.05, random_state=42)


def _incremental_value_analysis(X_train, y_train, X_test, y_test, all_features):
    """
    Marginal AUC of each clinical acquisition step.

    Groups follow the order a clinician actually obtains them: demographics are free,
    a BP cuff is nearly free, height/weight need a scale, cholesterol and glucose need
    a blood draw. The delta on each rung answers "is the next test worth ordering?"
    """
    rungs = []
    prev_auc = None
    prev_prob = None
    for label, feats in cb.FEATURE_LADDER:
        cols = [c for c in (feats or all_features) if c in X_train.columns]
        if not cols:
            continue
        pipe = Pipeline([("scaler", StandardScaler()), ("model", _model_factory())])
        pipe.fit(X_train[cols], y_train)
        prob = pipe.predict_proba(X_test[cols])[:, 1]
        auc = float(roc_auc_score(y_test, prob))
        lo, hi = _bootstrap_auc_ci(y_test, prob)
        entry = {
            "step": label,
            "n_features": len(cols),
            "features": cols,
            "auc": round(auc, 6),
            "auc_ci_low": lo,
            "auc_ci_high": hi,
            "delta_auc": None if prev_auc is None else round(auc - prev_auc, 6),
        }
        if prev_prob is not None:
            entry["paired_test_vs_previous"] = cb.paired_auc_difference(
                y_test, prob, prev_prob, n_boot=300)
        rungs.append(entry)
        prev_auc, prev_prob = auc, prob
    return rungs


def _baseline_benchmark(X_train, y_train, X_test, y_test, ml_proba):
    """ML model versus the clinical comparators, with paired significance tests."""
    baselines = {}

    bp = cb.bp_staging_score(X_test)
    baselines["BP staging rule (ACC/AHA 2017)"] = {
        "probability_like": bp,
        "note": "Blood-pressure category alone - the simplest real triage rule.",
    }

    fr = cb.framingham_proxy(X_test)
    baselines["Framingham 2008 (proxy)"] = {
        "probability_like": fr,
        "note": ("Framingham general-CVD equation with substituted lipids: ordinal "
                 "cholesterol mapped to band midpoints, HDL replaced by sex-specific "
                 "population means. Both substitutions HANDICAP this comparator, so "
                 "the margin shown against it is an upper bound."),
    }

    clin, clin_feats = cb.fit_clinical_logistic(X_train, y_train)
    cl = clin.predict_proba(X_test[clin_feats])[:, 1]
    baselines["Clinical logistic regression"] = {
        "probability_like": cl,
        "note": ("Logistic regression on the seven classic risk factors "
                 f"({', '.join(clin_feats)}). THE FAIR COMPARISON - same inputs, same "
                 "missing lipids, same outcome, so the difference isolates method."),
    }

    ml_auc = float(roc_auc_score(y_test, ml_proba))
    ml_lo, ml_hi = _bootstrap_auc_ci(y_test, ml_proba)
    out = {
        "ml_model": {
            "name": "HeartGuard ML ensemble",
            "auc": round(ml_auc, 6),
            "auc_ci_low": ml_lo, "auc_ci_high": ml_hi,
        },
        "baselines": {},
    }
    for name, meta in baselines.items():
        prob = meta["probability_like"]
        lo, hi = _bootstrap_auc_ci(y_test, prob)
        out["baselines"][name] = {
            "auc": round(float(roc_auc_score(y_test, prob)), 6),
            "auc_ci_low": lo, "auc_ci_high": hi,
            "note": meta["note"],
            "ml_advantage": cb.paired_auc_difference(y_test, ml_proba, prob,
                                                     n_boot=400),
        }
    return out


def _interaction_test(X_train, y_train, X_test, y_test):
    """
    Does adding clinically motivated interaction terms move the ceiling?

    Trees already represent interactions implicitly, so a null result there is strong
    evidence the functional form is saturated. Logistic regression cannot, so a gain
    there merely confirms the terms are real - it does not raise the ceiling.
    """
    Itr = pd.concat([X_train, cb.interaction_features(X_train)], axis=1)
    Ite = pd.concat([X_test,  cb.interaction_features(X_test)],  axis=1)
    res = {}
    for fam, mk in (("tree", _model_factory),
                    ("linear", lambda: LogisticRegression(max_iter=3000,
                                                          random_state=42))):
        row = {}
        for lbl, a, c in (("base", X_train, X_test), ("with_interactions", Itr, Ite)):
            pipe = Pipeline([("scaler", StandardScaler()), ("model", mk())]).fit(a, y_train)
            row[lbl] = round(float(roc_auc_score(y_test, pipe.predict_proba(c)[:, 1])), 6)
        row["delta"] = round(row["with_interactions"] - row["base"], 6)
        res[fam] = row
    res["interaction_terms"] = list(cb.interaction_features(X_train).columns)
    return res


TUNING_CACHE = os.path.join(MODELS_DIR, "tuning_result.json")


def _load_cached_tuning():
    """
    Last recorded hyperparameter-search result, if one exists.

    The search is not part of normal training (see run_hyperparameter_search), but its
    conclusion is evidence for the ceiling claim, so it travels with the benchmarks.
    """
    if os.path.exists(TUNING_CACHE):
        try:
            with open(TUNING_CACHE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "not run",
            "how_to_run": "python -c \"import train_models as t; t.tune()\""}


def tune(n_iter=40):
    """Run the hyperparameter search standalone and cache the result."""
    df = _load(os.path.join(BASE_DIR, "heart.csv"))
    df = _remove_duplicates(df); df = _basic_clean(df); df = _domain_filter(df)
    base = [c for c in df.columns if c != "cardio"]
    df[base] = df[base].apply(pd.to_numeric, errors="coerce")
    df = fe.engineer_features(df)
    feats = [c for c in df.columns if c != "cardio"]
    X, y = df[feats], df["cardio"].astype(int)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42,
                                         stratify=y)
    res = run_hyperparameter_search(Xtr, ytr, Xte, yte, n_iter=n_iter)
    with open(TUNING_CACHE, "w") as f:
        json.dump(res, f, indent=4)
    print(json.dumps(res, indent=2))
    return res


def run_hyperparameter_search(X_train, y_train, X_test, y_test, n_iter=40):
    """
    Randomised search over the deployed model's hyperparameters.

    NOT run during normal training - it takes ~100s and the measured gain (+0.0024
    AUC) sits well inside the bootstrap CI width (+/-0.007), i.e. it is not
    distinguishable from noise on a single holdout. Retained as a callable so the
    ceiling claim can be re-verified rather than taken on trust, and so the shipped
    hyperparameters can be revisited if the feature set ever changes.
    """
    from sklearn.model_selection import RandomizedSearchCV
    from scipy.stats import loguniform, randint, uniform

    base = Pipeline([("scaler", StandardScaler()), ("model", _model_factory())])
    base.fit(X_train, y_train)
    base_auc = float(roc_auc_score(y_test, base.predict_proba(X_test)[:, 1]))

    if not XGB_AVAILABLE:
        return {"skipped": "XGBoost unavailable", "baseline_auc": round(base_auc, 6)}

    space = {
        "model__n_estimators":     randint(200, 900),
        "model__max_depth":        randint(3, 10),
        "model__learning_rate":    loguniform(0.01, 0.3),
        "model__subsample":        uniform(0.6, 0.4),
        "model__colsample_bytree": uniform(0.6, 0.4),
        "model__min_child_weight": randint(1, 12),
        "model__reg_lambda":       loguniform(0.1, 20),
        "model__gamma":            uniform(0, 3),
    }
    rs = RandomizedSearchCV(
        Pipeline([("scaler", StandardScaler()),
                  ("model", XGBClassifier(eval_metric="logloss", random_state=42))]),
        space, n_iter=n_iter, scoring="roc_auc",
        cv=StratifiedKFold(3, shuffle=True, random_state=42),
        n_jobs=-1, random_state=42)
    t0 = time.time()
    rs.fit(X_train, y_train)
    tuned_auc = float(roc_auc_score(y_test, rs.predict_proba(X_test)[:, 1]))
    return {
        "n_trials": n_iter,
        "search_seconds": round(time.time() - t0, 1),
        "baseline_auc": round(base_auc, 6),
        "tuned_auc": round(tuned_auc, 6),
        "gain": round(tuned_auc - base_auc, 6),
        "best_params": {k.replace("model__", ""): (round(v, 5) if isinstance(v, float) else v)
                        for k, v in rs.best_params_.items()},
        "conclusion": ("Gain lies inside the bootstrap CI width of the AUC estimate, "
                       "so it is not distinguishable from noise. Shipped "
                       "hyperparameters retained for reproducibility."),
    }


# -------------------------------------------------------------
# HELPER - model evaluation
# -------------------------------------------------------------
def _evaluate(model, X_test_scaled, y_test, model_name,
              train_time_s=0.0, pred_time_ms=0.0, oof_proba=None, oof_y=None):
    proba = model.predict_proba(X_test_scaled)[:, 1]

    # Operating point derived from OUT-OF-FOLD TRAINING predictions when available,
    # never from the holdout it is then scored on (Run 5 - closes the Run 4 caveat).
    # Falls back to the holdout only if OOF probabilities were not supplied.
    if oof_proba is not None and oof_y is not None:
        profile = _build_threshold_profile(oof_y, oof_proba)
        profile["derived_from"] = "out-of-fold training predictions"
        # Re-measure the chosen point on the holdout so reported numbers are honest
        op_thresh = profile["operating_points"]["recommended"]["threshold"]
        holdout_pt = _confusion_at(y_test, proba, op_thresh)
        profile["holdout_at_operating_point"] = holdout_pt
    else:
        profile = _build_threshold_profile(y_test, proba)
        profile["derived_from"] = "holdout (no OOF predictions supplied)"
        op_thresh = profile["operating_points"]["recommended"]["threshold"]

    preds = (proba >= op_thresh).astype(int)
    acc   = accuracy_score(y_test, preds)
    auc   = roc_auc_score(y_test, proba)
    f1    = f1_score(y_test, preds)
    prec  = precision_score(y_test, preds)
    rec   = recall_score(y_test, preds)
    cm    = confusion_matrix(y_test, preds).tolist()

    # -- Calibration quality (added Run 3 - see TASK.md D1) --------------
    brier = brier_score_loss(y_test, proba)
    ece   = _expected_calibration_error(y_test, proba)
    mean_pred = float(proba.mean())
    prevalence = float(np.asarray(y_test).mean())

    # -- ROC Curve data (downsampled to 100 pts for compact JSON) --------
    fpr, tpr, _ = roc_curve(y_test, proba)
    step = max(1, len(fpr) // 100)
    roc_data = {"fpr": [round(float(v), 5) for v in fpr[::step]],
                "tpr": [round(float(v), 5) for v in tpr[::step]]}

    # -- Precision-Recall Curve data -------------------------------------
    pr_p, pr_r, _ = precision_recall_curve(y_test, proba)
    avg_prec      = average_precision_score(y_test, proba)
    step_pr = max(1, len(pr_p) // 100)
    pr_data = {"precision": [round(float(v), 5) for v in pr_p[::step_pr]],
               "recall":    [round(float(v), 5) for v in pr_r[::step_pr]],
               "avg_precision": round(float(avg_prec), 6)}

    # Run 7: a bare point estimate invites over-reading. Report the interval.
    _auc_ci = _bootstrap_auc_ci(y_test, proba)
    legacy = profile["operating_points"]["legacy_half"]
    print(f"  [{model_name}] AUC={auc:.4f}  Brier={brier:.4f}  ECE={ece:.4f}")
    print(f"        operating threshold={op_thresh:.3f} -> "
          f"Acc={acc:.4f} Sens={rec:.4f} Spec={profile['operating_points']['recommended']['specificity']:.4f} "
          f"missed/1k={profile['operating_points']['recommended']['missed_per_1000']:.0f}")
    print(f"        (legacy 0.500 would give Sens={legacy['sensitivity']:.4f} "
          f"missed/1k={legacy['missed_per_1000']:.0f})  "
          f"TrainTime={train_time_s:.2f}s PredTime={pred_time_ms:.1f}ms/1k")
    return {
        # Metrics below are computed AT THE OPERATING THRESHOLD - i.e. they describe
        # the app's actual behaviour, not a hypothetical 0.50 cut (Run 4).
        "accuracy":           round(acc,  6),
        "auc":                round(auc,  6),
        "f1":                 round(f1,   6),
        "precision":          round(prec, 6),
        "recall":             round(rec,  6),
        "operating_threshold": round(float(op_thresh), 4),
        "auc_ci_low":         _auc_ci[0],
        "auc_ci_high":        _auc_ci[1],
        "brier":              round(float(brier), 6),
        "ece":                round(ece, 6),
        "mean_predicted":     round(mean_pred, 6),
        "test_prevalence":    round(prevalence, 6),
        "training_time_s":    round(train_time_s, 4),
        "pred_time_ms":       round(pred_time_ms, 4),
        "conf_matrix":        cm,
        "report":             classification_report(y_test, preds, output_dict=True),
        "roc_curve":          roc_data,
        "pr_curve":           pr_data,
        "reliability":        _reliability_curve(y_test, proba),
        "threshold_profile":  profile,
    }


# -------------------------------------------------------------
# HELPER - K-Fold Cross Validation (Stratified, 5-fold)
# -------------------------------------------------------------
KFOLD_N = 5


def _kfold_cv(estimator, X_train_raw, y_train, model_name):
    """
    Leak-free StratifiedKFold CV.

    FIXED (BUG-15): previously this cross-validated over the FULL dataset using a scaler
    that had already been fitted on the training split - so every CV "test" fold was
    scaled with statistics derived from itself, and overlapped the original training
    rows. It was reported in the UI as independent generalisation evidence.

    Now: an unfitted Pipeline(StandardScaler -> estimator) is cross-validated over the
    TRAINING SPLIT ONLY, with the scaler refitted inside each fold.
    """
    skf     = StratifiedKFold(n_splits=KFOLD_N, shuffle=True, random_state=42)
    scoring = {
        "accuracy":  "accuracy",
        "roc_auc":   "roc_auc",
        "f1":        "f1",
        "precision": "precision",
        "recall":    "recall",
    }
    pipe = Pipeline([("scaler", StandardScaler()), ("model", clone(estimator))])
    cv_res = cross_validate(pipe, X_train_raw, y_train,
                            cv=skf, scoring=scoring,
                            return_train_score=False, n_jobs=-1)

    def _fmt(arr): return [round(float(v), 6) for v in arr]

    result = {
        "k": KFOLD_N,
        "scope": "training split only (leak-free pipeline)",
        "folds": {
            "accuracy":  _fmt(cv_res["test_accuracy"]),
            "auc":       _fmt(cv_res["test_roc_auc"]),
            "f1":        _fmt(cv_res["test_f1"]),
            "precision": _fmt(cv_res["test_precision"]),
            "recall":    _fmt(cv_res["test_recall"]),
        },
        "mean": {
            "accuracy":  round(float(cv_res["test_accuracy"].mean()),  6),
            "auc":       round(float(cv_res["test_roc_auc"].mean()),   6),
            "f1":        round(float(cv_res["test_f1"].mean()),        6),
            "precision": round(float(cv_res["test_precision"].mean()), 6),
            "recall":    round(float(cv_res["test_recall"].mean()),    6),
        },
        "std": {
            "accuracy":  round(float(cv_res["test_accuracy"].std()),  6),
            "auc":       round(float(cv_res["test_roc_auc"].std()),   6),
            "f1":        round(float(cv_res["test_f1"].std()),        6),
            "precision": round(float(cv_res["test_precision"].std()), 6),
            "recall":    round(float(cv_res["test_recall"].std()),    6),
        },
    }
    print(f"    K-Fold {KFOLD_N} [{model_name}]  "
          f"Acc={result['mean']['accuracy']:.4f}(+-{result['std']['accuracy']:.4f})  "
          f"AUC={result['mean']['auc']:.4f}(+-{result['std']['auc']:.4f})")
    return result


# -------------------------------------------------------------
# STEP 1 - load dataset
# -------------------------------------------------------------
def _load(data_path):
    df = pd.read_csv(data_path, sep=None, engine="python")
    print(f"  Loaded: {df.shape[0]:,} rows x {df.shape[1]} cols")
    return df


# -------------------------------------------------------------
# STEP 2 - remove duplicate rows
# -------------------------------------------------------------
def _remove_duplicates(df):
    """
    FIXED (BUG-06): this now runs BEFORE the days->years age conversion.

    Rounding age to whole years first collapsed patients who differed only by days into
    identical rows. Measured on heart.csv: 24 genuine duplicates before rounding, 3,821
    after - so 3,797 distinct patients were being deleted as "duplicates".
    """
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    removed = before - len(df)
    print(f"  Duplicates removed: {removed:,}  (remaining: {len(df):,})")
    return df


# -------------------------------------------------------------
# STEP 3 - basic housekeeping
# -------------------------------------------------------------
def _basic_clean(df):
    drop_cols = [c for c in ["Unnamed: 0", "id"] if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    df, converted = fe.convert_age_to_years(df)
    if converted:
        print("  Age converted from days to years.")

    # FIXED (BUG-22): normalise ordinal encoding before the domain filter runs.
    # The retention guardrail alone could not catch a 1-indexed dataset — filtering
    # 1/2/3 data against {0,1,2} costs only ~14% of rows, passing the 80% floor while
    # silently deleting every "well above normal" patient.
    df, enc_notes = fe.normalize_ordinal_encoding(df)
    for note in enc_notes:
        print(f"  {note}")
    if not enc_notes:
        print("  Ordinal encoding already 0-indexed - no shift needed.")

    return df


# -------------------------------------------------------------
# STEP 4 - domain / physiological rules
# -------------------------------------------------------------
def _domain_filter(df):
    """
    FIXED (BUG-03): ordinal columns are validated against {0, 1, 2}, matching this
    dataset's 0-indexed encoding. The previous `.isin([1, 2, 3])` assumed the canonical
    Kaggle encoding and silently discarded 89.8% of all rows - keeping only patients
    with BOTH elevated cholesterol AND elevated glucose, which shifted disease
    prevalence from 50.9% to 65.7% and biased every downstream model.
    """
    before = len(df)
    masks = []

    if "age" in df.columns:
        masks.append((df["age"] >= 1) & (df["age"] <= 120))

    if "ap_hi" in df.columns:
        masks.append((df["ap_hi"] >= 60) & (df["ap_hi"] <= 250))
    if "ap_lo" in df.columns:
        masks.append((df["ap_lo"] >= 40) & (df["ap_lo"] <= 200))
    if "ap_hi" in df.columns and "ap_lo" in df.columns:
        masks.append(df["ap_hi"] > df["ap_lo"])   # systolic must exceed diastolic

    if "height" in df.columns:
        masks.append((df["height"] >= 100) & (df["height"] <= 250))
    if "weight" in df.columns:
        masks.append((df["weight"] >= 20)  & (df["weight"] <= 300))

    # Ordinal severity columns - 0-indexed in this dataset (see feature_engineering.py)
    for col in ["cholesterol", "gluc"]:
        if col in df.columns:
            masks.append(df[col].isin(fe.ORDINAL_VALID_VALUES))

    if masks:
        combined = masks[0]
        for m in masks[1:]:
            combined = combined & m
        df = df[combined].reset_index(drop=True)

    removed = before - len(df)
    retained = len(df) / max(before, 1)
    print(f"  Domain-invalid rows removed: {removed:,}  "
          f"(remaining: {len(df):,}, retained {retained:.1%})")

    # Guardrail: catastrophic attrition means the filter rules disagree with the
    # dataset's encoding. This assertion is what would have caught BUG-03 on day one.
    if retained < MIN_RETENTION_RATIO:
        raise ValueError(
            f"Domain filter retained only {retained:.1%} of rows "
            f"(floor is {MIN_RETENTION_RATIO:.0%}). This almost always means a "
            f"categorical encoding mismatch - check that cholesterol/gluc use the "
            f"0-indexed scale {fe.ORDINAL_VALID_VALUES} expected by this pipeline."
        )
    return df


# -------------------------------------------------------------
# STEP 7 - Median imputation (medians computed on TRAIN only)
# -------------------------------------------------------------
def _fit_median_imputer(X_train):
    """
    FIXED (BUG-13 + BUG-14).

    BUG-13: the old code used `df[col].fillna(med, inplace=True)`, which under pandas 3
    is chained assignment on a temporary copy - a silent no-op that never wrote anything.
    It was hidden by a module-level `warnings.filterwarnings("ignore")`.

    BUG-14: medians were computed over the full dataset before the split, leaking test
    distribution into training. They are now computed on the training split only.
    """
    medians = {}
    missing = X_train.isnull().sum()
    missing = missing[missing > 0]
    if missing.empty:
        print("  No missing values in training split - imputation not required.")
    else:
        for col in missing.index:
            medians[col] = float(X_train[col].median())
            print(f"  Imputer fitted for '{col}': {int(missing[col])} NaNs "
                  f"-> median={medians[col]:.2f}")
    return medians


def _apply_median_imputer(X, medians):
    if not medians:
        return X
    X = X.copy()
    for col, med in medians.items():
        if col in X.columns:
            X[col] = X[col].fillna(med)   # explicit assignment - works under pandas 3
    return X


# -------------------------------------------------------------
# STEP 8 - Drop highly correlated features  (|r| >= 0.90)
# -------------------------------------------------------------
def _drop_high_correlation(X_train, feature_cols, threshold=0.90):
    """
    FIXED (BUG-14): correlations are computed on the TRAINING SPLIT only. Previously
    this ran on the full dataset, so feature selection was informed by the holdout.
    """
    corr_matrix = X_train[feature_cols].corr().abs()
    upper_tri   = corr_matrix.where(
        np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
    )
    to_drop = [col for col in upper_tri.columns
               if any(upper_tri[col] >= threshold)]
    if to_drop:
        print(f"  High-correlation features dropped (|r|>={threshold}): {to_drop}")
        feature_cols = [c for c in feature_cols if c not in to_drop]
    else:
        print(f"  No features dropped by correlation threshold ({threshold}).")
    return feature_cols


# -------------------------------------------------------------
# Provenance manifest
# -------------------------------------------------------------
def _sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _write_manifest(data_path, feature_cols, rows_used, prevalence, class_weight_mode):
    """
    Artifact provenance (addresses CONTEXT.md M7).

    Records exactly which dataset, library versions and settings produced the artifacts
    now sitting in models/, and a SHA-256 digest for each. The digests are also what
    the Backup & Restore page verifies against before accepting an uploaded archive.
    """
    import sklearn
    artifacts = {}
    for fname in sorted(os.listdir(MODELS_DIR)):
        fpath = os.path.join(MODELS_DIR, fname)
        if os.path.isfile(fpath) and fname != "manifest.json":
            artifacts[fname] = {
                "sha256": _sha256(fpath),
                "bytes": os.path.getsize(fpath),
            }

    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": {
            "path": os.path.basename(data_path),
            "sha256": _sha256(data_path) if os.path.exists(data_path) else None,
            "rows_used_for_training": rows_used,
            "class_prevalence": round(prevalence, 6),
        },
        "features": {
            "order": feature_cols,
            "count": len(feature_cols),
            "encoding": "cholesterol/gluc are 0-indexed (0=normal, 1=above, 2=well above)",
        },
        "training": {
            "class_weight_mode": class_weight_mode,
            "test_size": 0.2,
            "random_state": 42,
            "kfold": KFOLD_N,
        },
        "environment": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "xgboost_available": XGB_AVAILABLE,
        },
        "artifacts": artifacts,
    }
    with open(os.path.join(MODELS_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=4)
    return manifest


# -------------------------------------------------------------
# MAIN - train_all()
# -------------------------------------------------------------
def train_all(data_path=None):
    t0 = time.time()
    report_lines = []

    def log(msg):
        print(msg)
        report_lines.append(msg)

    # -- resolve dataset --------------------------------------
    if data_path is None:
        custom    = os.path.join(BASE_DIR, "custom_dataset.csv")
        data_path = custom if os.path.exists(custom) else \
                    os.path.join(BASE_DIR, "heart.csv")
    log("\n" + "=" * 60)
    log(" HeartGuard - Professional Preprocessing Pipeline")
    log("=" * 60)
    log(f"\n[STEP 1] Loading dataset: {data_path}")
    df = _load(data_path)
    rows_original = len(df)

    log("\n[STEP 2] Removing duplicate rows (before age rounding)")
    df = _remove_duplicates(df)

    log("\n[STEP 3] Basic housekeeping")
    df = _basic_clean(df)

    log("\n[STEP 4] Applying physiological domain filters")
    df = _domain_filter(df)

    # Determine target column
    target_col   = "cardio" if "cardio" in df.columns else "target"
    base_cols    = [c for c in df.columns if c != target_col]

    # Convert to numeric
    df[base_cols] = df[base_cols].apply(pd.to_numeric, errors="coerce")

    log("\n[STEP 5] Feature engineering (shared module)")
    df = fe.engineer_features(df)
    feature_cols = [c for c in df.columns if c != target_col]
    log(f"  Engineered features added: {[c for c in fe.ENGINEERED if c in df.columns]}")

    log("\n  NOTE: IQR winsorization intentionally removed this run.")
    log("  The domain filter already bounds every field to a clinically plausible range;")
    log("  clipping on top of it flattened 181 severe hypertensives (89% cardio rate)")
    log("  onto the cap, destroying the strongest signal in the dataset. (BUG-07)")

    X_all = df[feature_cols]
    y     = df[target_col].astype(int)

    log("\n" + "-" * 60)
    log(" Dataset after preprocessing:")
    log(f"   Rows  : {rows_original:,} -> {len(df):,} "
        f"({len(df)/max(rows_original,1):.1%} retained)")
    class_counts = y.value_counts().to_dict()
    log(f"   Class distribution: {class_counts}")
    imbalance_ratio = max(class_counts.values()) / max(min(class_counts.values()), 1)

    # -- Adaptive class weighting (design decision D2 in TASK.md) --------
    use_class_weight  = imbalance_ratio > 1.5
    class_weight      = "balanced" if use_class_weight else None
    class_weight_mode = f"balanced (imbalance {imbalance_ratio:.2f}x > 1.5x)" \
        if use_class_weight else f"none (imbalance {imbalance_ratio:.2f}x <= 1.5x, data is balanced)"
    log(f"   Class imbalance ratio: {imbalance_ratio:.2f}x")
    log(f"   Class weighting: {class_weight_mode}")
    log("-" * 60)

    # -- Train / Test split (EVERYTHING fitted comes after this) ---------
    log("\n[STEP 6] Train/Test split (80/20, stratified)")
    X_train_raw, X_test_raw, y_train, y_test = train_test_split(
        X_all, y, test_size=0.2, random_state=42, stratify=y
    )
    log(f"  Train: {len(X_train_raw):,}  |  Test: {len(X_test_raw):,}")

    log("\n[STEP 7] Median imputation (medians fitted on TRAIN split only)")
    medians = _fit_median_imputer(X_train_raw)
    X_train_raw = _apply_median_imputer(X_train_raw, medians)
    X_test_raw  = _apply_median_imputer(X_test_raw,  medians)

    log("\n[STEP 8] Correlation-based feature pruning (TRAIN split only)")
    feature_cols = _drop_high_correlation(X_train_raw, feature_cols, threshold=0.90)
    X_train_raw = X_train_raw[feature_cols]
    X_test_raw  = X_test_raw[feature_cols]
    log(f"  Features used : {len(feature_cols)} -> {feature_cols}")

    # Run 7: clinical direction constraints. Established evidence fixes the sign of
    # several risk factors; an unconstrained ensemble violated that (6/20 inversions
    # on a systolic sweep) and the counterfactual simulator turned those inversions
    # into care advice. Constraining costs ~0.0001 AUC.
    # Applied to XGBoost only. scikit-learn's monotonic_cst was measured on the tree
    # models too and was NOT free there: it cost Random Forest 0.011 AUC and, worse,
    # inflated its calibration error 8.5x (ECE 0.011 -> 0.093). Calibration is the
    # property this system depends on most, so RF and DT remain unconstrained and
    # XGBoost - where the constraint is free - becomes the clinically coherent model.
    mono = fe.monotonic_constraint_vector(feature_cols)
    log(f"  Monotonic constraints (XGBoost): "
        f"{sum(1 for v in mono if v)} of {len(mono)} features directionally constrained")

    # -- Scaling (fit on TRAIN only) -------------------------------------
    log("\n[STEP 9] StandardScaler normalization (fit on TRAIN split only)")
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train_raw)
    X_test_s  = scaler.transform(X_test_raw)

    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)
    with open(os.path.join(MODELS_DIR, "features.json"), "w") as f:
        json.dump(feature_cols, f)
    with open(os.path.join(MODELS_DIR, "imputer_medians.json"), "w") as f:
        json.dump(medians, f)
    log("  Scaler, feature list & imputer medians saved.")

    # -- Out-of-fold probabilities for unbiased threshold selection --------
    # Run 5: thresholds must not be chosen on the data they are then scored on.
    # cross_val_predict giveseach training row a prediction from a model that never saw
    # it, so operating points are selected honestly and the holdout stays untouched.
    log("\n[STEP 10] Generating out-of-fold predictions for threshold selection")
    log("  (thresholds are chosen on OOF training data, never on the holdout)")

    def _oof(estimator):
        pipe = Pipeline([("scaler", StandardScaler()), ("model", clone(estimator))])
        skf = StratifiedKFold(n_splits=KFOLD_N, shuffle=True, random_state=42)
        return cross_val_predict(pipe, X_train_raw, y_train, cv=skf,
                                 method="predict_proba", n_jobs=-1)[:, 1]

    # -- Model training ---------------------------------------
    log("\n[STEP 11] Training classifiers")
    results = {}
    estimators = {}
    oof_store = {}

    # 1. Logistic Regression
    log("  [1/5] Logistic Regression")
    lr = LogisticRegression(
        max_iter=2000, C=1.0, class_weight=class_weight, random_state=42
    )
    _t0 = time.time(); lr.fit(X_train_s, y_train); _train_t = time.time() - _t0
    _t0 = time.time(); lr.predict_proba(X_test_s[:1000]); _pred_t = (time.time()-_t0)*1000
    with open(os.path.join(MODELS_DIR, "logistic_regression.pkl"), "wb") as f:
        pickle.dump(lr, f)
    oof_store["Logistic Regression"] = _oof(lr)
    results["Logistic Regression"] = _evaluate(lr, X_test_s, y_test, "LR",
                                               _train_t, _pred_t,
                                       oof_proba=oof_store["Logistic Regression"], oof_y=y_train)
    estimators["Logistic Regression"] = lr

    # 2. SVM
    log("  [2/5] Support Vector Machine")
    svm_base = LinearSVC(max_iter=3000, C=1.0, class_weight=class_weight, random_state=42)
    svm = CalibratedClassifierCV(svm_base, cv=3)
    _t0 = time.time(); svm.fit(X_train_s, y_train); _train_t = time.time() - _t0
    _t0 = time.time(); svm.predict_proba(X_test_s[:1000]); _pred_t = (time.time()-_t0)*1000
    with open(os.path.join(MODELS_DIR, "svm.pkl"), "wb") as f:
        pickle.dump(svm, f)
    oof_store["Support Vector Machine (SVM)"] = _oof(svm)
    results["Support Vector Machine (SVM)"] = _evaluate(svm, X_test_s, y_test, "SVM",
                                                        _train_t, _pred_t,
                                       oof_proba=oof_store["Support Vector Machine (SVM)"], oof_y=y_train)
    estimators["Support Vector Machine (SVM)"] = svm

    # 3. Decision Tree
    log("  [3/5] Decision Tree")
    dt = DecisionTreeClassifier(
        max_depth=7, min_samples_split=20,
        class_weight=class_weight, random_state=42
    )
    _t0 = time.time(); dt.fit(X_train_s, y_train); _train_t = time.time() - _t0
    _t0 = time.time(); dt.predict_proba(X_test_s[:1000]); _pred_t = (time.time()-_t0)*1000
    with open(os.path.join(MODELS_DIR, "decision_tree.pkl"), "wb") as f:
        pickle.dump(dt, f)
    oof_store["Decision Tree"] = _oof(dt)
    results["Decision Tree"] = _evaluate(dt, X_test_s, y_test, "DT",
                                         _train_t, _pred_t,
                                       oof_proba=oof_store["Decision Tree"], oof_y=y_train)
    estimators["Decision Tree"] = dt

    # 4. Random Forest
    log("  [4/5] Random Forest")
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=12,
        min_samples_split=10, class_weight=class_weight,
        random_state=42, n_jobs=-1
    )
    _t0 = time.time(); rf.fit(X_train_s, y_train); _train_t = time.time() - _t0
    _t0 = time.time(); rf.predict_proba(X_test_s[:1000]); _pred_t = (time.time()-_t0)*1000
    with open(os.path.join(MODELS_DIR, "random_forest.pkl"), "wb") as f:
        pickle.dump(rf, f)
    oof_store["Random Forest"] = _oof(rf)
    results["Random Forest"] = _evaluate(rf, X_test_s, y_test, "RF",
                                         _train_t, _pred_t,
                                       oof_proba=oof_store["Random Forest"], oof_y=y_train)
    estimators["Random Forest"] = rf

    # 5. XGBoost / GradientBoosting
    log("  [5/5] XGBoost")
    neg  = int((y_train == 0).sum())
    pos  = int((y_train == 1).sum())
    # Adaptive, consistent with the other four models (design decision D2).
    scale_pw = (neg / max(pos, 1)) if use_class_weight else 1.0

    if XGB_AVAILABLE:
        xgb = XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            scale_pos_weight=scale_pw,
            eval_metric="logloss",
            monotone_constraints=mono,
            random_state=42,
        )
    else:
        log("    (XGBoost not installed -> using GradientBoostingClassifier)")
        xgb = GradientBoostingClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05, random_state=42
        )
    _t0 = time.time(); xgb.fit(X_train_s, y_train); _train_t = time.time() - _t0
    _t0 = time.time(); xgb.predict_proba(X_test_s[:1000]); _pred_t = (time.time()-_t0)*1000
    with open(os.path.join(MODELS_DIR, "xgboost.pkl"), "wb") as f:
        pickle.dump(xgb, f)
    oof_store["XGBoost"] = _oof(xgb)
    results["XGBoost"] = _evaluate(xgb, X_test_s, y_test, "XGB", _train_t, _pred_t,
                                       oof_proba=oof_store["XGBoost"], oof_y=y_train)
    results["XGBoost"]["is_fallback"] = not XGB_AVAILABLE
    # Flag consumed by the app: only a directionally-constrained model may drive the
    # counterfactual simulator, because that feature converts model gradients into
    # care advice and a non-monotonic gradient becomes harmful advice.
    results["XGBoost"]["monotonic"] = bool(XGB_AVAILABLE)
    results["XGBoost"]["monotonic_constraints"] = {
        f: int(v) for f, v in zip(feature_cols, mono) if v}
    estimators["XGBoost"] = xgb

    # -- Step 11: K-Fold Cross Validation (leak-free) ---------------------
    log(f"\n[STEP 11] {KFOLD_N}-Fold Stratified CV on the TRAINING SPLIT ONLY")
    log("  (Pipeline refits the scaler inside every fold - no preprocessing leakage)")

    cv_targets = list(estimators.items())
    for mname, mobj in cv_targets:
        log(f"  CV: {mname}")
        try:
            results[mname]["kfold_cv"] = _kfold_cv(
                mobj, X_train_raw, y_train.values, mname[:3]
            )
        except Exception as cv_err:
            log(f"    WARNING: CV failed for {mname}: {cv_err}")
            results[mname]["kfold_cv"] = None

    # -- Step 12: Ensemble operating point ---------------------
    # The app's default model is "Ensemble Voting" (mean of active model probabilities),
    # which has its own probability distribution and therefore needs its own threshold.
    # Deriving it from the same holdout keeps the app's default path honest.
    log("\n[STEP 12] Deriving ensemble operating point")
    # ── Ensemble weighting (Run 7) ──────────────────────────────────────
    # Previously an unweighted mean, which assumes every member is equally good and
    # equally calibrated. Weights are now proportional to each model's OOF skill above
    # chance (AUC - 0.5), so a weak member cannot drag the ensemble down as hard.
    # Weights come from OOF predictions, never from the holdout the ensemble is scored on.
    oof_auc = {m: float(roc_auc_score(y_train, oof_store[m])) for m in estimators}
    skill = {m: max(a - 0.5, 1e-6) for m, a in oof_auc.items()}
    total_skill = sum(skill.values())
    ens_weights = {m: skill[m] / total_skill for m in estimators}
    log("  Ensemble weights (proportional to OOF skill above chance):")
    for m in estimators:
        log(f"    {m:32s} OOF_AUC={oof_auc[m]:.4f}  weight={ens_weights[m]:.4f}")

    _member_test = {m: mo.predict_proba(X_test_s)[:, 1] for m, mo in estimators.items()}
    ens_proba = np.sum([ens_weights[m] * _member_test[m] for m in estimators], axis=0)
    _ens_unweighted = np.mean([_member_test[m] for m in estimators], axis=0)
    log(f"  Weighted AUC={roc_auc_score(y_test, ens_proba):.4f}  "
        f"vs unweighted={roc_auc_score(y_test, _ens_unweighted):.4f}")
    # Threshold derived on OOF training predictions, then MEASURED on the holdout,
    # so the reported operating characteristics are unbiased (Run 5).
    oof_ens = np.sum([ens_weights[m] * oof_store[m] for m in estimators], axis=0)
    ens_profile = _build_threshold_profile(y_train.values, oof_ens)
    ens_profile["derived_from"] = "out-of-fold training predictions"
    ens_thresh = ens_profile["operating_points"]["recommended"]["threshold"]
    ens_holdout = _confusion_at(y_test, ens_proba, ens_thresh)
    ens_profile["holdout_at_operating_point"] = ens_holdout
    # Top-level metrics describe HOLDOUT behaviour at the derived threshold.
    ens_op = ens_holdout
    results["Ensemble Voting"] = {
        "accuracy":            ens_op["accuracy"],
        "auc":                 round(float(roc_auc_score(y_test, ens_proba)), 6),
        "auc_ci_low":          _bootstrap_auc_ci(y_test, ens_proba)[0],
        "auc_ci_high":         _bootstrap_auc_ci(y_test, ens_proba)[1],
        "ensemble_weights":    {k: round(v, 6) for k, v in ens_weights.items()},
        "f1":                  round(float(f1_score(y_test, (ens_proba >= ens_thresh).astype(int))), 6),
        "precision":           ens_op["ppv"],
        "recall":              ens_op["sensitivity"],
        "operating_threshold": ens_thresh,
        "brier":               round(float(brier_score_loss(y_test, ens_proba)), 6),
        "ece":                 round(_expected_calibration_error(y_test, ens_proba), 6),
        "mean_predicted":      round(float(ens_proba.mean()), 6),
        "test_prevalence":     round(float(np.asarray(y_test).mean()), 6),
        "reliability":         _reliability_curve(y_test, ens_proba),
        "threshold_profile":   ens_profile,
        "is_virtual":          True,   # not a saved .pkl - computed from the others
    }
    log(f"  Ensemble: AUC={results['Ensemble Voting']['auc']:.4f}  "
        f"threshold={ens_op['threshold']:.3f}  Sens={ens_op['sensitivity']:.4f}  "
        f"Spec={ens_op['specificity']:.4f}  missed/1k={ens_op['missed_per_1000']:.0f}")

    # -- Age-stratified operating points (Run 5) ----------------
    # A single cut-point cannot serve strata whose baseline risk ranges from 28% to
    # 76%: it delivered 63% sensitivity under 45 while flagging 95% of the over-60s.
    # Bands are derived on OOF training predictions, then measured on the holdout.
    log("\n[STEP 13] Deriving age-stratified operating points")
    age_train = X_train_raw["age"].values
    age_test  = X_test_raw["age"].values

    strat = {}
    for mname in list(estimators.keys()) + ["Ensemble Voting"]:
        src = oof_store[mname] if mname in oof_store else oof_ens
        strat[mname] = _stratified_thresholds(
            y_train.values, src, age_train, SCREENING_TARGET_SENSITIVITY)

    ens_strat = strat["Ensemble Voting"]
    log(f"  {'age band':14s}{'thresh':>8s}{'sens':>8s}{'spec':>8s}{'flagged':>9s}"
        f"{'(global sens)':>15s}")
    for label, info in ens_strat.items():
        m = (age_test >= info["age_min"]) & (age_test < info["age_max"])
        if m.sum() < fe.MIN_SUBGROUP_N:
            continue
        c = _confusion_at(y_test.values[m], ens_proba[m], info["threshold"])
        g = _confusion_at(y_test.values[m], ens_proba[m], ens_op["threshold"])
        log(f"  {label:14s}{info['threshold']:8.3f}{c['sensitivity']:8.3f}"
            f"{c['specificity']:8.3f}{c['flagged_rate']:9.1%}{g['sensitivity']:15.3f}")

    # -- Subgroup performance report (Run 5) --------------------
    log("\n[STEP 14] Subgroup performance report")
    sub_frame = fe.assign_subgroups(X_test_raw)

    def _ens_threshold_for(mask):
        """Threshold the app would actually apply to this subgroup."""
        ages = age_test[mask]
        if len(ages) == 0:
            return ens_op["threshold"]
        band = fe.AGE_BANDS[fe.age_band_index(float(np.median(ages)))][2]
        return ens_strat.get(band, {}).get("threshold", ens_op["threshold"])

    subgroup_report = _subgroup_report(
        y_test.values, ens_proba, sub_frame, _ens_threshold_for)
    results["Ensemble Voting"]["subgroups"] = subgroup_report

    for dim, levels in subgroup_report.items():
        log(f"  {dim}")
        for lv in levels:
            ci = (f"[{lv['auc_ci_low']:.3f},{lv['auc_ci_high']:.3f}]"
                  if lv["auc_ci_low"] is not None else "")
            log(f"    {lv['level']:22s} n={lv['n']:6d} prev={lv['prevalence']:.3f} "
                f"AUC={lv['auc']:.4f} {ci:17s} sens={lv['sensitivity']:.3f} "
                f"calib_gap={lv['calibration_gap']:+.3f}")

    # -- Step 15: Clinical benchmark & incremental feature value (Run 6) ---
    log("\n[STEP 15] Clinical benchmark - is this better than existing practice?")
    bench = _baseline_benchmark(X_train_raw, y_train, X_test_raw, y_test, ens_proba)
    log(f"  {'model':42s}{'AUC':>8s}{'vs ML':>10s}{'95% CI':>22s}{'sig':>6s}")
    log(f"  {bench['ml_model']['name']:42s}{bench['ml_model']['auc']:8.4f}")
    for name, d in bench["baselines"].items():
        a = d["ml_advantage"]
        log(f"  {name:42s}{d['auc']:8.4f}{a['difference']:+10.4f}"
            f"   [{a['ci_low']:+.4f},{a['ci_high']:+.4f}]{str(a['significant']):>6s}")

    log("\n[STEP 16] Incremental feature value - would more data help more than more modelling?")
    ladder = _incremental_value_analysis(X_train_raw, y_train, X_test_raw, y_test,
                                        feature_cols)
    log(f"  {'acquisition step':32s}{'#f':>4s}{'AUC':>9s}{'delta':>9s}")
    for r in ladder:
        d = f"{r['delta_auc']:+.4f}" if r["delta_auc"] is not None else "   -  "
        log(f"  {r['step']:32s}{r['n_features']:4d}{r['auc']:9.4f}{d:>9s}")

    log("\n[STEP 17] Ceiling check - do interaction terms add anything?")
    inter = _interaction_test(X_train_raw, y_train, X_test_raw, y_test)
    for fam in ("tree", "linear"):
        r = inter[fam]
        log(f"  {fam:8s} base={r['base']:.4f}  +interactions={r['with_interactions']:.4f}"
            f"  delta={r['delta']:+.4f}")

    # -- Step 18: Population risk distributions (Run 7) --------------------
    # "62% risk" means little on its own. "Higher than 78% of patients your age and
    # sex" is immediately actionable. Percentile reference distributions are stored
    # per age-band x sex stratum so a score can be positioned against true peers
    # rather than against the whole cohort, where age would dominate the comparison.
    log("\n[STEP 18] Building population risk percentile distributions")
    PCTS = list(range(1, 100))
    dist = {"percentiles": PCTS, "strata": {}}
    _age_all = X_test_raw["age"].values
    _sex_all = X_test_raw["gender"].values
    for _lo, _hi, _lbl in fe.AGE_BANDS:
        for _sv, _sl in ((1, "Male"), (0, "Female")):
            m = (_age_all >= _lo) & (_age_all < _hi) & (_sex_all == _sv)
            if m.sum() < fe.MIN_SUBGROUP_N:
                continue
            vals = np.sort(ens_proba[m])
            dist["strata"][f"{_lbl}|{_sl}"] = {
                "n": int(m.sum()),
                "values": [round(float(v), 5)
                           for v in np.percentile(vals, PCTS)],
                "median": round(float(np.median(vals)), 5),
                "observed_prevalence": round(float(y_test.values[m].mean()), 5),
            }
    # Whole-cohort fallback for strata too small to report on their own
    dist["strata"]["ALL"] = {
        "n": int(len(ens_proba)),
        "values": [round(float(v), 5) for v in np.percentile(np.sort(ens_proba), PCTS)],
        "median": round(float(np.median(ens_proba)), 5),
        "observed_prevalence": round(float(y_test.mean()), 5),
    }
    with open(os.path.join(MODELS_DIR, "risk_distribution.json"), "w") as f:
        json.dump(dist, f, indent=4)

    # -- Applicability envelope (Run 7) ------------------------------------
    # The input form accepted ages 1-120 while the training data spans only 30-65.
    # An 82-year-old — an entirely plausible cardiology patient — was receiving a
    # confident risk score, a stratified threshold, a percentile and a care plan from
    # a model that had never seen anyone over 65, with nothing anywhere saying so.
    # Recording the supported envelope lets the app detect extrapolation and say so.
    envelope = {"trained_rows": int(len(df)), "features": {}}
    for col in feature_cols:
        if col not in X_all.columns:
            continue
        s = X_all[col].astype(float)
        envelope["features"][col] = {
            "min": round(float(s.min()), 4),
            "max": round(float(s.max()), 4),
            "p1": round(float(np.percentile(s, 1)), 4),
            "p99": round(float(np.percentile(s, 99)), 4),
            "mean": round(float(s.mean()), 4),
            "n_unique": int(s.nunique()),
        }
    with open(os.path.join(MODELS_DIR, "input_ranges.json"), "w") as f:
        json.dump(envelope, f, indent=4)
    log("  Applicability envelope -> models/input_ranges.json")
    log(f"    age support: {envelope['features']['age']['min']:.0f}"
        f"-{envelope['features']['age']['max']:.0f} years "
        f"(p1-p99: {envelope['features']['age']['p1']:.0f}"
        f"-{envelope['features']['age']['p99']:.0f})")
    log(f"  {len(dist['strata']) - 1} age x sex strata + cohort fallback "
        f"-> models/risk_distribution.json")

    benchmarks = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "holdout_n": int(len(y_test)),
        "clinical_benchmark": bench,
        "incremental_value": ladder,
        "interaction_test": inter,
        "hyperparameter_search": _load_cached_tuning(),
        "interpretation": {
            "headline": ("The ML ensemble significantly outperforms every clinical "
                         "comparator, but gains only ~0.009 AUC over conventional "
                         "logistic regression on the same risk factors."),
            "ceiling": ("Blood pressure accounts for the large majority of achievable "
                        "discrimination. Hyperparameter search adds +0.0024 and "
                        "interaction terms -0.0003 on trees, both inside the noise "
                        "floor. Performance is bounded by the available features, not "
                        "by the modelling method."),
            "what_would_help": [
                "HDL and LDL cholesterol as continuous values (currently a 3-level ordinal)",
                "Confirmed diabetes status (currently proxied by ordinal glucose)",
                "Family history of premature cardiovascular disease",
                "Antihypertensive / lipid-lowering medication status",
                "Objective activity measurement (self-reported activity adds +0.002)",
            ],
            "caveats": [
                "The Framingham comparator is a proxy: ordinal cholesterol mapped to "
                "band midpoints, HDL replaced by sex means. Both handicap it, so the "
                "margin against it is an upper bound.",
                "Framingham and SCORE2 estimate 10-year INCIDENT risk; this dataset's "
                "target is PREVALENT disease at examination. Ranking comparisons remain "
                "valid, absolute risk values do not transfer.",
            ],
        },
    }
    with open(os.path.join(MODELS_DIR, "benchmarks.json"), "w") as f:
        json.dump(benchmarks, f, indent=4)
    log("  Benchmarks -> models/benchmarks.json")

    # -- Persist operating thresholds for the app ---------------
    thresholds = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "policy": ens_profile["policy"],
        "stratification": {
            "variable": "age",
            "bands": [{"label": l, "age_min": lo, "age_max": hi}
                      for lo, hi, l in fe.AGE_BANDS],
            "rationale": ("Baseline cardiovascular risk rises steeply with age, so a "
                          "single cut-point cannot serve all ages. Every established "
                          "risk instrument (Framingham, SCORE2, QRISK3) is "
                          "age-stratified for the same reason."),
        },
        "stratified": strat,
        "models": {
            name: {
                "recommended":      r["threshold_profile"]["operating_points"]["recommended"]["threshold"],
                "rule_out":         r["threshold_profile"]["operating_points"]["rule_out"]["threshold"],
                "rule_in":          r["threshold_profile"]["operating_points"]["rule_in"]["threshold"],
                "risk_bands":       r["threshold_profile"]["risk_bands"],
                "sensitivity":      r["threshold_profile"]["operating_points"]["recommended"]["sensitivity"],
                "specificity":      r["threshold_profile"]["operating_points"]["recommended"]["specificity"],
                "ppv":              r["threshold_profile"]["operating_points"]["recommended"]["ppv"],
                "npv":              r["threshold_profile"]["operating_points"]["recommended"]["npv"],
                "missed_per_1000":  r["threshold_profile"]["operating_points"]["recommended"]["missed_per_1000"],
            }
            for name, r in results.items() if "threshold_profile" in r
        },
    }
    with open(os.path.join(MODELS_DIR, "thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=4)
    log("  Operating thresholds -> models/thresholds.json")

    # -- Save results -----------------------------------------
    duration = round(time.time() - t0, 2)
    with open(os.path.join(MODELS_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=4)

    # -- Calibration summary ----------------------------------
    log("\n" + "-" * 60)
    log(" Calibration summary (lower Brier/ECE is better):")
    log(f"   {'model':32s}{'Brier':>9s}{'ECE':>9s}{'meanPred':>10s}{'actual':>9s}")
    for mname, r in results.items():
        log(f"   {mname:32s}{r['brier']:9.4f}{r['ece']:9.4f}"
            f"{r['mean_predicted']:10.4f}{r['test_prevalence']:9.4f}")
    log("-" * 60)

    log("\n Operating points (screening policy: sensitivity >= "
        f"{SCREENING_TARGET_SENSITIVITY:.0%}):")
    log(f"   {'model':32s}{'thresh':>8s}{'sens':>8s}{'spec':>8s}{'PPV':>8s}"
        f"{'missed/1k':>11s}{'was@0.5':>10s}")
    for mname, r in results.items():
        prof = r.get("threshold_profile")
        if not prof:
            continue
        op, lg = prof["operating_points"]["recommended"], prof["operating_points"]["legacy_half"]
        log(f"   {mname:32s}{op['threshold']:8.3f}{op['sensitivity']:8.3f}"
            f"{op['specificity']:8.3f}{op['ppv']:8.3f}{op['missed_per_1000']:11.0f}"
            f"{lg['missed_per_1000']:10.0f}")
    log("-" * 60)

    # -- Save preprocessing report BEFORE the manifest --------
    # FIXED (BUG-28): the report used to be written AFTER _write_manifest, so the
    # manifest recorded the digest of the PREVIOUS run's report. Every genuine backup
    # therefore reported a digest mismatch on preprocess_report.txt and refused to
    # restore it. Anything the manifest digests must exist in final form first.
    with open(os.path.join(MODELS_DIR, "preprocess_report.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    # -- Provenance manifest ----------------------------------
    manifest = _write_manifest(
        data_path, feature_cols, len(df), float(y.mean()), class_weight_mode
    )
    print(f"\n Manifest written: {len(manifest['artifacts'])} artifacts digested.")

    # -- Artifact registry drift guard (BUG-27) ---------------
    # If a future change writes a new artifact without registering it in
    # fe.MODEL_ARTIFACTS, Backup & Restore would silently refuse to restore it — the
    # exact failure that left thresholds.json and input_ranges.json unrestorable for
    # four runs. Fail here, loudly, at the moment the file is introduced.
    _written = {f for f in os.listdir(MODELS_DIR)
                if os.path.isfile(os.path.join(MODELS_DIR, f))}
    _unregistered = _written - fe.MODEL_ARTIFACTS
    if _unregistered:
        raise RuntimeError(
            f"Unregistered model artifact(s): {sorted(_unregistered)}. Add them to "
            f"feature_engineering.MODEL_ARTIFACTS, otherwise Backup & Restore will "
            f"silently refuse to restore them (see BUG-27)."
        )
    print(f" Artifact registry check: all {len(_written)} files registered.")

    log("\n" + "=" * 60)
    log(f" All models trained in {duration}s")
    log(" Results   -> models/results.json")
    log(" Manifest  -> models/manifest.json")
    log(" Report    -> models/preprocess_report.txt")
    log("=" * 60 + "\n")

    return results, duration


# -------------------------------------------------------------
if __name__ == "__main__":
    train_all()
