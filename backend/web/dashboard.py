"""Role-aware landing page."""
from __future__ import annotations

from flask import Blueprint, render_template

from backend.domain import artifacts
from backend import repositories as db
from backend.services import auth as auth_service
from backend.services.analytics import dashboard_summary

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
@auth_service.login_required
def index():
    user = auth_service.current_user()
    summary = dashboard_summary(user)
    return render_template(
        "pages/dashboard.html",
        summary=summary,
        recent=summary["recent"],
        activity=db.get_system_logs(limit=8) if user["role"] != "Doctor" else [],
        models=artifacts.load_results(),
    )
