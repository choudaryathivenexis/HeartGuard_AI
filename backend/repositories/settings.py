"""
Operator-editable configuration, stored in the database.

WHY NOT A JSON FILE, WHICH IS WHAT THIS USED TO BE
`system_settings.json` sat beside the code and was written in place. That works on one
machine with a writable disk and fails in both of the ways a deployment actually fails:

  read-only filesystem   A serverless host mounts the application read-only. Writing
                         raised OSError, and the write on the path that MATTERS is
                         `secret_key()` during start-up — so the failure was not "an
                         admin could not save a setting", it was "the application does
                         not start".

  more than one instance  Two instances each hold their own file. An administrator
                         turns registration off, the next request lands on the other
                         instance, and it is on again. The same applies to the session
                         key: two keys means each instance rejects the other's cookies
                         and users are signed out at random.

Values are JSON-encoded, so a bool stays a bool and a float stays a float. The previous
file was JSON for the same reason, and the settings page relies on it — `risk_threshold`
is a float that must not come back as the string "0.42".
"""
from __future__ import annotations

import json

from .connection import connect

__all__ = ["get_setting", "set_setting", "get_all_settings", "import_legacy_file"]


def _decode(raw):
    """A stored value, or the raw text if it predates JSON encoding."""
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def get_all_settings() -> dict:
    conn = connect()
    try:
        c = conn.cursor()
        c.execute("SELECT key, value FROM app_settings")
        return {row["key"]: _decode(row["value"]) for row in c.fetchall()}
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = connect()
    try:
        c = conn.cursor()
        c.execute("SELECT value FROM app_settings WHERE key=?", (key,))
        row = c.fetchone()
        return _decode(row["value"]) if row is not None else default
    finally:
        conn.close()


def set_setting(key: str, value) -> None:
    """
    Store one setting.

    ON CONFLICT ... DO UPDATE is one statement on both backends — SQLite has supported
    it since 3.24 and Postgres since 9.5 — so there is no read-then-write race where
    two administrators saving at once lose one of the two changes.
    """
    conn = connect()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, json.dumps(value)))
        conn.commit()
    finally:
        conn.close()


def import_legacy_file(path: str) -> int:
    """
    One-time import of a pre-existing system_settings.json.

    Without this, upgrading an installation silently resets its settings AND generates
    a new session key, signing every user out for no reason they can see. Returns the
    number of keys imported; does nothing if the table already holds anything.
    """
    conn = connect()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM app_settings")
        if c.fetchone()[0]:
            return 0
    finally:
        conn.close()

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0

    for key, value in data.items():
        set_setting(key, value)
    return len(data)
