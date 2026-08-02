"""
Portable backup: every table out to a JSON document, and back in again.

WHY NOT THE SQLITE BACKUP API, WHICH IS WHAT THIS USED TO BE
The old flow called `sqlite3.Connection.backup()`, which is the correct way to copy a
SQLite file — in WAL mode the newest commits sit in the `-wal` sidecar, so a plain file
copy can miss exactly the records an operator taking a backup most wants. It is still
the right tool for copying a file, and it could not be the backup FEATURE:

  it produces a file on disk   The old flow wrote into `backups/`, listed the directory
                               and served files from it. A deployed host mounts the
                               application read-only, so "Create backup" was an OSError
                               there — the one button whose entire job is to protect
                               data was the one that did not work in the place data is
                               at risk.

  it is SQLite-only            There is no equivalent inside the process for Postgres.

So a backup is a download and a restore is an upload. Nothing touches the filesystem,
and the same file works whichever backend produced it — a SQLite installation can be
restored into Postgres, which is the migration path for anyone moving a populated local
database to a deployment.

THE FILE CONTAINS PASSWORD HASHES. They are PBKDF2, not plaintext, but the document is
still the whole user table and should be treated as sensitive. The session signing key
is the one thing deliberately left out — see `_REDACTED_SETTINGS`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .connection import IS_POSTGRES, connect, table_names

__all__ = ["export_document", "import_document", "FORMAT_VERSION"]

FORMAT_VERSION = 1

# Settings that must NOT leave the installation.
#
# `secret_key` signs the session cookies. A backup file containing it is a file that
# lets whoever holds it mint a valid session for any account, including SuperAdmin —
# and backups get emailed, copied to shared drives and attached to reports. Restoring
# a document without it simply leaves the running key in place, which is the behaviour
# you want anyway: a restore should not sign every current user out.
_REDACTED_SETTINGS = {"secret_key"}


def export_document() -> dict:
    """Every table, as a JSON-serialisable document."""
    conn = connect()
    try:
        c = conn.cursor()
        tables = {}
        for table in table_names():
            c.execute(f"SELECT * FROM {table} ORDER BY id" if table != "app_settings"
                      else "SELECT * FROM app_settings ORDER BY key")
            rows = [dict(row) for row in c.fetchall()]
            if table == "app_settings":
                rows = [r for r in rows if r.get("key") not in _REDACTED_SETTINGS]
            tables[table] = rows
        return {
            "format": "heartguard-backup",
            "version": FORMAT_VERSION,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "source": "postgres" if IS_POSTGRES else "sqlite",
            "tables": tables,
        }
    finally:
        conn.close()


def export_bytes() -> bytes:
    return json.dumps(export_document(), indent=1, default=str).encode("utf-8")


def summary() -> list[dict]:
    """Row count per table, so the backup page can say what a download would contain."""
    conn = connect()
    try:
        c = conn.cursor()
        out = []
        for table in table_names():
            c.execute(f"SELECT COUNT(*) FROM {table}")
            out.append({"table": table, "rows": c.fetchone()[0]})
        return out
    finally:
        conn.close()


def describe(document: dict) -> str:
    """A one-line summary of what a document holds, for the confirmation message."""
    tables = document.get("tables") or {}
    counts = ", ".join(f"{len(rows)} {name}" for name, rows in tables.items() if rows)
    return counts or "no rows"


def validate(document) -> str | None:
    """Return an error message if this is not a restorable document, else None."""
    if not isinstance(document, dict):
        return "That file is not a HeartGuard backup."
    if document.get("format") != "heartguard-backup":
        return "That file is not a HeartGuard backup."
    if document.get("version") != FORMAT_VERSION:
        return (f"That backup is format version {document.get('version')!r}; "
                f"this application reads version {FORMAT_VERSION}.")
    tables = document.get("tables")
    if not isinstance(tables, dict):
        return "The backup contains no tables."
    unknown = set(tables) - set(table_names())
    if unknown:
        return f"The backup contains unknown tables: {', '.join(sorted(unknown))}."
    if not tables.get("users"):
        # A restore that empties the user table locks the institution out of its own
        # application with no way back in through the interface.
        return "The backup contains no user accounts and would lock you out."
    return None


def import_document(document: dict) -> dict:
    """
    Replace the contents of every table with the document's.

    ONE TRANSACTION. A restore that fails half way would otherwise leave the database
    holding some tables from the backup and some from before it — predictions
    referencing users that no longer exist, which is worse than either state alone.

    Rows are deleted in reverse dependency order and inserted in forward order, so
    foreign keys hold at every point without disabling them.
    """
    tables = document["tables"]
    conn = connect()
    counts: dict[str, int] = {}
    try:
        c = conn.cursor()

        for table in reversed(table_names()):
            c.execute(f"DELETE FROM {table}")

        for table in table_names():
            rows = tables.get(table) or []
            counts[table] = len(rows)
            if not rows:
                continue
            columns = list(rows[0].keys())
            placeholders = ",".join("?" for _ in columns)
            sql = (f"INSERT INTO {table} ({','.join(columns)}) "
                   f"VALUES ({placeholders})")
            c.executemany(sql, [tuple(row.get(col) for col in columns)
                                for row in rows])

        if IS_POSTGRES:
            # Reset the identity sequences.
            #
            # The rows carry their original ids, which Postgres accepts without
            # advancing the sequence behind a SERIAL column. Leave it and the sequence
            # still points at 1, so the NEXT insert collides with a restored row and
            # raises a duplicate key error — a restore that appears to succeed and then
            # breaks the first attempt to save anything. SQLite advances sqlite_sequence
            # on an explicit id, so it needs none of this.
            for table in table_names():
                if table == "app_settings":
                    continue          # keyed by text, no sequence
                c.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1))")

        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
