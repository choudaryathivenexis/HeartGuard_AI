"""
Aggregations for the dashboard and the analytics page.

Counting happens here, not in a template. A template that filters a list is a template
that quietly disagrees with the page next to it the moment one of them is edited.
"""
from __future__ import annotations

from collections import Counter

from backend.domain import artifacts
from backend import repositories as db

__all__ = ["dashboard_summary", "risk_mix", "activity_series", "model_leaderboard",
           "outcome_summary"]


def outcome_summary() -> dict:
    """
    Deployed-performance summary, flattened for display.

    The repository returns `(summary, per_model_rows)`. Unpacking it HERE rather than
    in each template means one place knows the shape — three templates each indexing a
    tuple is three places to update when the query changes, and a template that gets it
    wrong fails at render time rather than at import.
    """
    try:
        summary, per_model = db.get_outcome_stats()
    except Exception:
        return {"summary": {}, "per_model": []}
    return {"summary": summary or {}, "per_model": list(per_model or [])}


def _visible_predictions(user: dict) -> list[dict]:
    """
    What this user is allowed to count.

    A Doctor sees their own assessments; Admin and SuperAdmin see everything. Scoping
    the QUERY rather than the display matters — a count computed over all records and
    then rendered to a doctor leaks the size of other clinicians' caseloads.
    """
    if user["role"] == "Doctor":
        return db.get_predictions(user_id=user["id"])
    return db.get_predictions()


def dashboard_summary(user: dict) -> dict:
    rows = _visible_predictions(user)
    # The column is `predicted_class`. Reading `prediction` returned None for every row
    # and reported "0 flagged" on a dashboard whose own table listed HIGH RISK
    # patients — the two disagreed on screen with nothing raised.
    flagged = sum(1 for r in rows if r.get("predicted_class") == 1)
    total = len(rows)
    users = db.get_all_users() if user["role"] != "Doctor" else []
    return {
        "total": total,
        "flagged": flagged,
        "below": total - flagged,
        "flagged_pct": (flagged / total) if total else 0.0,
        "users": len(users),
        "doctors": sum(1 for u in users if u.get("role") == "Doctor"),
        "active_models": len(artifacts.load_results()),
        "recent": rows[:10],
        "scope": "your assessments" if user["role"] == "Doctor" else "all assessments",
    }


def risk_mix(user: dict) -> dict[str, int]:
    """Assessments per risk band, in clinical order."""
    order = ["LOW RISK", "BORDERLINE", "INTERMEDIATE RISK", "HIGH RISK"]
    counts = Counter((r.get("risk_band") or "").upper()
                     for r in _visible_predictions(user))
    return {band: counts.get(band, 0) for band in order}


def activity_series(user: dict, days: int = 14) -> list[tuple[str, int]]:
    """Assessments per day, most recent last."""
    rows = _visible_predictions(user)
    counts = Counter((r.get("timestamp") or "")[:10] for r in rows if r.get("timestamp"))
    return sorted(counts.items())[-days:]


def model_leaderboard() -> list[dict]:
    """Trained estimators ranked by discrimination, virtual entries excluded."""
    out = []
    for name, entry in artifacts.load_results().items():
        out.append({
            # results.json names this key `auc`. Reading `roc_auc` returned None for
            # every model, which silently emptied the leaderboard and 404'd the
            # discrimination chart rather than raising anything.
            "name": name,
            "auc": entry.get("auc"),
            "accuracy": entry.get("accuracy"),
            "precision": entry.get("precision"),
            "recall": entry.get("recall"),
            "f1": entry.get("f1"),
        })
    return sorted(out, key=lambda r: (r["auc"] is None, -(r["auc"] or 0)))
