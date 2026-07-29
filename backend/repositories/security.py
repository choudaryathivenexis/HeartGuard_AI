"""
Password hashing and verification.

PBKDF2-HMAC-SHA256 with a unique 16-byte salt and 200,000 iterations, stored as
`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`.

PBKDF2 rather than bcrypt or argon2 because it is in the Python standard library, so
the project still installs from requirements.txt alone. Legacy 64-character SHA-256
digests are still VERIFIED so nobody is locked out, and are transparently re-hashed to
PBKDF2 on the next successful sign-in.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


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
