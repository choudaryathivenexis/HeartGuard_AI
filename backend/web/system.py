"""SuperAdmin: settings, model toggles, retraining, audit logs, backup and restore."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from flask import (Blueprint, flash, redirect, render_template, request,
                   send_file, url_for)

from backend import config
from backend.domain import artifacts
from backend.ml import registry
from backend import repositories as db
from backend.services import analytics
from backend.services import auth as auth_service

bp = Blueprint("system", __name__, url_prefix="/system")

BACKUP_DIR = os.path.join(config.PROJECT_ROOT, "backups")


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


def _backups() -> list[dict]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        path = os.path.join(BACKUP_DIR, name)
        if os.path.isfile(path):
            stat = os.stat(path)
            out.append({"name": name, "size_kb": stat.st_size / 1024,
                        "created": datetime.fromtimestamp(stat.st_mtime)
                                            .strftime("%Y-%m-%d %H:%M:%S")})
    return out


@bp.route("/backup", methods=["GET"])
@auth_service.roles_required("SuperAdmin")
def backup():
    return render_template("pages/backup.html", backups=_backups())


@bp.route("/backup/create", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def create_backup():
    actor = auth_service.current_user()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"heartguard-{stamp}.db"
    # SQLite's backup API, not a file copy: in WAL mode the newest commits live
    # in the -wal sidecar and a plain copy of the .db can miss them.
    db.backup_to(os.path.join(BACKUP_DIR, name))
    db.log_activity(actor["id"], actor["username"], "Backup Created", name)
    flash(f"Backup {name} created.", "success")
    return redirect(url_for("system.backup"))


@bp.route("/backup/<name>/download")
@auth_service.roles_required("SuperAdmin")
def download_backup(name: str):
    # basename() strips any traversal in the URL segment. Without it, a crafted name
    # reads arbitrary files off the server.
    safe = os.path.basename(name)
    path = os.path.join(BACKUP_DIR, safe)
    if not os.path.isfile(path):
        flash("That backup no longer exists.", "warning")
        return redirect(url_for("system.backup"))
    return send_file(path, as_attachment=True, download_name=safe)


@bp.route("/backup/<name>/restore", methods=["POST"])
@auth_service.roles_required("SuperAdmin")
def restore_backup(name: str):
    actor = auth_service.current_user()
    safe = os.path.basename(name)
    path = os.path.join(BACKUP_DIR, safe)
    if not os.path.isfile(path):
        flash("That backup no longer exists.", "warning")
    elif (request.form.get("confirm") or "").strip() != safe:
        flash("Type the backup filename exactly to confirm the restore.", "warning")
    else:
        # The CURRENT database is backed up first. Restore overwrites live patient
        # records; without this step an accidental restore is unrecoverable.
        os.makedirs(BACKUP_DIR, exist_ok=True)
        pre = f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        db.backup_to(os.path.join(BACKUP_DIR, pre))
        # Restoring IS a file copy - the incoming file becomes the database. Any
        # stale -wal/-shm sidecars must go with it, or SQLite replays them over
        # the restored file and undoes the restore.
        shutil.copy2(path, config.DB_PATH)
        for sidecar in (config.DB_PATH + "-wal", config.DB_PATH + "-shm"):
            if os.path.exists(sidecar):
                os.remove(sidecar)
        db.log_activity(actor["id"], actor["username"], "Backup Restored",
                        f"{safe} (previous state saved as {pre})")
        flash(f"Restored {safe}. The previous database was saved as {pre}.", "success")
    return redirect(url_for("system.backup"))
