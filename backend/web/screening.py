"""
The screening flow: assessment form, result, explanation and downloads.

The result is held in the SESSION between the POST and the page that renders it, and
the POST redirects rather than rendering directly (post/redirect/get). Without that, a
browser refresh on the result page re-submits the form and scores — and stores — the
same patient a second time.
"""
from __future__ import annotations

import io

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, send_file, session, url_for)

from backend import config
from backend.ml import applicability
from backend import repositories as db
from backend.services import auth as auth_service
from backend.services import screening as service
from backend.services import reporting

bp = Blueprint("screening", __name__, url_prefix="/screening")

# Sensible clinical defaults so the form opens ready to use.
DEFAULTS = {"age": 45, "gender": 1, "height": 165, "weight": 70.0,
            "ap_hi": 120, "ap_lo": 80, "cholesterol": 1, "gluc": 1,
            "smoke": 0, "alco": 0, "active": 1}

_NUMERIC = {"age": int, "height": int, "weight": float, "ap_hi": int, "ap_lo": int,
            "gender": int, "cholesterol": int, "gluc": int, "smoke": int,
            "alco": int, "active": int}


def _parse(form) -> tuple[dict, list[str]]:
    """Coerce the posted form. Bad numbers are reported, never silently defaulted."""
    values, errors = {}, []
    for field, cast in _NUMERIC.items():
        raw = (form.get(field) or "").strip()
        if raw == "":
            errors.append(f"{field.replace('_', ' ').title()} is required.")
            continue
        try:
            values[field] = cast(float(raw))
        except ValueError:
            errors.append(f"{field.replace('_', ' ').title()} must be a number.")
    values["patient_code"] = (form.get("patient_code") or "").strip()
    values["patient_name"] = (form.get("patient_name") or "").strip()
    return values, errors


@bp.route("/", methods=["GET"])
@auth_service.roles_required("Doctor")
def new():
    result = session.pop("last_result", None)
    return render_template("pages/screening.html",
                           defaults=DEFAULTS,
                           models=service.model_choices(),
                           ranges=applicability.load_input_ranges().get("features", {}),
                           result=result,
                           errors=session.pop("last_errors", None))


@bp.route("/", methods=["POST"])
@auth_service.roles_required("Doctor")
def assess():
    user = auth_service.current_user()
    values, errors = _parse(request.form)
    if errors:
        session["last_errors"] = errors
        return redirect(url_for("screening.new"))

    outcome = service.run_assessment(
        user, values,
        model_choice=request.form.get("model") or config.ENSEMBLE_NAME,
        notes=(request.form.get("notes") or "").strip())

    if outcome.get("refused"):
        session["last_errors"] = outcome["errors"]
        return redirect(url_for("screening.new"))

    # Only what the result page renders is kept. The scaled feature matrix and the SHAP
    # arrays are numpy and would not survive a session cookie; the prediction id is
    # enough to rebuild them for a download.
    session["last_result"] = reporting.to_session(outcome)
    session["last_prediction_id"] = db.get_predictions(user_id=user["id"])[0]["id"]
    flash("Assessment recorded.", "success")
    return redirect(url_for("screening.new"))


@bp.route("/history")
@auth_service.roles_required("Doctor")
def history():
    user = auth_service.current_user()
    rows = db.get_predictions(user_id=user["id"])
    band = request.args.get("band") or ""
    if band:
        rows = [r for r in rows if (r.get("risk_band") or "").upper() == band.upper()]
    return render_template("pages/history.html", rows=rows, band=band)


@bp.route("/history/<int:pred_id>/delete", methods=["POST"])
@auth_service.roles_required("Doctor")
def delete(pred_id: int):
    user = auth_service.current_user()
    owned = {r["id"] for r in db.get_predictions(user_id=user["id"])}
    if pred_id not in owned:
        flash("That assessment does not belong to your caseload.", "warning")
    else:
        db.delete_prediction(pred_id, user["username"])
        flash(f"Assessment {pred_id} deleted.", "success")
    return redirect(url_for("screening.history"))


@bp.route("/report/<int:pred_id>.pdf")
@auth_service.login_required
def report_pdf(pred_id: int):
    user = auth_service.current_user()
    data, error = reporting.build_pdf(pred_id, user)
    if error:
        flash(f"Report could not be built: {error}", "danger")
        return redirect(url_for("screening.history"))
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"heartguard-assessment-{pred_id}.pdf")


@bp.route("/report/<int:pred_id>.txt")
@auth_service.login_required
def report_text(pred_id: int):
    user = auth_service.current_user()
    text, error = reporting.build_text(pred_id, user)
    if error:
        flash(f"Report could not be built: {error}", "danger")
        return redirect(url_for("screening.history"))
    return Response(text, mimetype="text/plain", headers={
        "Content-Disposition": f"attachment; filename=heartguard-assessment-{pred_id}.txt"})
