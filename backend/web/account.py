"""The signed-in user's own profile."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from backend import repositories as db
from backend.services import auth as auth_service
from backend.services import validation

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

        # The SAME rules registration uses, from the same module. This form previously
        # checked only that a name and an email were non-empty and that a new password
        # was 8 characters — so an account created under the full policy could then be
        # edited straight past it. A password policy that applies only at registration
        # is a policy every existing account can walk around.
        problem = validation.profile_error(fullname, email, specialisation,
                                           password, confirm)
        if problem:
            flash(problem, "warning")
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
