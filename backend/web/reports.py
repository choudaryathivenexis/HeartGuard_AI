"""Cohort reporting and CSV export."""
from __future__ import annotations

import csv
import io

from flask import Blueprint, Response, render_template

from backend import repositories as db
from backend.services import analytics
from backend.services import auth as auth_service

bp = Blueprint("reports", __name__, url_prefix="/reports")

_EXPORT_COLUMNS = [
    "id", "timestamp", "patient_ref", "patient_name", "doctor_name", "age", "gender",
    "height", "weight", "ap_hi", "ap_lo", "cholesterol", "gluc", "smoke", "alco",
    "active", "probability", "predicted_class", "risk_band", "threshold_used",
    "model_used", "model_version", "extrapolated", "outcome",
]


def _scoped_rows(user: dict) -> list[dict]:
    if user["role"] == "Doctor":
        return db.get_predictions(user_id=user["id"])
    return db.get_predictions()


@bp.route("/")
@auth_service.roles_required("Doctor", "Admin")
def index():
    user = auth_service.current_user()
    rows = _scoped_rows(user)
    return render_template("pages/reports.html",
                           rows=rows[:200],
                           total=len(rows),
                           mix=analytics.risk_mix(user),
                           outcomes=analytics.outcome_summary()['summary'])


@bp.route("/export.csv")
@auth_service.roles_required("Doctor", "Admin")
def export_csv():
    """
    Export the caseload as CSV.

    Scoped by role like every other view of this data — an export that ignores the
    scoping is a data leak with a friendlier file extension.
    """
    user = auth_service.current_user()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_EXPORT_COLUMNS,
                            extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in _scoped_rows(user):
        writer.writerow({k: row.get(k) for k in _EXPORT_COLUMNS})
    return Response(buffer.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": "attachment; filename=heartguard-assessments.csv"})
