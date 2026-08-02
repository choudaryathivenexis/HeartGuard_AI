"""
The audit trail: activity log and training runs.

This module deliberately has NO dependency on the other repositories. Everything else
imports it to record what it did, so a cycle here would make the whole package
unimportable.
"""

from __future__ import annotations

from .connection import connect


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
def log_activity(user_id, username, action, details):
    conn = connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO system_logs (user_id,username,action,details)
        VALUES (?,?,?,?)
    """, (user_id, username, action, details))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Logs
# ─────────────────────────────────────────────
def get_system_logs(limit=200):
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def clear_system_logs(operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM system_logs WHERE action != 'DB Initialised'")
    conn.commit()
    log_activity(None, operator_username, "Purge Logs", "System audit logs cleared.")
    conn.close()


# ─────────────────────────────────────────────
# Training history
# ─────────────────────────────────────────────
def log_training_run(triggered_by, status, duration_s, results_json):
    conn = connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO training_runs (triggered_by,status,duration_s,results_json)
        VALUES (?,?,?,?)
    """, (triggered_by, status, duration_s, results_json))
    conn.commit()
    conn.close()


def get_training_runs():
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT * FROM training_runs ORDER BY timestamp DESC LIMIT 20")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
