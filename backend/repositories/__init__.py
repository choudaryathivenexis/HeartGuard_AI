"""
Data access, split by the thing being stored.

    connection.py   opening the database, creating the schema
    security.py     password hashing and verification
    users.py        accounts, authentication, roles
    patients.py     patient entities and their timeline
    predictions.py  assessments and recorded outcomes
    audit.py        activity log and training runs

WHY THIS PACKAGE RE-EXPORTS EVERYTHING
Callers import one name and get the whole data layer. The alternative is every service
importing four modules and knowing which function lives in which — so moving a function
between modules would become a change to every call site instead of one line here.

`audit` sits at the bottom of the dependency order on purpose: every other module
records what it did, so if audit imported any of them the package would not import.
"""
from __future__ import annotations

from backend.config import DB_PATH

from .audit import (clear_system_logs, get_system_logs, get_training_runs,
                    log_activity, log_training_run)
from .connection import (BASE_DIR, SEED_CREDENTIALS, backup_to, connect,
                         init_db)
from .patients import (delete_patient, get_patient_timeline, get_patients,
                       upsert_patient)
from .predictions import (add_prediction, clear_all_predictions,
                          delete_prediction, get_outcome_stats, get_predictions,
                          record_outcome)
from .security import hash_password, verify_password
from .users import (ban_user, delete_user, get_all_users, get_user_by_id,
                    register_user, unban_user, update_user_profile,
                    update_user_role, validate_login)

__all__ = [
    "connect", "init_db", "backup_to", "BASE_DIR", "SEED_CREDENTIALS",
    "DB_PATH",
    "hash_password", "verify_password",
    "validate_login", "register_user", "get_all_users", "get_user_by_id",
    "update_user_profile", "update_user_role", "ban_user", "unban_user",
    "delete_user",
    "upsert_patient", "get_patients", "get_patient_timeline", "delete_patient",
    "add_prediction", "get_predictions", "delete_prediction",
    "clear_all_predictions", "record_outcome", "get_outcome_stats",
    "log_activity", "get_system_logs", "clear_system_logs", "log_training_run",
    "get_training_runs",
]
