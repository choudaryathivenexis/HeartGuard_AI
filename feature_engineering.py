"""
HeartGuard FYP — Shared Feature Engineering
===========================================
SINGLE SOURCE OF TRUTH for categorical encodings and derived clinical features.

Before this module existed, the four engineered features were reimplemented in three
places (train_models.py, app.py diagnosis form, app.py SHAP background builder) and had
already drifted apart — the `high_risk_flag` threshold meant different things at train
time and at serve time (BUG-05). Every consumer now imports from here.

--------------------------------------------------------------------------
DATASET ENCODING — READ THIS BEFORE CHANGING ANYTHING
--------------------------------------------------------------------------
heart.csv is **0-indexed**. This differs from the canonical Kaggle release, which ships
these ordinals as 1/2/3. Assuming the upstream convention is what caused BUG-03
(89.8% of the dataset silently discarded) and BUG-04 (train/serve encoding skew).

    cholesterol :  0 = normal, 1 = above normal, 2 = well above normal
    gluc        :  0 = normal, 1 = above normal, 2 = well above normal
    gender      :  0 = female, 1 = male
    smoke/alco/active/cardio : 0 = no, 1 = yes

Any literal `[1, 2, 3]` or `>= 2` applied to cholesterol/gluc elsewhere in this codebase
is a bug, not a convention.
"""

import numpy as np
import pandas as pd

# ── Categorical encoding (0-indexed — see module docstring) ──────────────
CHOLESTEROL_LEVELS = [(0, "Normal"), (1, "Above Normal"), (2, "Well Above Normal")]
GLUCOSE_LEVELS     = [(0, "Normal"), (1, "Above Normal"), (2, "Well Above Normal")]
GENDER_LEVELS      = [(1, "Male"), (0, "Female")]

CHOLESTEROL_LABELS = dict(CHOLESTEROL_LEVELS)
GLUCOSE_LABELS     = dict(GLUCOSE_LEVELS)

# Valid ordinal values — used by the training domain filter.
ORDINAL_VALID_VALUES = [0, 1, 2]

# "Elevated" means above-normal or worse. On the 0-based scale that is >= 1.
# (On the old 1-based assumption this was >= 2, which is what made the flag fire on a
#  different population at train time than at serve time.)
ELEVATED_THRESHOLD = 1

# Hypertension threshold for the combined risk flag (mmHg, systolic).
HYPERTENSION_SYSTOLIC = 140

# ── Canonical feature order — the system's central contract ─────────────
# StandardScaler and all five estimators index positionally. Never reorder.
FEATURE_ORDER = [
    "age", "gender", "height", "weight", "ap_hi", "ap_lo",
    "cholesterol", "gluc", "smoke", "alco", "active",
    "bmi", "pulse_pressure", "age_group", "high_risk_flag",
]

BASE_INPUTS = [
    "age", "gender", "height", "weight", "ap_hi", "ap_lo",
    "cholesterol", "gluc", "smoke", "alco", "active",
]

ENGINEERED = ["bmi", "pulse_pressure", "age_group", "high_risk_flag"]

# Human-readable labels for charts and reports.
FEATURE_LABELS = {
    "age": "Age", "gender": "Gender", "height": "Height", "weight": "Weight",
    "ap_hi": "Systolic BP", "ap_lo": "Diastolic BP",
    "cholesterol": "Cholesterol", "gluc": "Glucose",
    "smoke": "Smoker", "alco": "Alcohol", "active": "Physically Active",
    "bmi": "BMI", "pulse_pressure": "Pulse Pressure",
    "age_group": "Age Group", "high_risk_flag": "High Risk Flag",
}

# ── Derived-feature parameters ──────────────────────────────────────────
BMI_MIN, BMI_MAX = 10, 70
AGE_GROUP_BINS   = [0, 30, 45, 60, 75, 120]
AGE_GROUP_LABELS = [0, 1, 2, 3, 4]


# ════════════════════════════════════════════════════════════════════════
# Scalar helpers — used by the single-patient inference path
# ════════════════════════════════════════════════════════════════════════
def compute_bmi(weight_kg, height_cm):
    """BMI clipped to a physiologically sane range."""
    bmi = weight_kg / ((height_cm / 100.0) ** 2)
    return float(np.clip(round(bmi, 2), BMI_MIN, BMI_MAX))


