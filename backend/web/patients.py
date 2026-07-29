"""Patient records and their assessment timeline."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from backend import repositories as db
from backend.services import auth as auth_service

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.route("/")
@auth_service.roles_required("Doctor", "Admin")
def index():
    user = auth_service.current_user()
    # A Doctor sees the patients they created; an Admin sees the institution's.
    rows = db.get_patients(created_by=user["id"] if user["role"] == "Doctor" else None)
    query = (request.args.get("q") or "").strip().lower()
    if query:
        rows = [r for r in rows
                if query in str(r.get("fullname", "")).lower()
                or query in str(r.get("patient_code", "")).lower()]
    return render_template("pages/patients.html", rows=rows, q=query)


@bp.route("/<patient_ref>")
@auth_service.roles_required("Doctor", "Admin")
def detail(patient_ref: str):
    timeline = db.get_patient_timeline(patient_ref)
    if not timeline:
        flash("No assessments found for that patient.", "warning")
        return redirect(url_for("patients.index"))
    return render_template("pages/patient_detail.html",
                           patient_ref=patient_ref, timeline=timeline)


@bp.route("/<patient_ref>/delete", methods=["POST"])
@auth_service.roles_required("Admin")
def delete(patient_ref: str):
    """
    Deleting a patient is Admin-only and typed-confirmation gated.

    The confirmation is checked server-side. A client-side-only guard is decoration:
    the POST can be issued without ever loading the page that carries it.
    """
    user = auth_service.current_user()
    if (request.form.get("confirm") or "").strip() != patient_ref:
        flash("Type the patient code exactly to confirm deletion.", "warning")
        return redirect(url_for("patients.detail", patient_ref=patient_ref))
    db.delete_patient(patient_ref, user["username"])
    flash(f"Patient {patient_ref} and their assessments were deleted.", "success")
    return redirect(url_for("patients.index"))


@bp.route("/outcome/<int:pred_id>", methods=["POST"])
@auth_service.roles_required("Doctor", "Admin")
def record_outcome(pred_id: int):
    """Record the confirmed clinical outcome — this is what makes calibration measurable."""
    user = auth_service.current_user()
    outcome = request.form.get("outcome")
    if outcome not in {"confirmed", "ruled_out", "unknown"}:
        flash("Select a valid outcome.", "warning")
    else:
        db.record_outcome(pred_id, outcome,
                          (request.form.get("outcome_notes") or "").strip(),
                          user["username"])
        flash("Outcome recorded.", "success")
    return redirect(request.referrer or url_for("patients.index"))
