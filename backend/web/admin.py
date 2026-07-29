"""
User administration, prediction management and the dataset.

WHO MAY ACT ON WHOM is decided in `_may_manage`, once. Spreading that rule across four
views is how an Admin ends up able to delete a SuperAdmin through the one view that
forgot to check.
"""
from __future__ import annotations

import os
import shutil

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from backend import config
from backend import repositories as db
from backend.services import auth as auth_service

bp = Blueprint("admin", __name__, url_prefix="/admin")

_RANK = {"Doctor": 1, "Admin": 2, "SuperAdmin": 3}


def _may_manage(actor: dict, target: dict) -> bool:
    """
    An actor may only act on a strictly lower rank, and never on themselves.

    Self-exclusion is not politeness: an Admin who bans or demotes their own account
    locks the institution out of its own administration, and nothing in the interface
    can undo it afterwards.
    """
    if actor["id"] == target["id"]:
        return False
    return _RANK.get(actor["role"], 0) > _RANK.get(target["role"], 0)


def _users_of(*roles) -> list[dict]:
    return [u for u in db.get_all_users() if u["role"] in roles]


@bp.route("/doctors")
@auth_service.roles_required("Admin", "SuperAdmin")
def doctors():
    return render_template("pages/users.html", title="Doctor Management",
                           subtitle="Clinicians with access to screening.",
                           users=_users_of("Doctor"), scope="doctors",
                           can_change_role=False)


@bp.route("/admins")
@auth_service.roles_required("SuperAdmin")
def admins():
    return render_template("pages/users.html", title="Admin Management",
                           subtitle="Administrative accounts.",
                           users=_users_of("Admin", "SuperAdmin"), scope="admins",
                           can_change_role=False)


@bp.route("/roles", methods=["GET", "POST"])
@auth_service.roles_required("SuperAdmin")
def roles():
    actor = auth_service.current_user()
    if request.method == "POST":
        try:
            target_id = int(request.form.get("user_id") or 0)
        except ValueError:
            target_id = 0
        new_role = request.form.get("role")
        target = db.get_user_by_id(target_id)
        if not target or new_role not in auth_service.ROLES:
            flash("Select a user and a valid role.", "warning")
        elif target["id"] == actor["id"]:
            flash("You cannot change your own role.", "warning")
        else:
            db.update_user_role(target["id"], new_role, actor["username"])
            flash(f"{target['username']} is now {new_role}.", "success")
        return redirect(url_for("admin.roles"))

    capabilities = [
        ("Run predictions", ["Doctor", "Admin", "SuperAdmin"]),
        ("View own history", ["Doctor", "Admin", "SuperAdmin"]),
        ("View all predictions", ["Admin", "SuperAdmin"]),
        ("Manage doctors", ["Admin", "SuperAdmin"]),
        ("Manage admins", ["SuperAdmin"]),
        ("Upload dataset", ["Admin", "SuperAdmin"]),
        ("Train models", ["SuperAdmin"]),
        ("Toggle models", ["SuperAdmin"]),
        ("View analytics", ["Admin", "SuperAdmin"]),
        ("System audit logs", ["SuperAdmin"]),
    ]
    return render_template("pages/roles.html", users=db.get_all_users(),
                           roles=auth_service.ROLES, capabilities=capabilities)


@bp.route("/users/<int:user_id>/<action>", methods=["POST"])
@auth_service.roles_required("Admin", "SuperAdmin")
def user_action(user_id: int, action: str):
    actor = auth_service.current_user()
    target = db.get_user_by_id(user_id)
    if not target:
        flash("That account no longer exists.", "warning")
        return redirect(request.referrer or url_for("admin.doctors"))
    if not _may_manage(actor, target):
        flash("You cannot act on that account.", "warning")
        return redirect(request.referrer or url_for("admin.doctors"))

    if action == "ban":
        db.ban_user(user_id, actor["username"])
        flash(f"{target['username']} suspended.", "success")
    elif action == "unban":
        db.unban_user(user_id, actor["username"])
        flash(f"{target['username']} reinstated.", "success")
    elif action == "delete":
        if (request.form.get("confirm") or "").strip() != target["username"]:
            flash("Type the username exactly to confirm deletion.", "warning")
        else:
            db.delete_user(user_id, actor["username"])
            flash(f"{target['username']} deleted.", "success")
    else:
        flash("Unknown action.", "warning")
    return redirect(request.referrer or url_for("admin.doctors"))


@bp.route("/predictions")
@auth_service.roles_required("Admin", "SuperAdmin")
def predictions():
    rows = db.get_predictions()
    band = (request.args.get("band") or "").strip()
    if band:
        rows = [r for r in rows if (r.get("risk_band") or "").upper() == band.upper()]
    return render_template("pages/predictions.html", rows=rows[:300],
                           total=len(rows), band=band)


@bp.route("/predictions/<int:pred_id>/delete", methods=["POST"])
@auth_service.roles_required("Admin", "SuperAdmin")
def delete_prediction(pred_id: int):
    actor = auth_service.current_user()
    db.delete_prediction(pred_id, actor["username"])
    flash(f"Assessment {pred_id} deleted.", "success")
    return redirect(url_for("admin.predictions"))


@bp.route("/predictions/clear", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def clear_predictions():
    actor = auth_service.current_user()
    if (request.form.get("confirm") or "").strip() != "DELETE ALL":
        flash("Type DELETE ALL exactly to confirm.", "warning")
    else:
        db.clear_all_predictions(actor["username"])
        flash("All assessments cleared.", "success")
    return redirect(url_for("admin.predictions"))


@bp.route("/dataset", methods=["GET", "POST"])
@auth_service.roles_required("Admin", "SuperAdmin")
def dataset():
    actor = auth_service.current_user()
    if request.method == "POST":
        upload = request.files.get("dataset")
        if not upload or not upload.filename:
            flash("Choose a CSV file to upload.", "warning")
        elif not secure_filename(upload.filename).lower().endswith(".csv"):
            flash("The training dataset must be a .csv file.", "warning")
        else:
            # The previous dataset is kept beside the new one. Replacing the training
            # data is not reversible from the interface otherwise, and the models in
            # models/ were fitted on the file being overwritten.
            if os.path.exists(config.DATASET_CSV):
                shutil.copy2(config.DATASET_CSV, config.DATASET_CSV + ".previous")
            upload.save(config.DATASET_CSV)
            db.log_activity(actor["id"], actor["username"], "Dataset Upload",
                            f"Replaced heart.csv with {upload.filename}.")
            flash("Dataset replaced. Retrain the models to use it.", "success")
        return redirect(url_for("admin.dataset"))

    info = {"exists": os.path.exists(config.DATASET_CSV)}
    if info["exists"]:
        info["size_kb"] = os.path.getsize(config.DATASET_CSV) / 1024
        with open(config.DATASET_CSV, encoding="utf-8", errors="replace") as fh:
            header = fh.readline().strip()
            info["columns"] = header.split(";") if ";" in header else header.split(",")
            info["rows"] = sum(1 for _ in fh)
    return render_template("pages/dataset.html", info=info,
                           has_backup=os.path.exists(config.DATASET_CSV + ".previous"))