def compute_pulse_pressure(ap_hi, ap_lo):
    return ap_hi - ap_lo


def compute_age_group(age_years):
    """Ordinal age band 0-4, matching AGE_GROUP_BINS."""
    for idx, upper in enumerate(AGE_GROUP_BINS[1:]):
        if age_years <= upper:
            return AGE_GROUP_LABELS[idx]
    return AGE_GROUP_LABELS[-1]


def compute_high_risk_flag(cholesterol, ap_hi):
    """Combined clinical risk flag: elevated cholesterol AND hypertensive."""
    return int(cholesterol >= ELEVATED_THRESHOLD and ap_hi >= HYPERTENSION_SYSTOLIC)


def build_feature_row(age, gender, height, weight, ap_hi, ap_lo,
                      cholesterol, gluc, smoke, alco, active):
    """
    Build one inference-ready feature vector in FEATURE_ORDER.

    This is the ONLY supported way to construct input for the models — it guarantees
    the derived features and the column order match what training produced.

    Returns
    -------
    list[float]  length == len(FEATURE_ORDER)
    """
    row = {
        "age": age, "gender": gender, "height": height, "weight": weight,
        "ap_hi": ap_hi, "ap_lo": ap_lo,
        "cholesterol": cholesterol, "gluc": gluc,
        "smoke": smoke, "alco": alco, "active": active,
        "bmi": compute_bmi(weight, height),
        "pulse_pressure": compute_pulse_pressure(ap_hi, ap_lo),
        "age_group": compute_age_group(age),
        "high_risk_flag": compute_high_risk_flag(cholesterol, ap_hi),
    }
    return [row[c] for c in FEATURE_ORDER]


# ════════════════════════════════════════════════════════════════════════
# Vectorised helpers — used by training and by the SHAP background builder
# ════════════════════════════════════════════════════════════════════════
def engineer_features(df):
    """
    Add the four derived features to a DataFrame, in place-safe fashion.

    Applied identically at train time and when building the SHAP background, so
    explanations describe the same feature space the models were fitted on.
    """
    df = df.copy()

    if "height" in df.columns and "weight" in df.columns:
        df["bmi"] = (df["weight"] / ((df["height"] / 100.0) ** 2)).round(2)
        df["bmi"] = df["bmi"].clip(BMI_MIN, BMI_MAX)

    if "ap_hi" in df.columns and "ap_lo" in df.columns:
        df["pulse_pressure"] = df["ap_hi"] - df["ap_lo"]

    if "age" in df.columns:
        df["age_group"] = pd.cut(
            df["age"], bins=AGE_GROUP_BINS, labels=AGE_GROUP_LABELS
        ).astype("float").fillna(AGE_GROUP_LABELS[-1]).astype(int)

    if "cholesterol" in df.columns and "ap_hi" in df.columns:
        df["high_risk_flag"] = (
            (df["cholesterol"] >= ELEVATED_THRESHOLD)
            & (df["ap_hi"] >= HYPERTENSION_SYSTOLIC)
        ).astype(int)

    return df


def convert_age_to_years(df):
    """Convert the `age` column from days to whole years when it is clearly in days."""
    if "age" in df.columns and df["age"].max() > 1000:
        df = df.copy()
        df["age"] = (df["age"] / 365.25).round(0).astype(int)
        return df, True
    return df, False


# ════════════════════════════════════════════════════════════════════════
# SUBGROUP DEFINITIONS  (Run 5)
# ════════════════════════════════════════════════════════════════════════
# Shared by training (to measure per-subgroup performance and derive stratified
# operating points) and by the app (to tell a clinician how reliable the model is
# for the patient in front of them). One definition, two consumers.
#
# AGE is the stratification variable for thresholds. Every established cardiovascular
# risk instrument (Framingham, SCORE2, QRISK3) is age-stratified, because baseline
# risk rises so steeply with age that a single cut-point cannot serve all ages: on
# this data a global threshold gives 63% sensitivity under 45 and flags 95% of the
# over-60s. The other subgroups below are measured and reported, but do not get their
# own thresholds - splitting on several variables at once fragments the data faster
# than it buys accuracy.

AGE_BANDS = [
    (0,   45,  "Under 45"),
    (45,  55,  "45-54"),
    (55,  60,  "55-59"),
    (60,  200, "60 and over"),
]


