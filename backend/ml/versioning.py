"""
Version identity for the loaded model artifacts.

Every prediction records this. Without it, retraining silently invalidates the
interpretation of every historical row: the score stays in the database but the model
that produced it is gone, so the record can no longer be explained or audited.
"""

from __future__ import annotations

import json
import os

from backend.config import MODELS_DIR


# ════════════════════════════════════════════════════════════════════════
# Model version identity
# ════════════════════════════════════════════════════════════════════════
def model_version_info():
    """
    Version identity for the currently loaded artifacts.

    Every prediction records this. Without it, retraining silently invalidates the
    interpretation of every historical row — the score stays in the database but the
    model that produced it is gone, so the record cannot be explained or audited.
    """
    path = os.path.join(MODELS_DIR, "manifest.json")
    if not os.path.exists(path):
        return {"version": "unknown", "manifest_sha": "", "trained_at": ""}
    try:
        with open(path) as f:
            m = json.load(f)
        trained = m.get("generated_at", "")
        ds_sha = (m.get("dataset", {}) or {}).get("sha256", "") or ""
        rows = (m.get("dataset", {}) or {}).get("rows_used_for_training", 0)
        # Human-readable, sortable, and tied to the exact data that produced it
        version = f"{trained.replace('-', '').replace(':', '').replace(' ', '-')}"
        return {
            "version": version,
            "manifest_sha": ds_sha[:16],
            "trained_at": trained,
            "rows": rows,
        }
    except Exception:
        return {"version": "unknown", "manifest_sha": "", "trained_at": ""}
