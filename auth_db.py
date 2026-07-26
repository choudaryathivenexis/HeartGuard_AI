import sqlite3
import hashlib
import hmac
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "heartguard.db")

# ─────────────────────────────────────────────
# Password hashing  (BUG-11)
# ─────────────────────────────────────────────
# Passwords were previously stored as bare, unsalted SHA-256 digests — identical
# passwords produced identical hashes and the whole table fell to a rainbow table.
#
# They are now PBKDF2-HMAC-SHA256 with a unique 16-byte salt and 200,000 iterations,
# stored as:  pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
#
# PBKDF2 is used rather than bcrypt/argon2 because it is in the Python standard
# library — no new dependency, so the project still installs from requirements.txt
# alone. Legacy 64-char SHA-256 digests are still *verified* (so nobody is locked
# out) and are transparently re-hashed to PBKDF2 on the next successful login.

PBKDF2_ITERATIONS = 200_000
PBKDF2_PREFIX = "pbkdf2_sha256"


def hash_password(password: str, salt: bytes = None,
                  iterations: int = PBKDF2_ITERATIONS) -> str:
    """Derive a salted PBKDF2 hash in the storage format described above."""
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_PREFIX}${iterations}${salt.hex()}${dk.hex()}"


def _is_legacy_hash(stored: str) -> bool:
    """True for the old bare SHA-256 digests (64 hex chars, no algorithm prefix)."""
    return bool(stored) and "$" not in stored and len(stored) == 64