def age_band_index(age):
    """Index into AGE_BANDS for a given age in years."""
    for i, (lo, hi, _) in enumerate(AGE_BANDS):
        if lo <= age < hi:
            return i
    return len(AGE_BANDS) - 1


def age_band_label(age):
    return AGE_BANDS[age_band_index(age)][2]


BMI_CLASSES = [
    (0.0,  25.0, "Normal (<25)"),
    (25.0, 30.0, "Overweight (25-30)"),
    (30.0, 999.0, "Obese (30+)"),
]


def bmi_class_label(bmi):
    for lo, hi, lbl in BMI_CLASSES:
        if lo <= bmi < hi:
            return lbl
    return BMI_CLASSES[-1][2]


def assign_subgroups(df):
    """
    Map each row to its subgroup label across every reported dimension.

    Returns a DataFrame of string labels with one column per dimension, aligned to
    df's index. Used by training for stratified reporting and by the app to locate a
    single patient within the measured performance table.
    """
    out = pd.DataFrame(index=df.index)
    if "age" in df.columns:
        out["Age band"] = df["age"].apply(age_band_label)
    if "gender" in df.columns:
        out["Sex"] = df["gender"].map({1: "Male", 0: "Female"}).fillna("Unknown")
    if "cholesterol" in df.columns:
        out["Cholesterol"] = df["cholesterol"].map(CHOLESTEROL_LABELS).fillna("Unknown")
    if "gluc" in df.columns:
        out["Glucose"] = df["gluc"].map(GLUCOSE_LABELS).fillna("Unknown")
    if "bmi" in df.columns:
        out["BMI class"] = df["bmi"].apply(bmi_class_label)
    if "smoke" in df.columns:
        out["Smoking"] = df["smoke"].map({1: "Smoker", 0: "Non-smoker"}).fillna("Unknown")
    return out


# Minimum stratum size before a measured statistic is considered reportable.
# Below this the confidence interval is too wide to act on.
MIN_SUBGROUP_N = 200


# ════════════════════════════════════════════════════════════════════════
# MODEL ARTIFACT REGISTRY  (Run 8 — BUG-27)
# ════════════════════════════════════════════════════════════════════════
# The canonical set of files a training run produces, and therefore the only files
# Backup & Restore may write into models/.
#
# WHY THIS LIVES HERE
# -------------------
# The restore allowlist was originally hardcoded inside pages_ext.page_backup_restore
# (Run 3). Runs 4-7 then added thresholds.json, input_ranges.json,
# risk_distribution.json, benchmarks.json and tuning_result.json — and nobody updated
# that list. A genuine backup therefore could not be fully restored, and the failure
# was SILENT and safety-critical:
#
#   thresholds.json missing    -> get_risk_threshold() falls back to 0.50, undoing the
#                                 entire Run 4 fix and doubling the miss rate
#   input_ranges.json missing  -> check_applicability() returns nothing, so the BUG-23
#                                 extrapolation guard goes dead
#
# A "restore" silently downgrading clinical safety is the worst possible failure mode
# for that feature. The set now lives beside the feature contract, and train_models
# asserts at the end of every run that it actually wrote nothing outside it — so
# adding a new artifact without registering it breaks training loudly and immediately
# rather than quietly breaking restore months later.

MODEL_ARTIFACTS = {
    # estimators + preprocessing
    "scaler.pkl",
    "logistic_regression.pkl",
    "svm.pkl",
    "decision_tree.pkl",
    "random_forest.pkl",
    "xgboost.pkl",
    # feature / preprocessing contract
    "features.json",
    "imputer_medians.json",
    # evaluation + operating points
    "results.json",
    "thresholds.json",
    "risk_distribution.json",
    "input_ranges.json",
    "benchmarks.json",
    "tuning_result.json",
    # provenance + human-readable record
    "manifest.json",
    "preprocess_report.txt",
    # runtime configuration
    "config.json",
}


