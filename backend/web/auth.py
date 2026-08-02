"""Sign in, register, sign out."""
from __future__ import annotations

import re

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

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
        "submit": "Sign in",
        "role_icon": "doctors",
        "role_title": "Signing in as a Doctor",
        # Truthful about the exception rather than tidy. This door admits every role —
        # see the note above — and a clinician told "Doctors only" who then watches an
        # administrator sign in at the same page learns that the interface tells them
        # convenient things rather than true ones.
        "role_note": "The clinical console: run screenings, review patients and export "
                     "reports. Administrators may also sign in here.",
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
        "submit": "Sign in as Administrator",
        "role_icon": "admin",
        "role_title": "Administrator accounts only",
        "role_note": "Doctors cannot sign in here. Use the clinician entrance below "
                     "to reach the screening console.",
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
        "submit": "Sign in as System Administrator",
        "role_icon": "roles",
        "role_title": "System administrator accounts only",
        "role_note": "Separate from Administrator: these are different jobs, not "
                     "ranks. Use the links below if you are at the wrong entrance.",
        "roles": (auth_service.ROLE_SUPERADMIN,),
        "allow_register": False,
    },
}


def _other_portals(current_key: str) -> list[dict]:
    """The other entrances, for the links at the foot of the card."""
    return [PORTALS[key] for key in PORTAL_ORDER if key != current_key]


# `_login_facts()` was removed with the panel that displayed it. It read the AUC, the
# operating point and the calibration gap out of the shipped artifacts and printed them
# beside the sign-in form. The numbers were real, and the page is not where they belong:
# they are on Model Performance, where a reader can see the confidence intervals and the
# per-model breakdown next to them, and where they can act on what they say.


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

    # Self-registration is offered on the clinical entrance only. `register` fixes the
    # role to Doctor, so a Register tab on an administrator's page would promise an
    # account that cannot open the page it was created from.
    allow_register = (portal["allow_register"]
                      and auth_service.registration_allowed())
    return render_template("auth/login.html", mode="login", error=error,
                           portal=portal,
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


# ════════════════════════════════════════════════════════════════════════
# Registration validation
# ════════════════════════════════════════════════════════════════════════
# THE SAME RULES THE BROWSER ENFORCES, enforced again here. The `required`,
# `minlength`, `maxlength` and `pattern` attributes on the form are a courtesy: they put
# the message beside the field instead of after a round trip. They are also two lines of
# devtools away from being deleted, and curl never sees them at all. So every constraint
# below has a twin in frontend/templates/auth/login.html, and this is the one that
# decides.
#
# The messages name the field and the rule. "Invalid input" tells a user that something
# is wrong and leaves them to find out what by trial.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")

# Deliberately permissive. A regex that tries to decide whether an address is
# deliverable rejects real ones — plus-addressing, new TLDs, non-ASCII local parts —
# and the only test that actually proves an address works is sending mail to it. This
# checks the shape a typo breaks: one @, something either side, a dot in the domain.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PASSWORD_MIN = 8
_PASSWORD_MAX = 128          # bcrypt-style truncation is not in play, but an unbounded
                             # field is an unbounded hash input


def _validation_error(form: dict, password: str, confirm: str) -> str | None:
    """The first problem with a registration submission, or None if it is sound."""
    if not form["fullname"] or not form["username"] or not form["email"]:
        return "Full name, username and email are all required."
    if not (2 <= len(form["fullname"]) <= 80):
        return "Enter a full name between 2 and 80 characters."
    if not _USERNAME_RE.match(form["username"]):
        return ("Usernames are 3 to 32 characters and may contain letters, digits, "
                "dot, underscore or hyphen only.")
    if len(form["email"]) > 120 or not _EMAIL_RE.match(form["email"]):
        return "Enter a valid email address, for example name@hospital.org"
    if len(form["specialisation"]) > 80:
        return "Keep the specialisation under 80 characters."
    if not password:
        return "Choose a password."
    if not (_PASSWORD_MIN <= len(password) <= _PASSWORD_MAX):
        return (f"Use a password between {_PASSWORD_MIN} and {_PASSWORD_MAX} "
                f"characters.")
    if password != confirm:
        return "The two passwords do not match."
    return None


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
        error = _validation_error(form, password, confirm)
        if error is None:
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

    # Registration belongs to the clinical entrance, so the tabs and the footer links
    # match the page the "Sign in" tab goes back to.
    return render_template("auth/login.html", mode="register", error=error,
                           form=form, portal=PORTALS["clinical"],
                           other_portals=_other_portals("clinical"),
                           registration_allowed=True)


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    auth_service.logout()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
