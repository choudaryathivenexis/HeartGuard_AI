"""
Database connection and schema creation.

Every other repository module opens its connection through `connect()` here, so the
path is resolved in exactly one place — and that place reads it from backend.config
rather than from `__file__`. Deriving it from the module's own location is what once
made this package create an empty database beside itself after being moved.
"""

from __future__ import annotations

import sqlite3

from backend.config import DB_PATH, PROJECT_ROOT
from .security import hash_password


BASE_DIR = PROJECT_ROOT


# ─────────────────────────────────────────────
# First-run seed accounts
# ─────────────────────────────────────────────
# (username, password, role, fullname, email, specialisation)
#
# These are inserted ONCE, when an empty database is first created. Redesign §7.2
# required them off the sign-in screen: the old login page printed all three, in
# plaintext, to every anonymous visitor. A demo convenience that ships as a published
# credential list is not a demo convenience, it is three unauthenticated accounts —
# one of them SuperAdmin.
#
# They are still discoverable, but only by whoever started the process: they are
# printed to the server console at the moment of creation, and the login page carries
# a caption saying so. Someone with the terminal already controls the machine; someone
# with the URL does not.
SEED_CREDENTIALS = [
    ("doctor",     "doctor123",     "Doctor",
     "Dr. John Smith",       "jsmith@heartguard.ai",   "Cardiologist"),
    ("admin",      "admin123",      "Admin",
     "Admin User",           "admin@heartguard.ai",    "System Admin"),
    ("superadmin", "superadmin123", "SuperAdmin",
     "Dr. Sarah Jenkins MD", "sjenkins@heartguard.ai", "Cardiologist"),
]


def connect():
    """
    Open a connection, configured for a threaded server.

    A NEW connection per call, never a shared one. SQLite connections belong to the
    thread that created them, and a production WSGI server handles requests on a pool
    of threads — a module-level connection would raise `ProgrammingError: SQLite
    objects created in a thread can only be used in that same thread` under any real
    concurrency.

    The four pragmas, and why each is here:

    foreign_keys    `predictions.user_id` declares ON DELETE CASCADE, but SQLite
                    ignores foreign keys unless this is set PER CONNECTION — without
                    it, deleting a user silently orphaned all of their predictions.

    journal_mode    WAL lets readers continue during a write. Under the default
                    rollback journal every write locks the entire database, so a
                    clinician saving an assessment blocks every other page load.
                    WAL is persistent: it is stored in the database file, so setting
                    it here applies once and stays.

    busy_timeout    Wait for a held lock instead of failing instantly. Python's
                    default is 5s; making it explicit means the value is visible
                    rather than inherited.

    synchronous     NORMAL is the documented safe pairing with WAL — durable across
                    application crashes, and only at risk from an OS-level power loss
                    mid-write, which is the trade every SQLite web application makes.

    WAL HAS A CONSEQUENCE FOR BACKUPS, HANDLED ELSEWHERE: recent commits live in the
    `-wal` sidecar file, so copying the `.db` alone can miss them. `backup_to()` below
    exists for that reason and is what the backup route uses.
    """
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def backup_to(destination: str) -> None:
    """
    Copy the database to `destination` using SQLite's own backup API.

    NOT `shutil.copy2`. In WAL mode the newest commits sit in the `-wal` sidecar until
    a checkpoint, so a file copy of the `.db` alone can silently produce a backup that
    is missing the most recent assessments — the exact records an operator taking a
    backup right now most wants to keep.

    The backup API takes a consistent snapshot across both files, holding a read lock
    for the duration, and works while the application is serving.
    """
    source = connect()
    target = sqlite3.connect(destination)
    try:
        with target:
            source.backup(target)
    finally:
        target.close()
        source.close()


def _announce_seed_credentials(creds):
    """
    Print the seeded accounts to stdout, once, at database creation.

    Written to the console rather than the log table on purpose: system_logs is
    readable through Activity Logs by any Admin, which would put the plaintext
    passwords back in the browser by a longer route.
    """
    # ASCII only. The Windows console defaults to cp1252, which cannot encode the box
    # rule or the em dash this used, so the announcement raised UnicodeEncodeError and
    # took `init_db()` down with it — turning "first run" into a crash on a machine
    # whose only fault was a non-UTF-8 console.
    line = "-" * 66
    print(f"\n{line}\n  HeartGuard AI - database created, seed accounts:\n")
    for username, password, role, *_ in creds:
        print(f"    {role:<11}  {username:<11}  {password}")
    print("\n  Change these before any deployment. They are printed once and\n"
          f"  are not shown in the application.\n{line}\n", flush=True)


def init_db():
    conn = connect()
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
            (u, hash_password(p), role, full, mail, spec)
            for u, p, role, full, mail, spec in SEED_CREDENTIALS
        ]
        c.executemany("""
            INSERT INTO users (username,password_hash,role,fullname,email,specialisation)
            VALUES (?,?,?,?,?,?)
        """, defaults)
        c.execute("""
            INSERT INTO system_logs (user_id,username,action,details)
            VALUES (1,'system','DB Initialised','Default accounts seeded successfully.')
        """)
        _announce_seed_credentials(SEED_CREDENTIALS)
    conn.commit()
    conn.close()
