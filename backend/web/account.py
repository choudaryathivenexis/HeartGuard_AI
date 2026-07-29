"""The signed-in user's own profile."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from backend import repositories as db
from backend.services import auth as auth_service

bp = Blueprint("account", __name__, url_prefix="/account")


@bp.route("/profile", methods=["GET", "POST"])
@auth_service.login_required
def profile():
    user = auth_service.current_user()
    if request.method == "POST":
        fullname = (request.form.get("fullname") or "").strip()
        email = (request.form.get("email") or "").strip()
        specialisation = (request.form.get("specialisation") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if not fullname or not email:
            flash("Name and email are both required.", "warning")
        elif password and password != confirm:
            flash("The two passwords do not match.", "warning")
        elif password and len(password) < 8:
            flash("Use a password of at least 8 characters.", "warning")
        else:
            # The role is never taken from this form. A user editing their own profile
            # must not be able to promote themselves by posting a role field.
            db.update_user_profile(user["id"], fullname, email, specialisation,
                                   new_password=password or None)
            db.log_activity(user["id"], user["username"], "Profile Updated",
                            "Own profile edited.")
            flash("Profile updated.", "success")
        return redirect(url_for("account.profile"))

    return render_template("pages/profile.html",
                           assessments=len(db.get_predictions(user_id=user["id"])))
