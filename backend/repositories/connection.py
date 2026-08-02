"""
Database connection and schema creation, for SQLite and for Postgres.

Every other repository module opens its connection through `connect()` here, so the
choice of backend is made in exactly one place — and the SQLite path resolves from
backend.config rather than from `__file__`. Deriving it from the module's own location
is what once made this package create an empty database beside itself after being moved.

WHICH BACKEND, AND WHY THERE ARE TWO
Set DATABASE_URL and the application talks to Postgres; leave it unset and it uses the
SQLite file. That is not a preference toggle, it is what makes the same code run in two
places that genuinely differ: a laptop, where a file is the simplest correct answer, and
a serverless host, where the filesystem is read-only and each instance would otherwise
hold a private copy of the data. `dialect.py` carries the translation.

CONNECTION LIFETIME
A NEW connection per call, never a shared one. SQLite connections belong to the thread
that created them, and a production WSGI server handles requests on a pool of threads —
a module-level connection would raise `ProgrammingError: SQLite objects created in a
thread can only be used in that same thread` under any real concurrency.

On Postgres "new connection per call" would mean a TCP and TLS handshake for every
repository function, and a single page calls several — against a hosted database that
is tenths of a second of latency per page view, spent doing nothing. So the Postgres
path hands out POOLED connections: same per-call API, same `close()` at the end, but
close() returns the connection to the pool instead of dropping it.
"""

from __future__ import annotations

import sqlite3
from threading import Lock

from backend.config import DB_PATH, PROJECT_ROOT

from .dialect import (DATABASE_URL, IS_POSTGRES, NOW_SQL, Row, pg_row_factory,
                      sqlite_row_factory, to_postgres)
from .security import hash_password

BASE_DIR = PROJECT_ROOT

__all__ = ["BASE_DIR", "SEED_CREDENTIALS", "connect", "init_db",
           "insert_returning_id", "IntegrityError", "OperationalError",
           "IS_POSTGRES", "Row", "table_names"]


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


# ════════════════════════════════════════════════════════════════════════
# Driver exceptions
# ════════════════════════════════════════════════════════════════════════
# Exposed as TUPLES covering whichever drivers are present, so a repository module can
# write `except IntegrityError:` once and have it mean the same thing on both backends.
# Catching `sqlite3.IntegrityError` directly — which is what this code used to do —
# silently stops catching anything the moment Postgres is in use, and the duplicate
# username that used to return "taken" becomes a 500.
def _driver_exceptions():
    integrity = [sqlite3.IntegrityError]
    operational = [sqlite3.OperationalError]
    if IS_POSTGRES:
        import psycopg
        integrity.append(psycopg.IntegrityError)
        operational.append(psycopg.OperationalError)
    return tuple(integrity), tuple(operational)


IntegrityError, OperationalError = _driver_exceptions()


# ════════════════════════════════════════════════════════════════════════
# Postgres connection wrapper
# ════════════════════════════════════════════════════════════════════════
class _PgCursor:
    """A psycopg cursor that accepts SQLite's `?` placeholders."""

    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        # params or None: psycopg only performs `%` interpolation when parameters are
        # supplied, and `to_postgres` escapes `%` on the same condition. The two must
        # agree or a literal percent sign breaks one of the two cases.
        self._cur.execute(to_postgres(sql, bool(params)), params or None)
        return self

    def executemany(self, sql, seq_of_params):
        rows = list(seq_of_params)
        if rows:
            self._cur.executemany(to_postgres(sql, True), rows)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()