# ════════════════════════════════════════════════════════════════════════
# MONOTONIC CLINICAL CONSTRAINTS  (Run 7)
# ════════════════════════════════════════════════════════════════════════
# Established cardiovascular evidence fixes the DIRECTION of several risk factors:
# risk does not fall because blood pressure rose. An unconstrained gradient-boosted
# ensemble does not know that, and measurably violated it — a systolic sweep from
# 100 to 200 mmHg produced 6 non-monotonic steps out of 20, i.e. the model implied
# that raising blood pressure by 5 mmHg could REDUCE risk across ~30% of the range.
#
# That is tolerable in a pure ranking task and unacceptable in a tool that generates
# care advice, because the counterfactual simulator turns those inversions into
# recommendations. Constraining the direction cost 0.0001 AUC (0.8000 -> 0.7999) and
# removed every violation.
#
#   +1  risk is non-decreasing in this feature
#   -1  risk is non-increasing in this feature
#    0  unconstrained (direction not established, or not clinically monotonic)
#
# Deliberately unconstrained: gender and alcohol (no monotonic clinical direction as
# encoded), and height/weight (only meaningful jointly, via BMI, which IS constrained).

MONOTONIC_DIRECTIONS = {
    "age":            +1,
    "gender":          0,
    "height":          0,
    "weight":          0,
    "ap_hi":          +1,
    "ap_lo":          +1,
    "cholesterol":    +1,
    "gluc":           +1,
    "smoke":          +1,
    "alco":            0,
    "active":         -1,
    "bmi":            +1,
    "pulse_pressure": +1,
    "age_group":      +1,
    "high_risk_flag": +1,
}


def monotonic_constraint_vector(feature_names):
    """Constraint tuple aligned to a feature list, for XGBoost / scikit-learn."""
    return tuple(MONOTONIC_DIRECTIONS.get(f, 0) for f in feature_names)


# ════════════════════════════════════════════════════════════════════════
# PHYSIOLOGICAL VALIDITY  (Run 8 — BUG-26)
# ════════════════════════════════════════════════════════════════════════
# The training pipeline rejects rows where systolic <= diastolic (see
# train_models._domain_filter) because such a reading is physically impossible — it
# is a transcription error, not a patient. The input form applied no such rule, so
# 90/180 was accepted, produced a pulse pressure of -90 (training range is 5-140),
# and returned a confident "LOW RISK" verdict with no warning of any kind.
#
# This is a DIFFERENT failure from extrapolation. Extrapolation means "a real patient
# the model has not seen"; this means "not a possible measurement". The former earns a
# warning, the latter must be rejected — otherwise the form silently launders a typo
# into a clinical record.
#
# Kept here so training and inference enforce one definition of "physiologically
# possible", exactly as they now share one definition of the feature space.

def validate_physiology(inputs):
    """
    Hard validity checks on a submitted measurement set.

    Returns a list of human-readable error strings. A non-empty list means the input
    is not a possible clinical measurement and must not be scored.
    """
    errors = []
    ap_hi = inputs.get("ap_hi")
    ap_lo = inputs.get("ap_lo")

    if ap_hi is not None and ap_lo is not None:
        if ap_hi <= ap_lo:
            errors.append(
                f"Systolic BP ({ap_hi:g}) must be greater than diastolic BP "
                f"({ap_lo:g}). A reading where systolic does not exceed diastolic is "
                f"not physiologically possible — please check the values."
            )
        elif (ap_hi - ap_lo) < 5:
            errors.append(
                f"Pulse pressure is only {ap_hi - ap_lo:g} mmHg "
                f"({ap_hi:g}/{ap_lo:g}). The narrowest reading in the training data is "
                f"5 mmHg — please confirm this measurement."
            )

    height = inputs.get("height")
    weight = inputs.get("weight")
    if height and weight:
        bmi = compute_bmi(weight, height)
        if bmi <= BMI_MIN or bmi >= BMI_MAX:
            errors.append(
                f"Height and weight give a BMI of {bmi:g}, outside the physiologically "
                f"plausible range {BMI_MIN}-{BMI_MAX}. Please check both values."
            )
    return errors


# ════════════════════════════════════════════════════════════════════════
# CLINICAL UNITS  (Run 7)
# ════════════════════════════════════════════════════════════════════════
# The model consumes ordinal severity categories, but clinicians read lab reports in
# concentration units — and which unit depends on where they practise. mg/dL is
# standard in the US, Japan and parts of Asia; mmol/L across Europe, the UK,
# Australia and Canada. Hardcoding one of them makes the tool unusable in half the
# world, and — worse — invites silent misreading of a boundary value.
#
# The ordinal bands themselves are unit-independent. What changes is only how each
# band is LABELLED, so the conversion never touches the model input.
#
# Conversion factors (standard):
#   total cholesterol   mg/dL = mmol/L x 38.67
#   glucose             mg/dL = mmol/L x 18.02

