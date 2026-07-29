"""
Readers for the artifacts produced at training time.

Every one of these is a JSON file written by train_models.py. They are read, never
written, by the running application — the one exception is the model on/off config,
which an administrator toggles.

All readers fail soft and return an empty mapping. A missing artifact must degrade a
page, never take the application down: a fresh clone with no trained models should
still start, sign in and explain that no models are available.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from backend import config

__all__ = [
    "load_results", "load_thresholds", "load_manifest", "load_benchmarks",
    "load_model_config", "save_model_config", "clear_caches",
]


def _read_json(path: str) -> dict:
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def _results_raw() -> dict:
    return _read_json(config.RESULTS_JSON)


def load_results(include_virtual: bool = False) -> dict:
    """
    Trained-model results.

    "Ensemble Voting" is a VIRTUAL entry: it exists so the default prediction path has
    its own derived operating point, but it is not a saved estimator and therefore has
    no confusion matrix, feature importances or cross-validation figures. Including it
    in a page that iterates models produces a row of blanks, so it is excluded unless
    a caller explicitly asks — the threshold analysis is the only place that wants it.
    """
    data = _results_raw()
    if include_virtual:
        return dict(data)
    return {k: v for k, v in data.items() if not v.get("is_virtual")}


@lru_cache(maxsize=1)
def load_thresholds() -> dict:
    """Per-model operating points and risk bands derived from the holdout ROC."""
    return _read_json(config.THRESHOLDS_JSON)


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    """Dataset provenance: row counts, digests, training timestamp."""
    return _read_json(config.MANIFEST_JSON)


@lru_cache(maxsize=1)
def load_benchmarks() -> dict:
    """Clinical benchmark comparison and incremental feature value."""
    return _read_json(config.BENCHMARKS_JSON)


def load_model_config() -> dict:
    """
    Which estimators are enabled, as toggled by an administrator.

    Defaults every known model to on. Written back on first read so the file exists
    and the toggles page has something concrete to edit.
    """
    path = os.path.join(config.MODELS_DIR, "config.json")
    existing = _read_json(path)
    if existing:
        return existing
    defaults = {name: True for name in config.MODEL_FILES}
    save_model_config(defaults)
    return defaults


def save_model_config(cfg: dict) -> None:
    os.makedirs(config.MODELS_DIR, exist_ok=True)
    with open(os.path.join(config.MODELS_DIR, "config.json"), "w",
              encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)


def clear_caches() -> None:
    """Drop cached artifacts after a retrain so pages show the new numbers."""
    _results_raw.cache_clear()
    load_thresholds.cache_clear()
    load_manifest.cache_clear()
    load_benchmarks.cache_clear()