class _PgConnection:
    """
    A psycopg connection presenting the small slice of the sqlite3 API this code uses.

    `close()` returns the connection to the pool rather than closing it — the callers
    are written as open/use/close and must not need to know the difference.
    """

    __slots__ = ("_raw", "_pool", "_closed")

    def __init__(self, raw, pool=None):
        self._raw = raw
        self._pool = pool
        self._closed = False

    def cursor(self):
        return _PgCursor(self._raw.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._pool is None:
            self._raw.close()
            return
        # Roll back BEFORE returning the connection.
        #
        # psycopg opens a transaction on the first statement, including a plain SELECT,
        # so every read-only repository function returns its connection with one still
        # open. The pool copes — it rolls back for us — but it logs "rolling back
        # returned connection" at WARNING each time, which on a busy page is several
        # lines of alarming log output describing nothing wrong.
        #
        # Doing it here also matches SQLite exactly: sqlite3 discards an uncommitted
        # transaction on close, so a caller that wrote without committing loses the
        # write on both backends rather than on one.
        try:
            self._raw.rollback()
        except Exception:
            # A connection broken mid-request cannot be rolled back and must not be
            # handed to the next caller. Drop it; the pool opens a replacement.
            try:
                self._raw.close()
            finally:
                self._pool.putconn(self._raw)
            return
        self._pool.putconn(self._raw)


_pool = None
_pool_lock = Lock()

# Small on purpose. Every repository call takes a connection for the length of one
# query, so throughput needs far fewer connections than requests — and hosted Postgres
# free tiers cap simultaneous connections tightly enough that a generous pool is how a
# deployment starts refusing connections under no real load.
_POOL_MAX = 5


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                from psycopg_pool import ConnectionPool
                _pool = ConnectionPool(
                    DATABASE_URL,
                    min_size=0,
                    max_size=_POOL_MAX,
                    kwargs={"row_factory": pg_row_factory},
                    # Hosted Postgres suspends an idle database and drops its
                    # connections. Without this check the pool hands out a corpse and
                    # the first query after a quiet period fails — which on a
                    # demonstration URL is precisely when somebody is looking.
                    check=ConnectionPool.check_connection,
                    open=True,
                )
                # Close the pool while the interpreter is still alive.
                #
                # ConnectionPool runs worker threads and joins them from __del__. At
                # interpreter shutdown that join is illegal and raises
                # PythonFinalizationError, printed as an "Exception ignored in"
                # traceback after the process has finished its work — output that looks
                # like a crash and is not one. atexit runs early enough for the join to
                # be legal.
                import atexit
                atexit.register(_close_pool)
    return _pool


def _close_pool() -> None:
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass


def connect():
    """
    Open a connection to whichever backend is configured.

    THE FOUR SQLITE PRAGMAS, and why each is here:

    foreign_keys    `predictions.user_id` declares ON DELETE CASCADE, but SQLite
                    ignores foreign keys unless this is set PER CONNECTION — without
                    it, deleting a user silently orphaned all of their predictions.
                    Postgres enforces them without being asked.

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
    exists for that reason.
    """
    if IS_POSTGRES:
        try:
            pool = _get_pool()
            return _PgConnection(pool.getconn(), pool)
        except ImportError:
            # psycopg_pool is a convenience, not a requirement. Without it the
            # application still works, one handshake at a time.
            import psycopg
            return _PgConnection(
                psycopg.connect(DATABASE_URL, row_factory=pg_row_factory))

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite_row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def insert_returning_id(cursor, sql, params=()):
    """
    Run an INSERT and return the new row's id, on either backend.

    `cursor.lastrowid` is SQLite's and is always None on psycopg, so the three call
    sites that used it would have stored a null id on Postgres — and stored it
    SILENTLY, because nothing downstream checks. Postgres gets `RETURNING id` instead.
    """
    if IS_POSTGRES:
        cursor.execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
        row = cursor.fetchone()
        return row[0] if row else None
    cursor.execute(sql, params)
    return cursor.lastrowid


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


# ════════════════════════════════════════════════════════════════════════
# Schema
# ════════════════════════════════════════════════════════════════════════
# Two dialects, written out rather than generated. A type-mapping layer would be
# shorter and would hide exactly the details that matter here — which column is TEXT
# and not TIMESTAMP, which default produces SQLite's timestamp format — so the DDL is
# stated once per backend where it can be read.
#
# TIMESTAMPS ARE TEXT ON BOTH. See dialect.py: Postgres would otherwise return datetime
# objects, and `services/analytics.py` slices the value as a string.

_SQLITE_TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        fullname TEXT,
        email TEXT,
        specialisation TEXT DEFAULT '',
        is_banned INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

    """CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        age REAL, gender INTEGER, height REAL, weight REAL,
        ap_hi REAL, ap_lo REAL, cholesterol INTEGER, gluc INTEGER,
        smoke INTEGER, alco INTEGER, active INTEGER,
        predicted_class INTEGER, probability REAL, model_used TEXT,
        patient_name TEXT DEFAULT '', notes TEXT DEFAULT '',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",

    # ─────────────────────────────────────────────
    # Patients  (Run 7)
    # ─────────────────────────────────────────────
    # Before this table existed, `predictions` conflated an EVENT with a PERSON: the
    # only patient identity was a free-text name on each row, so the same patient
    # assessed twice produced two unrelated records. Cardiovascular risk management is
    # inherently longitudinal — you track a trajectory, not a snapshot — so a first
    # class patient entity is a prerequisite, not a nicety.
    """CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_code TEXT UNIQUE NOT NULL,
        fullname TEXT NOT NULL,
        gender INTEGER,
        notes TEXT DEFAULT '',
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        )""",

    """CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, action TEXT NOT NULL,
        details TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

    """CREATE TABLE IF NOT EXISTS training_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        triggered_by INTEGER, status TEXT DEFAULT 'running',
        duration_s REAL, results_json TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

    # Operator-editable configuration. Held in the database rather than a JSON file
    # beside the code so that it survives on a host with a read-only filesystem, and
    # so that every instance of the application reads the same value.
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
        )""",
]

