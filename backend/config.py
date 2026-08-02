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


def project_dir_writable() -> bool:
    """
    Can the application write beside its own code?

    Two features need to: replacing the training dataset (which overwrites heart.csv)
    and retraining (which writes new pickles into models/). A serverless host mounts
    the deployment read-only, so both raise OSError there — and an unhandled OSError
    renders as "Something went wrong", which tells an administrator nothing about why
    a button does not work and invites them to keep pressing it.

    Probed by writing rather than by `os.access`, which reports the permission bits and
    not the mount: on a read-only filesystem the bits still say writable, and Windows
    ignores the call almost entirely. The probe file is removed immediately.

    Cached: the answer cannot change while the process runs, and the pages that ask are
    on the request path.
    """
    global _WRITABLE
    if _WRITABLE is None:
        probe = os.path.join(PROJECT_ROOT, ".writeprobe")
        try:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("")
            os.remove(probe)
            _WRITABLE = True
        except OSError:
            _WRITABLE = False
    return _WRITABLE


_WRITABLE: bool | None = None

# Shown wherever a feature is unavailable for this reason, so the wording is identical
# on every page rather than reinvented at each call site.
READ_ONLY_NOTICE = (
    "This deployment's filesystem is read-only, so the training dataset and the model "
    "files cannot be changed from here. Run the application locally, or in a container "
    "with a writable volume, to use this feature."
)


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


# ── settings ────────────────────────────────────────────────────────────
# These delegate to the database. The import is INSIDE each function on purpose:
# `backend.repositories.connection` imports this module for DB_PATH, so importing it
# back at module level is a cycle that makes the whole package unimportable. A local
# import runs after both modules are loaded, and costs a dictionary lookup.
#
# The storage moved out of system_settings.json because a file beside the code cannot
# be written on a read-only host and is not shared between instances — see
# backend/repositories/settings.py for the full reasoning.


def get_setting(key: str, default=None):
    from backend.repositories import settings as store
    return store.get_setting(key, default)


def set_setting(key: str, value) -> None:
    from backend.repositories import settings as store
    store.set_setting(key, value)


def secret_key() -> str:
    """
    A persistent session key, created on first run.

    Stored with the other system settings so it survives restarts. Without persistence
    Flask signs cookies with a key that changes every reload, and every user is
    silently signed out whenever the server restarts — which during development is
    constantly, and across a fleet of instances is permanently.

    HEARTGUARD_SECRET_KEY wins and is checked FIRST, before anything touches the
    database. That ordering is what lets a deployment set the key as an environment
    variable and start up even if the schema has not been created yet.

    REQUIRES THE SCHEMA TO EXIST when falling through to the database, so `create_app`
    calls `init_db()` before this.
    """
    if Config.SECRET_KEY:
        return Config.SECRET_KEY
    key = get_setting("secret_key")
    if not key:
        key = secrets.token_hex(32)
        set_setting("secret_key", key)
    return key
