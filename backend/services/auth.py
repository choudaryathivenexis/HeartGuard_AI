"""
Authentication, session handling and role-based access control.

Roles are hierarchical in capability but NOT in navigation: an Admin is not a Doctor
with extras, it is a different job with a different page set. That is why permissions
are declared per page below rather than inferred from a rank number — inferring it is
how a Doctor-only clinical page ends up reachable by an accountant with a high rank.
"""
from __future__ import annotations

from functools import wraps

from flask import flash, g, redirect, request, session, url_for

from backend import config
from backend import repositories as db

__all__ = [
    "ROLES", "NAV", "login", "logout", "current_user", "login_required",
    "roles_required", "can_access", "nav_for", "registration_allowed",
]

ROLE_DOCTOR = "Doctor"
ROLE_ADMIN = "Admin"
ROLE_SUPERADMIN = "SuperAdmin"
ROLES = [ROLE_DOCTOR, ROLE_ADMIN, ROLE_SUPERADMIN]

# The navigation, declared once. Each entry is (endpoint, label, icon, groups).
# `roles` is the access control list AND the menu source, so a page cannot appear in a
# menu it is not permitted to open — the two cannot drift apart because they are one
# declaration.
NAV = [
    ("Clinical", [
        ("dashboard.index",        "Dashboard",              "dashboard",    ROLES),
        ("screening.new",          "Heart Disease Prediction", "prediction", [ROLE_DOCTOR]),
        ("patients.index",         "Patient Management",     "patients",
         [ROLE_DOCTOR, ROLE_ADMIN]),
        ("screening.history",      "Prediction History",     "history",  [ROLE_DOCTOR]),
        ("reports.index",          "Reports",                "reports",
         [ROLE_DOCTOR, ROLE_ADMIN]),
    ]),
    ("Model", [
        ("performance.index",      "Model Performance",      "performance",   ROLES),
        ("system.models",          "ML Model Management",    "training",  [ROLE_SUPERADMIN]),
    ]),
    ("Administration", [
        ("admin.doctors",          "Doctor Management",      "doctors",
         [ROLE_ADMIN, ROLE_SUPERADMIN]),
        ("admin.admins",           "Admin Management",       "admin",    [ROLE_SUPERADMIN]),
        ("admin.predictions",      "Prediction Management",  "prediction",   [ROLE_ADMIN]),
        ("admin.roles",            "Role & Permission Management", "roles",
         [ROLE_SUPERADMIN]),
        ("admin.dataset",          "Dataset Management",     "dataset", [ROLE_ADMIN]),
    ]),
    ("System", [
        ("system.settings",        "System Settings",        "settings", [ROLE_SUPERADMIN]),
        ("system.analytics",       "Analytics",              "analytics",
         [ROLE_ADMIN, ROLE_SUPERADMIN]),
        ("system.logs",            "Activity Logs",          "logs",    [ROLE_SUPERADMIN]),
        ("system.backup",          "Backup & Restore",       "backup", [ROLE_SUPERADMIN]),
        ("account.profile",        "Profile",                "profile",    ROLES),
    ]),
]

_ACL = {endpoint: roles
        for _group, items in NAV
        for endpoint, _label, _icon, roles in items}


def registration_allowed() -> bool:
    """Honour the `allow_registration` system setting."""
    return bool(config.get_setting("allow_registration", True))


def login(username: str, password: str) -> tuple[dict | None, str | None]:
    """
    Validate credentials. Returns (user, error).

    The repository returns (row_or_None, status) where status is 'ok', 'invalid' or
    'banned'. A suspended account gets a DIFFERENT message from a wrong password on
    purpose: the user is legitimate and needs to know to contact an administrator
    rather than keep retrying a password that is already correct.
    """
    user, status = db.validate_login(username, password)
    if status == "banned":
        return None, "This account has been suspended. Contact an administrator."
    if not user or status != "ok":
        return None, "Incorrect username or password."
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = False
    db.log_activity(user["id"], user["username"], "Login",
                    f"Authenticated as {user['role']}.")
    return user, None


def logout() -> None:
    user = current_user()
    if user:
        db.log_activity(user["id"], user["username"], "Logout", "User session ended.")
    session.clear()


def current_user() -> dict | None:
    """
    The signed-in user, re-read from the database once per request.

    Re-read rather than stored in the session, so a role change, a ban or a deletion
    takes effect on the user's NEXT request instead of whenever they happen to sign in
    again. A revoked administrator keeping their powers until they choose to log out is
    not access control.
    """
    if "user" in g:
        return g.user
    uid = session.get("user_id")
    g.user = None
    if uid is not None:
        record = db.get_user_by_id(uid)
        if record and not record.get("is_banned"):
            g.user = record
        else:
            session.clear()
    return g.user


def can_access(endpoint: str, user: dict | None) -> bool:
    if not user:
        return False
    allowed = _ACL.get(endpoint)
    # Endpoints not in the navigation (downloads, chart images, sub-actions) inherit
    # "any signed-in user" and rely on their own blueprint guard.
    return True if allowed is None else user.get("role") in allowed


def nav_for(user: dict | None) -> list[tuple[str, list]]:
    """The menu this user may actually open, with empty groups dropped."""
    if not user:
        return []
    groups = []
    for title, items in NAV:
        visible = [(endpoint, label, icon)
                   for endpoint, label, icon, roles in items
                   if user["role"] in roles]
        if visible:
            groups.append((title, visible))
    return groups


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """
    Guard a view by role.

    Refuses with a redirect and an explanation rather than a bare 403: the user is
    signed in and legitimate, they simply cannot open this page, and a blank error page
    reads as a broken application.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return redirect(url_for("auth.login", next=request.path))
            if user["role"] not in roles:
                flash("Your role does not have access to that page.", "warning")
                return redirect(url_for("dashboard.index"))
            return view(*args, **kwargs)
        return wrapped
    return decorator
