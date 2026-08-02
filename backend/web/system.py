"""SuperAdmin: settings, model toggles, retraining, audit logs, backup and restore."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, send_file, url_for)

from backend import config
from backend.domain import artifacts
from backend.ml import registry
from backend import repositories as db
from backend.repositories import backup as db_backup
from backend.services import analytics
from backend.services import auth as auth_service

bp = Blueprint("system", __name__, url_prefix="/system")


@bp.route("/settings", methods=["GET", "POST"])
@auth_service.roles_required("SuperAdmin")
def settings():
    actor = auth_service.current_user()
    if request.method == "POST":
        allow = request.form.get("allow_registration") == "on"
        config.set_setting("allow_registration", allow)

        raw = (request.form.get("risk_threshold") or "").strip()
        if raw == "":
            # Blank clears the override and returns every model to its own derived,
            # age-stratified operating point. That is the intended default and must be
            # reachable from the form, not only by editing JSON.
            config.set_setting("risk_threshold", None)
        else:
            try:
                value = float(raw)
                if not 0.05 <= value <= 0.95:
                    raise ValueError
                config.set_setting("risk_threshold", value)
            except ValueError:
                flash("The threshold override must be a number between 0.05 and 0.95.",
                      "warning")
                return redirect(url_for("system.settings"))

        db.log_activity(actor["id"], actor["username"], "Settings Updated",
                        f"registration={allow}, threshold_override={raw or 'cleared'}")
        flash("Settings saved.", "success")
        return redirect(url_for("system.settings"))

    return render_template("pages/settings.html",
                           allow_registration=config.get_setting("allow_registration", True),
                           threshold_override=config.get_setting("risk_threshold"))


@bp.route("/models", methods=["GET", "POST"])
@auth_service.roles_required("SuperAdmin")
def models():
    actor = auth_service.current_user()
    if request.method == "POST":
        cfg = {name: (request.form.get(f"model_{i}") == "on")
               for i, name in enumerate(config.MODEL_FILES)}
        if not any(cfg.values()):
            flash("At least one model must stay enabled.", "warning")
        else:
            artifacts.save_model_config(cfg)
            registry.reload_registry()
            db.log_activity(actor["id"], actor["username"], "Models Toggled",
                            ", ".join(f"{k}={'on' if v else 'off'}"
                                      for k, v in cfg.items()))
            flash("Model selection saved.", "success")
        return redirect(url_for("system.models"))

    reg = registry.get_registry()
    return render_template("pages/models.html",
                           enabled=artifacts.load_model_config(),
                           loaded=reg.models, errors=reg.errors,
                           names=list(config.MODEL_FILES),
                           runs=db.get_training_runs(),
                           results=artifacts.load_results())


@bp.route("/models/train", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def train():
    """
    Retrain from the current dataset.

    Run as a SUBPROCESS, not imported and called. Training loads its own copies of the
    estimators and rebinds matplotlib state; doing that inside the web process would
    leave the server holding two sets of models and a changed global backend. A crashed
    subprocess costs a failed training run, not the application.
    """
    actor = auth_service.current_user()
    if not config.project_dir_writable():
        # Training writes new pickles into models/. On a read-only host it would run
        # for however long the estimators take and then fail at the final write, having
        # burned the time and changed nothing.
        flash(config.READ_ONLY_NOTICE, "warning")
        return redirect(url_for("system.models"))

    script = os.path.join(config.PROJECT_ROOT, "train_models.py")
    if not os.path.exists(script):
        flash("train_models.py is not present.", "danger")
        return redirect(url_for("system.models"))

    started = time.time()
    try:
        proc = subprocess.run([sys.executable, script], cwd=config.PROJECT_ROOT,
                              capture_output=True, text=True, timeout=3600)
        duration = time.time() - started
        ok = proc.returncode == 0
        tail = (proc.stdout or proc.stderr or "")[-4000:]
        db.log_training_run(actor["username"], "success" if ok else "failed",
                            duration, tail)
        if ok:
            registry.reload_registry()
            flash(f"Training finished in {duration:.0f}s. Models reloaded.", "success")
        else:
            flash("Training failed. See the run log below.", "danger")
    except subprocess.TimeoutExpired:
        db.log_training_run(actor["username"], "timeout", time.time() - started, "")
        flash("Training exceeded the one-hour limit and was stopped.", "danger")
    return redirect(url_for("system.models"))


@bp.route("/analytics", endpoint="analytics")
@auth_service.roles_required("Admin", "SuperAdmin")
def analytics_view():
    user = auth_service.current_user()
    return render_template("pages/analytics.html",
                           summary=analytics.dashboard_summary(user),
                           mix=analytics.risk_mix(user),
                           series=analytics.activity_series(user),
                           outcomes=analytics.outcome_summary()['summary'],
                           leaderboard=analytics.model_leaderboard())


@bp.route("/logs", methods=["GET"])
@auth_service.roles_required("SuperAdmin")
def logs():
    return render_template("pages/logs.html", rows=db.get_system_logs(limit=500))


@bp.route("/logs/clear", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def clear_logs():
    actor = auth_service.current_user()
    if (request.form.get("confirm") or "").strip() != "CLEAR LOGS":
        flash("Type CLEAR LOGS exactly to confirm.", "warning")
    else:
        db.clear_system_logs(actor["username"])
        flash("Audit log cleared.", "success")
    return redirect(url_for("system.logs"))


# ════════════════════════════════════════════════════════════════════════
# Backup and restore
# ════════════════════════════════════════════════════════════════════════
# A backup is a DOWNLOAD and a restore is an UPLOAD. Nothing is written to the server's
# filesystem, because the server may not have a writable one — the previous version
# wrote snapshots into `backups/` and served them from there, which on a deployed host
# is an OSError on the one button whose whole purpose is to protect data.
#
# The file is portable between backends, so a populated local SQLite database can be
# downloaded and restored straight into a deployed Postgres one. That is the migration
# path off a laptop.

@bp.route("/backup", methods=["GET"])
@auth_service.roles_required("SuperAdmin")
def backup():
    return render_template("pages/backup.html", summary=db_backup.summary())


@bp.route("/backup/download")
@auth_service.roles_required("SuperAdmin")
def download_backup():
    actor = auth_service.current_user()
    payload = db_backup.export_bytes()
    name = f"heartguard-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    db.log_activity(actor["id"], actor["username"], "Backup Downloaded",
                    f"{name} ({len(payload) / 1024:.0f} KB)")
    # BytesIO, not a temporary file: send_file streams it from memory and there is no
    # path to clean up afterwards or leave behind on a shared host.
    return send_file(io.BytesIO(payload), mimetype="application/json",
                     as_attachment=True, download_name=name)


@bp.route("/backup/restore", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def restore_backup():
    actor = auth_service.current_user()

    # The confirmation is checked FIRST, before the upload is even parsed. A restore
    # replaces every patient record in the database, and the cost of getting here by
    # accident is the whole dataset.
    if (request.form.get("confirm") or "").strip() != "RESTORE":
        flash("Type RESTORE exactly to confirm.", "warning")
        return redirect(url_for("system.backup"))

    upload = request.files.get("backup")
    if not upload or not upload.filename:
        flash("Choose a backup file to restore.", "warning")
        return redirect(url_for("system.backup"))

    try:
        document = json.loads(upload.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        flash("That file is not readable JSON.", "danger")
        return redirect(url_for("system.backup"))

    problem = db_backup.validate(document)
    if problem:
        flash(problem, "danger")
        return redirect(url_for("system.backup"))

    try:
        counts = db_backup.import_document(document)
    except Exception as exc:                                   # noqa: BLE001
        # import_document rolls back, so the database is untouched. Report the failure
        # rather than a generic 500: the operator needs to know their data is intact.
        current_app.logger.exception("Restore failed")
        flash(f"Restore failed and nothing was changed ({type(exc).__name__}).",
              "danger")
        return redirect(url_for("system.backup"))

    restored = ", ".join(f"{n} {t}" for t, n in counts.items() if n)
    db.log_activity(actor["id"], actor["username"], "Backup Restored",
                    f"{upload.filename}: {restored}")
    flash(f"Restored from {upload.filename} — {restored}.", "success")
    return redirect(url_for("system.backup"))