def verify_password(password: str, stored: str) -> bool:
    """
    Constant-time password check supporting both the new and legacy formats.

    hmac.compare_digest avoids leaking hash content through comparison timing.
    """
    if not stored:
        return False
    if _is_legacy_hash(stored):
        legacy = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(legacy, stored)
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != PBKDF2_PREFIX:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _connect():
    """
    Open a connection with foreign-key enforcement switched on.

    FIXED (BUG-20): `predictions.user_id` declares ON DELETE CASCADE, but SQLite
    ignores foreign keys unless this PRAGMA is set per-connection — so deleting a
    user silently orphaned all of their prediction rows.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = _connect()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        fullname TEXT,
        email TEXT,
        specialisation TEXT DEFAULT '',
        is_banned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

    c.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        age REAL, gender INTEGER, height REAL, weight REAL,
        ap_hi REAL, ap_lo REAL, cholesterol INTEGER, gluc INTEGER,
        smoke INTEGER, alco INTEGER, active INTEGER,
        predicted_class INTEGER, probability REAL, model_used TEXT,
        patient_name TEXT DEFAULT '', notes TEXT DEFAULT '',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")

    # ─────────────────────────────────────────────
    # Patients  (Run 7)
    # ─────────────────────────────────────────────
    # Before this table existed, `predictions` conflated an EVENT with a PERSON: the
    # only patient identity was a free-text name on each row, so the same patient
    # assessed twice produced two unrelated records. Cardiovascular risk management is
    # inherently longitudinal — you track a trajectory, not a snapshot — so a first
    # class patient entity is a prerequisite, not a nicety.
    c.execute("""
        CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_code TEXT UNIQUE NOT NULL,
        fullname TEXT NOT NULL,
        gender INTEGER,
        notes TEXT DEFAULT '',
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        )""")

    c.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, action TEXT NOT NULL,
        details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

    c.execute("""
        CREATE TABLE IF NOT EXISTS training_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        triggered_by INTEGER, status TEXT DEFAULT 'running',
        duration_s REAL, results_json TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

    # ─────────────────────────────────────────────
    # Schema migration  (Run 7)
    # ─────────────────────────────────────────────
    # Additive, idempotent migration so existing databases keep their data. Each new
    # column addresses a specific gap:
    #
    #   patient_ref          links an assessment to a patient entity (longitudinal view)
    #   model_version /
    #   model_manifest_sha   WHICH model produced this score. Previously only a label
    #                        ("Ensemble Voting") was stored, so after a retrain every
    #                        historical prediction became unexplainable — a real
    #                        compliance gap for a clinical decision-support record.
    #   threshold_used /
    #   risk_band            the operating point in force at prediction time. Thresholds
    #                        are now age-stratified and configurable, so a probability
    #                        alone no longer reconstructs the decision.
    #   outcome*             clinician confirmation, enabling drift monitoring and
    #                        continuous validation against reality.
    _existing = {r[1] for r in c.execute("PRAGMA table_info(predictions)")}
    for _col, _ddl in [
        ("patient_ref",        "INTEGER"),
        ("model_version",      "TEXT DEFAULT ''"),
        ("model_manifest_sha", "TEXT DEFAULT ''"),
        ("threshold_used",     "REAL"),
        ("risk_band",          "TEXT DEFAULT ''"),
        ("outcome",            "INTEGER"),            # NULL unknown / 0 not confirmed / 1 confirmed
        ("outcome_notes",      "TEXT DEFAULT ''"),
        ("outcome_by",         "TEXT DEFAULT ''"),
        ("outcome_at",         "TIMESTAMP"),
        # BUG-23: was this patient outside the model's training envelope? An
        # extrapolated score must be identifiable forever after, not just flagged
        # on screen once — a reviewer auditing a past decision needs to know the
        # prediction was made outside the model's supported population.
        ("extrapolated",       "INTEGER DEFAULT 0"),
        ("applicability_notes", "TEXT DEFAULT ''"),
    ]:
        if _col not in _existing:
            c.execute(f"ALTER TABLE predictions ADD COLUMN {_col} {_ddl}")

    c.execute("CREATE INDEX IF NOT EXISTS idx_pred_patient ON predictions(patient_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pred_outcome ON predictions(outcome)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pred_user ON predictions(user_id)")

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        defaults = [
            ("doctor",   hash_password("doctor123"),   "Doctor",
             "Dr. John Smith",       "jsmith@heartguard.ai",    "Cardiologist"),
            ("admin",    hash_password("admin123"),    "Admin",
             "Admin User",           "admin@heartguard.ai",     "System Admin"),
            ("superadmin", hash_password("superadmin123"), "SuperAdmin",
             "Dr. Sarah Jenkins MD", "sjenkins@heartguard.ai",  "Cardiologist"),
        ]
        c.executemany("""
            INSERT INTO users (username,password_hash,role,fullname,email,specialisation)
            VALUES (?,?,?,?,?,?)
        """, defaults)
        c.execute("""
            INSERT INTO system_logs (user_id,username,action,details)
            VALUES (1,'system','DB Initialised','Default accounts seeded successfully.')
        """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────
def validate_login(username, password):
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    row = c.fetchone()

    if not row:
        conn.close()
        return None, "invalid"
    if row["is_banned"]:
        conn.close()
        return None, "banned"

    stored = row["password_hash"]
    if not verify_password(password, stored):
        conn.close()
        return None, "invalid"

    # Transparent upgrade: a correct password stored under the old unsalted SHA-256
    # scheme is re-hashed with PBKDF2 now that we hold the plaintext (BUG-11).
    if _is_legacy_hash(stored):
        c.execute("UPDATE users SET password_hash=? WHERE id=?",
                  (hash_password(password), row["id"]))
        conn.commit()

    conn.close()
    return dict(row), "ok"


def register_user(username, password, role, fullname, email, specialisation=""):
    conn = _connect()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO users (username,password_hash,role,fullname,email,specialisation)
            VALUES (?,?,?,?,?,?)
        """, (username, hash_password(password), role, fullname, email, specialisation))
        conn.commit()
        uid = c.lastrowid
        log_activity(uid, username, "Registration", f"New {role} account created.")
        return uid, None
    except sqlite3.IntegrityError:
        return None, "taken"
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
def log_activity(user_id, username, action, details):
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO system_logs (user_id,username,action,details)
        VALUES (?,?,?,?)
    """, (user_id, username, action, details))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# Users CRUD
# ─────────────────────────────────────────────
def get_all_users():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id,username,role,fullname,email,specialisation,is_banned,created_at FROM users ORDER BY id")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def update_user_profile(user_id, fullname, email, specialisation, new_password=None):
    conn = _connect()
    c = conn.cursor()
    if new_password:
        c.execute("UPDATE users SET fullname=?,email=?,specialisation=?,password_hash=? WHERE id=?",
                  (fullname, email, specialisation, hash_password(new_password), user_id))
    else:
        c.execute("UPDATE users SET fullname=?,email=?,specialisation=? WHERE id=?",
                  (fullname, email, specialisation, user_id))
    conn.commit()
    log_activity(user_id, fullname, "Profile Update", "User profile updated.")
    conn.close()