_POSTGRES_TABLES = [
    f"""CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        fullname TEXT,
        email TEXT,
        specialisation TEXT DEFAULT '',
        is_banned INTEGER DEFAULT 0,
        created_at TEXT DEFAULT {NOW_SQL}
        )""",

    # The Run-7 columns are declared inline here. On SQLite they arrive through the
    # additive migration below, because SQLite databases exist that predate them; a
    # Postgres database can only ever be created by this file, so there is no older
    # shape to migrate from and pretending otherwise would be theatre.
    f"""CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        age DOUBLE PRECISION, gender INTEGER,
        height DOUBLE PRECISION, weight DOUBLE PRECISION,
        ap_hi DOUBLE PRECISION, ap_lo DOUBLE PRECISION,
        cholesterol INTEGER, gluc INTEGER,
        smoke INTEGER, alco INTEGER, active INTEGER,
        predicted_class INTEGER, probability DOUBLE PRECISION, model_used TEXT,
        patient_name TEXT DEFAULT '', notes TEXT DEFAULT '',
        timestamp TEXT DEFAULT {NOW_SQL},
        patient_ref INTEGER,
        model_version TEXT DEFAULT '',
        model_manifest_sha TEXT DEFAULT '',
        threshold_used DOUBLE PRECISION,
        risk_band TEXT DEFAULT '',
        outcome INTEGER,
        outcome_notes TEXT DEFAULT '',
        outcome_by TEXT DEFAULT '',
        outcome_at TEXT,
        extrapolated INTEGER DEFAULT 0,
        applicability_notes TEXT DEFAULT ''
        )""",

    f"""CREATE TABLE IF NOT EXISTS patients (
        id SERIAL PRIMARY KEY,
        patient_code TEXT UNIQUE NOT NULL,
        fullname TEXT NOT NULL,
        gender INTEGER,
        notes TEXT DEFAULT '',
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT DEFAULT {NOW_SQL}
        )""",

    f"""CREATE TABLE IF NOT EXISTS system_logs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, username TEXT, action TEXT NOT NULL,
        details TEXT, timestamp TEXT DEFAULT {NOW_SQL}
        )""",

    f"""CREATE TABLE IF NOT EXISTS training_runs (
        id SERIAL PRIMARY KEY,
        triggered_by INTEGER, status TEXT DEFAULT 'running',
        duration_s DOUBLE PRECISION, results_json TEXT,
        timestamp TEXT DEFAULT {NOW_SQL}
        )""",

    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
        )""",
]

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
#   extrapolated /
#   applicability_notes  BUG-23: was this patient outside the model's training
#                        envelope? An extrapolated score must be identifiable forever
#                        after, not just flagged on screen once.
_PREDICTION_COLUMNS = [
    ("patient_ref",         "INTEGER",          "INTEGER"),
    ("model_version",       "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
    ("model_manifest_sha",  "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
    ("threshold_used",      "REAL",             "DOUBLE PRECISION"),
    ("risk_band",           "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
    ("outcome",             "INTEGER",          "INTEGER"),
    ("outcome_notes",       "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
    ("outcome_by",          "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
    ("outcome_at",          "TIMESTAMP",        "TEXT"),
    ("extrapolated",        "INTEGER DEFAULT 0", "INTEGER DEFAULT 0"),
    ("applicability_notes", "TEXT DEFAULT ''",  "TEXT DEFAULT ''"),
]

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_pred_patient ON predictions(patient_ref)",
    "CREATE INDEX IF NOT EXISTS idx_pred_outcome ON predictions(outcome)",
    "CREATE INDEX IF NOT EXISTS idx_pred_user ON predictions(user_id)",
]


def table_names() -> list[str]:
    """Every table this schema creates, in dependency order. Used by the exporter."""
    return ["users", "patients", "predictions", "system_logs", "training_runs",
            "app_settings"]


def init_db():
    conn = connect()
    c = conn.cursor()

    for statement in (_POSTGRES_TABLES if IS_POSTGRES else _SQLITE_TABLES):
        c.execute(statement)

    if IS_POSTGRES:
        # ADD COLUMN IF NOT EXISTS is a single statement on Postgres and needs no
        # inspection of the current shape.
        for column, _sqlite_ddl, pg_ddl in _PREDICTION_COLUMNS:
            c.execute(
                f"ALTER TABLE predictions ADD COLUMN IF NOT EXISTS {column} {pg_ddl}")
    else:
        existing = {row[1] for row in c.execute("PRAGMA table_info(predictions)")}
        for column, sqlite_ddl, _pg_ddl in _PREDICTION_COLUMNS:
            if column not in existing:
                c.execute(f"ALTER TABLE predictions ADD COLUMN {column} {sqlite_ddl}")

    for statement in _INDEXES:
        c.execute(statement)

    if not IS_POSTGRES:
        # Repair outcomes stored as words.
        #
        # `predictions.outcome` is INTEGER and every consumer compares it against 1.
        # The outcome form used to send its own vocabulary — "confirmed", "ruled_out",
        # "unknown" — straight into the column. SQLite stores a string it cannot
        # losslessly convert, so those rows were collected and then silently excluded
        # from the deployed-performance statistics they exist to feed.
        #
        # Postgres cannot hold such a row, so this is SQLite's alone. Written with
        # explicit values rather than a mapping table because it runs once and then
        # matches nothing.
        c.execute("UPDATE predictions SET outcome = 1 WHERE outcome = 'confirmed'")
        c.execute("UPDATE predictions SET outcome = 0 WHERE outcome = 'ruled_out'")
        c.execute("UPDATE predictions SET outcome = NULL WHERE outcome = 'unknown'")
        # Anything else that is neither 0, 1 nor NULL is not an outcome this
        # application ever meant to store, and leaving it in place would keep the
        # statistics broken for a value nobody can explain.
        c.execute("UPDATE predictions SET outcome = NULL "
                  "WHERE outcome IS NOT NULL AND outcome NOT IN (0, 1)")

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

    # Carry an existing installation's settings across, once.
    #
    # Settings used to live in system_settings.json. Upgrading without this would
    # silently reset every operator preference AND generate a new session key, signing
    # everyone out for a reason nothing on screen explains. Cheap: one COUNT that stops
    # immediately on every run after the first.
    #
    # Imported locally because settings.py imports this module for `connect`.
    from backend.config import SETTINGS_PATH
    from .settings import import_legacy_file
    import_legacy_file(SETTINGS_PATH)
