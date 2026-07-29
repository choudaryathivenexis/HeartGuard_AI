"""Sign in, register, sign out."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from backend.domain import artifacts
from backend import repositories as db
from backend.services import auth as auth_service
from backend.web import hardening

bp = Blueprint("auth", __name__)


def _login_facts() -> list[tuple[str, str]]:
    """
    The three trust markers on the sign-in panel.

    Read from the shipped artifacts rather than typed in, so the claim on the login
    screen cannot drift away from the model that is actually deployed.
    """
    results = artifacts.load_results(include_virtual=True)
    thresholds = artifacts.load_thresholds()
    manifest = artifacts.load_manifest()
    ens = results.get("Ensemble Voting") or {}

    facts = []
    auc = ens.get("auc")
    lo = ens.get("auc_ci_low")
    hi = ens.get("auc_ci_high")
    if auc is not None:
        interval = f" [{lo:.4f}–{hi:.4f}]" if lo and hi else ""
        facts.append(("Discrimination", f"AUC {auc:.4f}{interval}"))
    strat = thresholds.get("stratification", {}).get("variable")
    # The target lives under `policy`, not at the top level. Reading it from the
    # root returned None and silently dropped the operating-point marker from the
    # sign-in panel — the claim simply did not appear.
    target = thresholds.get("policy", {}).get("target_sensitivity")
    if target:
        facts.append(("Operating point",
                      f"Sensitivity {float(target):.2f}"
                      + (f" · {strat}-stratified" if strat else "")))
    if ens.get("mean_predicted") is not None and ens.get("test_prevalence") is not None:
        gap = abs(ens["mean_predicted"] - ens["test_prevalence"])
        facts.append(("Calibration gap", f"{gap:.3f}"))
    rows = manifest.get("dataset", {}).get("rows_used_for_training")
    return facts, rows


@bp.route("/", methods=["GET"])
def index():
    if auth_service.current_user():
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if auth_service.current_user():
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        locked = hardening.is_locked_out(username)
        if not username or not password:
            error = "Enter both a username and a password."
        elif locked:
            # Counted per (IP, username) pair, so an attacker guessing at an account
            # cannot lock the real clinician out from somewhere else.
            error = (f"Too many failed attempts. Try again in "
                     f"{max(1, locked // 60)} minute(s).")
        else:
            user, error = auth_service.login(username, password)
            if user is None:
                hardening.record_failure(username)
            if user:
                hardening.clear_failures(username)
                nxt = request.args.get("next") or request.form.get("next")
                # Only relative paths are honoured. Accepting an absolute URL here is
                # an open redirect: a crafted link would bounce a signed-in clinician
                # to an external page that looks like this one.
                if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                    return redirect(nxt)
                return redirect(url_for("dashboard.index"))

    facts, rows = _login_facts()
    return render_template("auth/login.html", mode="login", error=error,
                           facts=facts, rows=rows,
                           registration_allowed=auth_service.registration_allowed())


@bp.route("/register", methods=["GET", "POST"])
def register():
    if not auth_service.registration_allowed():
        flash("Self-registration is currently disabled.", "warning")
        return redirect(url_for("auth.login"))

    error = None
    form = {}
    if request.method == "POST":
        form = {k: (request.form.get(k) or "").strip()
                for k in ("username", "fullname", "email", "specialisation")}
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not all([form["username"], form["fullname"], form["email"], password]):
            error = "All fields except specialisation are required."
        elif password != confirm:
            error = "The two passwords do not match."
        elif len(password) < 8:
            error = "Use a password of at least 8 characters."
        else:
            # The role is FIXED to Doctor and never read from the form. A role field in
            # a public registration form is a privilege-escalation hole regardless of
            # what the markup offers.
            #
            # The repository returns (user_id, error) — not (ok, message).
            user_id, message = db.register_user(
                form["username"], password, "Doctor",
                form["fullname"], form["email"], form["specialisation"])
            if user_id is not None:
                flash("Account created. Sign in to continue.", "success")
                return redirect(url_for("auth.login"))
            error = message or "That username is already taken."

    facts, rows = _login_facts()
    return render_template("auth/login.html", mode="register", error=error,
                           form=form, facts=facts, rows=rows,
                           registration_allowed=True)


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    auth_service.logout()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