def update_user_role(user_id, new_role, operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
    conn.commit()
    log_activity(None, operator_username, "Role Change", f"User {uname} role changed to {new_role}.")
    conn.close()


def ban_user(user_id, operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET is_banned=1 WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Ban User", f"User {uname} has been banned.")
    conn.close()


def unban_user(user_id, operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET is_banned=0 WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Unban User", f"User {uname} has been unbanned.")
    conn.close()


def delete_user(user_id, operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Delete User", f"Account '{uname}' permanently deleted.")
    conn.close()


# ─────────────────────────────────────────────
# Predictions
# ─────────────────────────────────────────────
def add_prediction(user_id, age, gender, height, weight, ap_hi, ap_lo,
                   cholesterol, gluc, smoke, alco, active,
                   predicted_class, probability, model_used,
                   patient_name="", notes="",
                   patient_ref=None, model_version="", model_manifest_sha="",
                   threshold_used=None, risk_band="",
                   extrapolated=0, applicability_notes=""):
    """
    Persist an assessment.

    Run 7 additions make the record self-describing: it now carries the patient it
    belongs to, the exact model version that produced it, and the operating point in
    force at the time. Without those, a retrained model silently invalidates the
    interpretation of every historical row.
    """
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO predictions
        (user_id,age,gender,height,weight,ap_hi,ap_lo,cholesterol,gluc,
        smoke,alco,active,predicted_class,probability,model_used,patient_name,notes,
        patient_ref,model_version,model_manifest_sha,threshold_used,risk_band,
        extrapolated,applicability_notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (user_id, age, gender, height, weight, ap_hi, ap_lo,
          cholesterol, gluc, smoke, alco, active,
          predicted_class, probability, model_used, patient_name, notes,
          patient_ref, model_version, model_manifest_sha, threshold_used, risk_band,
          int(extrapolated), applicability_notes))
    conn.commit()
    pid = c.lastrowid
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    log_activity(user_id, uname, "Prediction",
                 f"Risk={predicted_class} ({probability:.2%}) via {model_used}.")
    conn.close()
    return pid


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
    conn = _connect()
    conn.row_factory = sqlite3.Row
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
        c.execute("""INSERT INTO patients (patient_code,fullname,gender,notes,created_by)
                     VALUES (?,?,?,?,?)""",
                  (patient_code, fullname, gender, notes, created_by))
        pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid


def get_user_by_id(user_id):
    """
    Current database state for a user id, or None if the account no longer exists.

    Needed for session revalidation (BUG-25): st.session_state.user is a plain dict
    captured at login, so a user deleted, banned or re-roled afterwards continued with
    their original privileges until they chose to log out.
    """
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_patients(created_by=None):
    """Patients with assessment counts and latest risk, for the records page."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
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
    except sqlite3.OperationalError:
        # Older SQLite builds reject NULLS LAST
        c.execute(sql.replace(" NULLS LAST", ""), params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_patient_timeline(patient_ref):
    """Every assessment for one patient, oldest first — the risk trajectory."""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""SELECT p.*, u.fullname AS doctor_name
                 FROM predictions p LEFT JOIN users u ON p.user_id = u.id
                 WHERE p.patient_ref = ? ORDER BY p.timestamp ASC""", (patient_ref,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def delete_patient(patient_ref, operator_username):
    """Remove a patient and detach their assessments (GDPR erasure support)."""
    conn = _connect()
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


# ─────────────────────────────────────────────
# Outcome capture & drift monitoring  (Run 7)
# ─────────────────────────────────────────────
def record_outcome(pred_id, outcome, notes, operator_username):
    """
    Record whether a prediction was clinically confirmed.

    This single field is what turns a one-shot calculator into a monitored system:
    without ground truth arriving back, model drift is undetectable and the deployed
    performance is forever assumed rather than measured.
    """
    conn = _connect()
    c = conn.cursor()
    c.execute("""UPDATE predictions
                 SET outcome=?, outcome_notes=?, outcome_by=?,
                     outcome_at=CURRENT_TIMESTAMP
                 WHERE id=?""", (outcome, notes, operator_username, pred_id))
    conn.commit()
    log_activity(None, operator_username, "Outcome Recorded",
                 f"Prediction {pred_id} outcome set to "
                 f"{'confirmed' if outcome == 1 else 'not confirmed'}.")
    conn.close()


def get_outcome_stats():
    """
    Deployed-performance summary over predictions with confirmed outcomes.

    Deliberately returns raw counts alongside derived rates: with a small number of
    recorded outcomes the rates are noise, and the caller needs to know that rather
    than be handed a confident-looking percentage.
    """
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""SELECT id, probability, predicted_class, outcome, threshold_used,
                        model_version, model_used, timestamp, outcome_at
                 FROM predictions WHERE outcome IS NOT NULL""")
    rows = [dict(r) for r in c.fetchall()]
    c.execute("SELECT COUNT(*) FROM predictions")
    total = c.fetchone()[0]
    conn.close()

    n = len(rows)
    stats = {"total_predictions": total, "with_outcome": n,
             "coverage": (n / total) if total else 0.0}
    if n == 0:
        return stats, rows

    tp = sum(1 for r in rows if r["predicted_class"] == 1 and r["outcome"] == 1)
    fp = sum(1 for r in rows if r["predicted_class"] == 1 and r["outcome"] == 0)
    fn = sum(1 for r in rows if r["predicted_class"] == 0 and r["outcome"] == 1)
    tn = sum(1 for r in rows if r["predicted_class"] == 0 and r["outcome"] == 0)
    probs = [r["probability"] for r in rows if r["probability"] is not None]
    obs = [r["outcome"] for r in rows]

    stats.update({
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "sensitivity": tp / (tp + fn) if (tp + fn) else None,
        "specificity": tn / (tn + fp) if (tn + fp) else None,
        "ppv": tp / (tp + fp) if (tp + fp) else None,
        "npv": tn / (tn + fn) if (tn + fn) else None,
        "observed_rate": sum(obs) / n,
        "mean_predicted": (sum(probs) / len(probs)) if probs else None,
        "calibration_drift": ((sum(probs) / len(probs)) - (sum(obs) / n))
                             if probs else None,
        # Below this, per-metric estimates are too noisy to act on
        "reliable": n >= 30,
    })
    return stats, rows


def get_predictions(user_id=None):
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if user_id:
        c.execute("SELECT * FROM predictions WHERE user_id=? ORDER BY timestamp DESC", (user_id,))
    else:
        c.execute("""
            SELECT p.*, u.fullname as doctor_name, u.username as doctor_username
            FROM predictions p JOIN users u ON p.user_id=u.id
            ORDER BY p.timestamp DESC
        """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def delete_prediction(pred_id, operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM predictions WHERE id=?", (pred_id,))
    conn.commit()
    log_activity(None, operator_username, "Delete Prediction", f"Prediction ID {pred_id} removed.")
    conn.close()


def clear_all_predictions(operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM predictions")
    conn.commit()
    log_activity(None, operator_username, "Clear Predictions", "All predictions purged.")
    conn.close()


# ─────────────────────────────────────────────
# Logs
# ─────────────────────────────────────────────
def get_system_logs(limit=200):
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def clear_system_logs(operator_username):
    conn = _connect()
    c = conn.cursor()
    c.execute("DELETE FROM system_logs WHERE action != 'DB Initialised'")
    conn.commit()
    log_activity(None, operator_username, "Purge Logs", "System audit logs cleared.")
    conn.close()


# ─────────────────────────────────────────────
# Training history
# ─────────────────────────────────────────────
def log_training_run(triggered_by, status, duration_s, results_json):
    conn = _connect()
    c = conn.cursor()
    c.execute("""
        INSERT INTO training_runs (triggered_by,status,duration_s,results_json)
        VALUES (?,?,?,?)
    """, (triggered_by, status, duration_s, results_json))
    conn.commit()
    conn.close()


def get_training_runs():
    conn = _connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM training_runs ORDER BY timestamp DESC LIMIT 20")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# Initialise on import
init_db()
