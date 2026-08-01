"""Sign in, register, sign out."""
from __future__ import annotations

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from backend.domain import artifacts
from backend import repositories as db
from backend.services import auth as auth_service
from backend.web import hardening

bp = Blueprint("auth", __name__)


# ════════════════════════════════════════════════════════════════════════
# Sign-in entrances
# ════════════════════════════════════════════════════════════════════════
# Three doors onto ONE authentication path. Everything that makes a sign-in safe — the
# password check, the ban check, the lockout counter, the audit entry — happens in
# `services.auth.login` and `hardening`, and is reached identically from all three.
# The portal only decides which roles the door admits and what the page says.
#
# WHAT THIS IS NOT: it is not an extra security boundary. What a signed-in user may
# open is decided by the role ACL in `services.auth.NAV`, on every request, whichever
# door they came through. Anyone claiming a separate URL protects the administration
# pages has the model backwards — the URL is not a secret, it is in this repository.
# The value here is a focused entrance, no self-registration on it, and an audit trail
# of correct credentials arriving at the wrong door.
#
# ROLES ARE NOT RANKED. A SuperAdmin is refused at /admin/login, because this codebase
# treats Admin and SuperAdmin as different jobs rather than levels — the same rule that
# keeps the clinical pages off an administrator's menu (see services/auth.py). The
# links at the foot of every portal are what stops that being a dead end: someone at
# the wrong door is one click from the right one, without the page ever having to admit
# which one is theirs.
#
# /login still admits every role. Making it Doctor-only would mean an administrator who
# forgets which door is theirs is told their password is wrong — the message has to be
# identical to a real failure — and eight of those is a five-minute lockout on correct
# credentials. That is a support call caused by the login page, in exchange for no
# security the ACL does not already provide.
PORTAL_ORDER = ("clinical", "admin", "superadmin")

PORTALS = {
    "clinical": {
        "key": "clinical",
        "endpoint": "auth.login",
        "badge": None,
        "heading": "Sign in",
        "blurb": "Access the cardiovascular screening console.",
        "link_label": "Clinician sign-in",
        "roles": None,            # every role
        "allow_register": True,
    },
    "admin": {
        "key": "admin",
        "endpoint": "auth.admin_login",
        "badge": "Administration",
        "heading": "Administrator sign-in",
        "blurb": "Doctor accounts, prediction records, the training dataset and "
                 "institutional analytics.",
        "link_label": "Administrator sign-in",
        "roles": (auth_service.ROLE_ADMIN,),
        "allow_register": False,
    },
    "superadmin": {
        "key": "superadmin",
        "endpoint": "auth.superadmin_login",
        "badge": "System administration",
        "heading": "System administrator sign-in",
        "blurb": "Roles and permissions, model management, system settings, activity "
                 "logs and backups.",
        "link_label": "System administrator sign-in",
        "roles": (auth_service.ROLE_SUPERADMIN,),
        "allow_register": False,
    },
}


def _other_portals(current_key: str) -> list[dict]:
    """The other entrances, for the links at the foot of the card."""
    return [PORTALS[key] for key in PORTAL_ORDER if key != current_key]


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


def _sign_in(portal: dict):
    """
    Handle one sign-in entrance. Shared by all three portals.

    The lockout is consulted BEFORE the password is checked and counted for every
    refusal, including a wrong-door one. The counter lives in `hardening` and is keyed
    on (client address, username) with no endpoint in the key, so the three portals
    share one budget of attempts — an extra door must not mean extra guesses.
    """
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
            user, error = auth_service.login(username, password,
                                             allowed_roles=portal["roles"])
            if user is None:
                hardening.record_failure(username)
            else:
                hardening.clear_failures(username)
                nxt = request.args.get("next") or request.form.get("next")
                # Only relative paths are honoured. Accepting an absolute URL here is
                # an open redirect: a crafted link would bounce a signed-in clinician
                # to an external page that looks like this one.
                if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                    return redirect(nxt)
                return redirect(url_for("dashboard.index"))

    facts, rows = _login_facts()
    # Self-registration is offered on the clinical entrance only. `register` fixes the
    # role to Doctor, so a Register tab on an administrator's page would promise an
    # account that cannot open the page it was created from.
    allow_register = (portal["allow_register"]
                      and auth_service.registration_allowed())
    return render_template("auth/login.html", mode="login", error=error,
                           facts=facts, rows=rows, portal=portal,
                           other_portals=_other_portals(portal["key"]),
                           registration_allowed=allow_register)


@bp.route("/login", methods=["GET", "POST"])
def login():
    return _sign_in(PORTALS["clinical"])


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    # Deliberately NOT under the admin blueprint, which is guarded per view by
    # `roles_required`. A sign-in page living behind the guard that redirects to the
    # sign-in page is a redirect loop; keeping it in this blueprint means the guard and
    # the door can never end up pointing at each other.
    return _sign_in(PORTALS["admin"])


@bp.route("/superadmin/login", methods=["GET", "POST"])
def superadmin_login():
    return _sign_in(PORTALS["superadmin"])


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
    # Registration belongs to the clinical entrance, so the tabs and the footer links
    # match the page the "Sign in" tab goes back to.
    return render_template("auth/login.html", mode="register", error=error,
                           form=form, facts=facts, rows=rows,
                           portal=PORTALS["clinical"],
                           other_portals=_other_portals("clinical"),
                           registration_allowed=True)


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    auth_service.logout()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
