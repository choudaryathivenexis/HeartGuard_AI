"""
User accounts: authentication, registration, profile and role administration.

Every function that CHANGES an account records the operator in the audit log. An
administrative action nobody can attribute is an administrative action nobody can
review.
"""

from __future__ import annotations

import sqlite3

from .audit import log_activity
from .connection import connect
from .security import hash_password, verify_password, _is_legacy_hash


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────
def validate_login(username, password):
    conn = connect()
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
    conn = connect()
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
# Users CRUD
# ─────────────────────────────────────────────
def get_all_users():
    conn = connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id,username,role,fullname,email,specialisation,is_banned,created_at FROM users ORDER BY id")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_user_by_id(user_id):
    """
    Current database state for a user id, or None if the account no longer exists.

    Needed for session revalidation (BUG-25): st.session_state.user is a plain dict
    captured at login, so a user deleted, banned or re-roled afterwards continued with
    their original privileges until they chose to log out.
    """
    conn = connect()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_profile(user_id, fullname, email, specialisation, new_password=None):
    conn = connect()
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
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
    conn.commit()
    log_activity(None, operator_username, "Role Change", f"User {uname} role changed to {new_role}.")
    conn.close()


def ban_user(user_id, operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET is_banned=1 WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Ban User", f"User {uname} has been banned.")
    conn.close()


def unban_user(user_id, operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("UPDATE users SET is_banned=0 WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Unban User", f"User {uname} has been unbanned.")
    conn.close()


def delete_user(user_id, operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    log_activity(None, operator_username, "Delete User", f"Account '{uname}' permanently deleted.")
    conn.close()
