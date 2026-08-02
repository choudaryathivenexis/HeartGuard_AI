"""
Patient records and their assessment timeline.

A patient is an ENTITY, not a name typed on a form: assessments link to it so a
clinician can see the same person's history across visits.
"""

from __future__ import annotations

from .audit import log_activity
from .connection import OperationalError, connect, insert_returning_id


# ─────────────────────────────────────────────
# Patients  (Run 7)
# ─────────────────────────────────────────────
def upsert_patient(patient_code, fullname, gender, created_by, notes=""):
    """
    Find or create a patient by code, returning its internal id.

    Called on every assessment so repeat visits attach to the same person rather than
    creating a parallel record. The code is the clinician-facing identifier (e.g.
    PT-00123); it is unique, so re-using it is how a follow-up is recorded.
    """
    conn = connect()
    c = conn.cursor()

    # BUG-24: `created_by` is a foreign key to users(id), and foreign keys are now
    # enforced (BUG-20). If an administrator deletes a clinician while that clinician
    # is still logged in, their next assessment raised an unhandled IntegrityError and
    # crashed the whole diagnosis page. Degrade to an unattributed patient record
    # instead — losing the attribution is acceptable, losing the assessment is not.
    if created_by is not None:
        c.execute("SELECT 1 FROM users WHERE id=?", (created_by,))
        if c.fetchone() is None:
            created_by = None

    c.execute("SELECT * FROM patients WHERE patient_code=?", (patient_code,))
    row = c.fetchone()
    if row:
        pid = row["id"]
        # Keep the display name and sex current without losing history
        c.execute("UPDATE patients SET fullname=?, gender=? WHERE id=?",
                  (fullname, gender, pid))
    else:
        pid = insert_returning_id(
            c, """INSERT INTO patients (patient_code,fullname,gender,notes,created_by)
                  VALUES (?,?,?,?,?)""",
            (patient_code, fullname, gender, notes, created_by))
    conn.commit()
    conn.close()
    return pid


def get_patients(created_by=None):
    """Patients with assessment counts and latest risk, for the records page."""
    conn = connect()
    c = conn.cursor()
    sql = """
        SELECT p.*,
               COUNT(pr.id)                AS assessments,
               MAX(pr.timestamp)           AS last_assessed,
               (SELECT probability FROM predictions
                 WHERE patient_ref=p.id ORDER BY timestamp DESC LIMIT 1) AS latest_risk,
               (SELECT risk_band  FROM predictions
                 WHERE patient_ref=p.id ORDER BY timestamp DESC LIMIT 1) AS latest_band
        FROM patients p
        LEFT JOIN predictions pr ON pr.patient_ref = p.id
    """
    params = ()
    if created_by is not None:
        sql += " WHERE p.created_by = ?"
        params = (created_by,)
    sql += " GROUP BY p.id ORDER BY last_assessed DESC NULLS LAST"
    try:
        c.execute(sql, params)
    except OperationalError:
        # Older SQLite builds reject NULLS LAST. Postgres has supported it since 8.3,
        # so this branch is SQLite's in practice — but the rollback is here because on
        # Postgres a failed statement poisons the transaction, and retrying on the same
        # connection without it fails for a reason that has nothing to do with the
        # retry.
        conn.rollback()
        c = conn.cursor()
        c.execute(sql.replace(" NULLS LAST", ""), params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_patient_timeline(patient_ref):
    """Every assessment for one patient, oldest first — the risk trajectory."""
    conn = connect()
    c = conn.cursor()
    c.execute("""SELECT p.*, u.fullname AS doctor_name
                 FROM predictions p LEFT JOIN users u ON p.user_id = u.id
                 WHERE p.patient_ref = ? ORDER BY p.timestamp ASC""", (patient_ref,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def delete_patient(patient_ref, operator_username):
    """Remove a patient and detach their assessments (GDPR erasure support)."""
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT patient_code FROM patients WHERE id=?", (patient_ref,))
    row = c.fetchone()
    code = row[0] if row else "unknown"
    # Scrub identifiers from the clinical record but retain the anonymised assessment
    c.execute("""UPDATE predictions SET patient_ref=NULL, patient_name='[erased]'
                 WHERE patient_ref=?""", (patient_ref,))
    c.execute("DELETE FROM patients WHERE id=?", (patient_ref,))
    conn.commit()
    log_activity(None, operator_username, "Erase Patient",
                 f"Patient {code} erased; assessments retained anonymised.")
    conn.close()
