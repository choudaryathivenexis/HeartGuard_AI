"""
Application configuration and filesystem paths.

THE ONE RULE: no module derives a path from its own `__file__`.

Every path in the application resolves from `PROJECT_ROOT`, which is computed here,
once, by walking up from this file. Modules used to each compute `BASE_DIR` from their
own location, which was silently correct only while everything sat in the project root.
The moment `auth_db.py` moved to `backend/repositories/database.py` its `BASE_DIR`
became `backend/repositories/`, so it looked for the database next to itself, did not
find one, and created an empty seeded database there instead — pointing the application
at zero patients while the real records sat untouched two directories up. Nothing
raised; it looked like data loss.

So paths live here, and modules import them.
"""
from __future__ import annotations

import os
import secrets

# backend/config.py -> backend/ -> project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── data ────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(PROJECT_ROOT, "heartguard.db")
DATASET_CSV = os.path.join(PROJECT_ROOT, "heart.csv")
SETTINGS_PATH = os.path.join(PROJECT_ROOT, "system_settings.json")

# ── model artifacts ─────────────────────────────────────────────────────
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
BASELINE_DIR = os.path.join(PROJECT_ROOT, "baseline")
RESULTS_JSON = os.path.join(MODELS_DIR, "results.json")
THRESHOLDS_JSON = os.path.join(MODELS_DIR, "thresholds.json")
MANIFEST_JSON = os.path.join(MODELS_DIR, "manifest.json")
BENCHMARKS_JSON = os.path.join(MODELS_DIR, "benchmarks.json")
SCALER_PATH = os.path.join(MODELS_DIR, "scaler.pkl")

# ── frontend ────────────────────────────────────────────────────────────
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, "templates")
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")

# ── model registry ──────────────────────────────────────────────────────
# Display name -> pickle filename. The display name is the key everywhere else in the
# application (thresholds.json, results.json, the series palette), so it is the key
# here too — a positional list zipped against results.json is what silently
# mislabelled every chart in an earlier build.
MODEL_FILES = {
    "Logistic Regression": "logistic_regression.pkl",
    "Decision Tree": "decision_tree.pkl",
    "Random Forest": "random_forest.pkl",
    "Support Vector Machine (SVM)": "svm.pkl",
    "XGBoost": "xgboost.pkl",
}
ENSEMBLE_NAME = "Ensemble Voting"


class Config:
    """Flask configuration. Values here are read by the app factory."""

    # A stable key means sessions survive a restart. Generated once into
    # system_settings.json rather than hard-coded, because a literal secret committed
    # to a repository is not a secret, and a per-process random key logs every user
    # out on every reload.
    SECRET_KEY = os.environ.get("HEARTGUARD_SECRET_KEY") or ""
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024      # dataset uploads
    TEMPLATES_AUTO_RELOAD = True
    JSON_SORT_KEYS = False


def _load_settings() -> dict:
    import json
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_settings(data: dict) -> None:
    import json
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get_setting(key: str, default=None):
    return _load_settings().get(key, default)


def set_setting(key: str, value) -> None:
    data = _load_settings()
    data[key] = value
    _save_settings(data)


def secret_key() -> str:
    """
    A persistent session key, created on first run.

    Stored beside the other system settings so it survives restarts. Without
    persistence Flask signs cookies with a key that changes every reload, and every
    user is silently signed out whenever the server restarts — which during
    development is constantly.
    """
    if Config.SECRET_KEY:
        return Config.SECRET_KEY
    key = get_setting("secret_key")
    if not key:
        key = secrets.token_hex(32)
        set_setting("secret_key", key)
    return key
