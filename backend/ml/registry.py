"""
Model registry: loads the scaler and estimators once per process and hands them out.

WHY A MODULE-LEVEL CACHE AND NOT A REQUEST-SCOPED LOAD
The five estimators plus the scaler take a noticeable moment to unpickle, and the
server process is long-lived. Loading them once at first use and holding them for the
life of the process costs one delay on the first request instead of one on every
request.

Loading NEVER raises. A missing or unreadable artifact yields an empty registry and a
recorded reason, and the pages that need a model say so. A screening tool that refuses
to start because one pickle is absent is harder to diagnose than one that starts and
reports which pickle is absent.
"""
from __future__ import annotations

import os
import pickle
import threading

from backend import config
from backend.domain import artifacts

__all__ = ["get_registry", "reload_registry", "active_models", "Registry"]

_lock = threading.Lock()
_cache: "Registry | None" = None


class Registry:
    """The loaded scaler, the loaded estimators, and why anything is missing."""

    def __init__(self, scaler=None, models: dict | None = None,
                 errors: dict | None = None):
        self.scaler = scaler
        self.models = models or {}
        self.errors = errors or {}

    @property
    def ready(self) -> bool:
        return self.scaler is not None and bool(self.models)

    @property
    def names(self) -> list[str]:
        # Registry order, not dict-insertion accident: pages list models in this order
        # and a stable order keeps a table from reshuffling between requests.
        return [n for n in config.MODEL_FILES if n in self.models]


def _load() -> Registry:
    errors: dict[str, str] = {}
    if not os.path.exists(config.SCALER_PATH):
        return Registry(errors={"scaler": "scaler.pkl not found — train the models"})
    try:
        with open(config.SCALER_PATH, "rb") as fh:
            scaler = pickle.load(fh)
    except Exception as exc:
        return Registry(errors={"scaler": f"scaler.pkl unreadable: {exc}"})

    models: dict[str, object] = {}
    for name, filename in config.MODEL_FILES.items():
        path = os.path.join(config.MODELS_DIR, filename)
        if not os.path.exists(path):
            errors[name] = "artifact not found"
            continue
        try:
            with open(path, "rb") as fh:
                models[name] = pickle.load(fh)
        except Exception as exc:
            # One corrupt estimator must not cost the other four.
            errors[name] = f"unreadable: {exc}"
    return Registry(scaler=scaler, models=models, errors=errors)


def get_registry() -> Registry:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _load()
    return _cache


def reload_registry() -> Registry:
    """Drop the cache after a retrain. Also clears the cached JSON artifacts."""
    global _cache
    with _lock:
        _cache = None
    artifacts.clear_caches()
    return get_registry()


def active_models() -> dict:
    """
    The estimators an administrator has left enabled.

    Falls back to every loaded model if the toggles would leave nothing enabled —
    an empty ensemble scores nothing, and a configuration mistake should not silently
    disable screening for the whole institution.
    """
    reg = get_registry()
    cfg = artifacts.load_model_config()
    enabled = {n: m for n, m in reg.models.items() if cfg.get(n, True)}
    return enabled or dict(reg.models)
