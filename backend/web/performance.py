"""Model performance: leaderboard, operating points, subgroup breakdown."""
from __future__ import annotations

from flask import Blueprint, render_template

from backend.domain import artifacts
from backend.domain import risk as risk_domain
from backend.services import analytics
from backend.services import auth as auth_service

bp = Blueprint("performance", __name__, url_prefix="/performance")


@bp.route("/")
@auth_service.login_required
def index():
    thresholds = artifacts.load_thresholds()
    return render_template(
        "pages/performance.html",
        leaderboard=analytics.model_leaderboard(),
        thresholds=thresholds.get("models", {}),
        stratified=thresholds.get("stratified", {}),
        sensitivity_target=thresholds.get("policy", {}).get("target_sensitivity"),
        manifest=artifacts.load_manifest(),
        benchmarks=artifacts.load_benchmarks(),
        subgroups=risk_domain.subgroup_performance(),
    )