CHOLESTEROL_MMOL_PER_MGDL = 1.0 / 38.67
GLUCOSE_MMOL_PER_MGDL     = 1.0 / 18.02

SUPPORTED_UNITS = ["mg/dL", "mmol/L"]

# Clinical band boundaries in mg/dL (ATP III for cholesterol, ADA for glucose).
CHOLESTEROL_BANDS_MGDL = [(0, 200), (200, 240), (240, None)]
GLUCOSE_BANDS_MGDL     = [(0, 100), (100, 126), (126, None)]


def _fmt_band(lo, hi, factor, unit, decimals):
    """Render one band boundary pair in the requested unit."""
    def _v(x):
        return f"{x * factor:.{decimals}f}" if factor != 1.0 else f"{x:.0f}"
    if hi is None:
        return f"≥ {_v(lo)} {unit}"
    if lo == 0:
        return f"< {_v(hi)} {unit}"
    return f"{_v(lo)}–{_v(hi)} {unit}"


def ordinal_labels_with_units(kind="cholesterol", unit="mg/dL"):
    """
    Ordinal level -> label annotated with the clinical range in the chosen unit.

    e.g. cholesterol level 1 in mmol/L -> "Above Normal (5.17-6.21 mmol/L)"

    Returns {level: label}. Falls back to bare labels for an unknown unit rather
    than guessing — a wrong unit annotation on a clinical form is worse than none.
    """
    base = CHOLESTEROL_LABELS if kind == "cholesterol" else GLUCOSE_LABELS
    bands = CHOLESTEROL_BANDS_MGDL if kind == "cholesterol" else GLUCOSE_BANDS_MGDL
    if unit not in SUPPORTED_UNITS:
        return dict(base)
    if unit == "mg/dL":
        factor, decimals = 1.0, 0
    else:
        factor = (CHOLESTEROL_MMOL_PER_MGDL if kind == "cholesterol"
                  else GLUCOSE_MMOL_PER_MGDL)
        decimals = 2 if kind == "cholesterol" else 1
    return {lvl: f"{base[lvl]} ({_fmt_band(lo, hi, factor, unit, decimals)})"
            for lvl, (lo, hi) in enumerate(bands) if lvl in base}


def levels_with_units(kind="cholesterol", unit="mg/dL"):
    """(value, label) pairs for a Streamlit selectbox, annotated with unit ranges."""
    labels = ordinal_labels_with_units(kind, unit)
    order = CHOLESTEROL_LEVELS if kind == "cholesterol" else GLUCOSE_LEVELS
    return [(v, labels.get(v, name)) for v, name in order]


ORDINAL_COLUMNS = ["cholesterol", "gluc"]


def normalize_ordinal_encoding(df):
    """
    Coerce ordinal severity columns onto the 0-indexed scale this pipeline expects.

    WHY THIS EXISTS (BUG-22)
    ------------------------
    `heart.csv` ships cholesterol/gluc as 0/1/2, but the canonical Kaggle release uses
    1/2/3. A retention floor alone cannot catch the difference: filtering 1/2/3 data
    against {0,1,2} only drops the "well above normal" rows, which costs ~14% of the
    dataset — under any sane attrition threshold. It passes silently while deleting
    every most-severe patient and shifting disease prevalence by ~3.5 points.

    Detection rule: a 0-indexed column has max == 2. If a column's observed values sit
    in [1, 3] with max == 3, it is 1-indexed and is shifted down by one.

    Returns
    -------
    (df, notes) : the normalised frame and a list of human-readable descriptions of
                  any shift applied, for the training log.
    """
    notes = []
    df = df.copy()
    for col in ORDINAL_COLUMNS:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        lo, hi = int(series.min()), int(series.max())
        if lo >= 1 and hi == 3:
            df[col] = df[col] - 1
            notes.append(
                f"'{col}' detected as 1-indexed (observed {lo}..{hi}) "
                f"-> shifted to 0-indexed"
            )
        elif hi > 2 or lo < 0:
            notes.append(
                f"WARNING: '{col}' has values outside both known encodings "
                f"(observed {lo}..{hi}); rows outside {ORDINAL_VALID_VALUES} "
                f"will be dropped by the domain filter"
            )
    return df, notes


def label_for(feature_name):
    return FEATURE_LABELS.get(feature_name, feature_name)
