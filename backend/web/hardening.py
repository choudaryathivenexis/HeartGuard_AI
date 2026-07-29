"""
Response security headers and login rate limiting.

Both defend against attacks the application is otherwise open to, and neither needs a
dependency.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from flask import request

__all__ = ["init_hardening", "record_failure", "is_locked_out", "clear_failures"]


# ════════════════════════════════════════════════════════════════════════
# Response headers
# ════════════════════════════════════════════════════════════════════════
# Content-Security-Policy is the significant one. This application renders its own
# HTML with no third-party scripts, so the policy can be strict: no scripts at all,
# styles from this origin plus Google Fonts (the only external resource), images from
# this origin and data: URIs (the icons are inline SVG data URIs).
#
# `style-src 'unsafe-inline'` is present and is a real, small concession: the templates
# use inline `style=` attributes for a handful of one-off values such as rail band
# widths, which are computed per patient and cannot live in a static stylesheet. It
# does not permit scripts.
_CSP = ("default-src 'self'; "
        "script-src 'none'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'")

_HEADERS = {
    # Clickjacking. Without this, an attacker frames the admin pages invisibly and
    # tricks a signed-in SuperAdmin into clicking "Suspend" or "Delete".
    "X-Frame-Options": "DENY",
    # Stops a browser second-guessing a declared Content-Type, which is how a text
    # upload gets executed as script.
    "X-Content-Type-Options": "nosniff",
    # Do not leak the URL of an internal page (which carries patient ids) to any
    # external site a user navigates to.
    "Referrer-Policy": "no-referrer",
    # This application needs none of these.
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Content-Security-Policy": _CSP,
}


# ════════════════════════════════════════════════════════════════════════
# Login rate limiting
# ════════════════════════════════════════════════════════════════════════
# WHY IN MEMORY: this is a single-process deployment against a SQLite database. A
# shared store would be the right answer behind several workers, and would need Redis —
# a dependency this project does not otherwise carry. The limit is per (ip, username),
# so one attacker cannot lock out a real clinician by guessing at their account from
# elsewhere; the pair has to match.
_MAX_FAILURES = 8
_WINDOW_SECONDS = 300      # failures older than this are forgotten
_LOCKOUT_SECONDS = 300     # how long a tripped limit holds

_failures: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = Lock()


def _key(username: str, client_ip: str | None = None) -> tuple[str, str]:
    """
    The identity being rate-limited.

    `client_ip` is a PARAMETER, defaulting to the current request's address rather
    than reading it unconditionally. Reading `request.remote_addr` inside made these
    functions unusable outside a request context — including from a test, which is how
    this was found. Everything else in the backend takes its inputs explicitly for the
    same reason.
    """
    if client_ip is None:
        client_ip = (request.remote_addr or "unknown") if request else "unknown"
    return (client_ip, (username or "").lower())


def _prune(stamps: deque, now: float) -> None:
    while stamps and now - stamps[0] > _WINDOW_SECONDS:
        stamps.popleft()


def record_failure(username: str, client_ip: str | None = None) -> None:
    now = time.time()
    with _lock:
        stamps = _failures[_key(username, client_ip)]
        _prune(stamps, now)
        stamps.append(now)


def clear_failures(username: str, client_ip: str | None = None) -> None:
    """Called on a successful sign-in — a correct password resets the count."""
    with _lock:
        _failures.pop(_key(username, client_ip), None)


def is_locked_out(username: str, client_ip: str | None = None) -> int:
    """Seconds remaining on a lockout, or 0 if the account may attempt a sign-in."""
    now = time.time()
    with _lock:
        stamps = _failures.get(_key(username, client_ip))
        if not stamps:
            return 0
        _prune(stamps, now)
        if len(stamps) < _MAX_FAILURES:
            return 0
        remaining = _LOCKOUT_SECONDS - (now - stamps[-1])
        return max(0, int(remaining))


def init_hardening(app) -> None:
    import os

    @app.after_request
    def _headers(response):
        for header, value in _HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    # ── trust the proxy's forwarded headers, when there IS a trusted proxy ────
    #
    # THIS IS NOT COSMETIC. Behind a reverse proxy — Hugging Face Spaces, Render, nginx
    # — `request.remote_addr` is the PROXY's address, the same value for every visitor
    # on earth. The rate limiter keys on (ip, username), so with a constant ip an
    # attacker guessing at `admin` accumulates failures against the same bucket the
    # real administrator hashes to, and locks them out. The limiter stops being a
    # brute-force defence and becomes a denial-of-service tool aimed at real accounts —
    # the exact collateral lockout the per-pair key was chosen to avoid.
    #
    # OPT-IN, because trusting these headers without a proxy in front is worse than not
    # trusting them: any client can send its own X-Forwarded-For and pick a fresh
    # identity for every attempt, which evades the limiter completely. Only set
    # HEARTGUARD_TRUST_PROXY where something you control terminates the connection.
    if os.environ.get("HEARTGUARD_TRUST_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        # x_for=1 / x_proto=1: trust exactly one hop. A larger number lets a client
        # prepend entries to the header and impersonate an arbitrary address.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # The Secure flag requires TLS. Setting it on a plain-HTTP host means the browser
    # never returns the cookie, so the CSRF check finds no session token and every
    # sign-in fails with 400 — see the diagnostic in backend/web/csrf.py, which exists
    # because that failure is otherwise indistinguishable from an expired form.
    if os.environ.get("HEARTGUARD_HTTPS") == "1":
        app.config["SESSION_COOKIE_SECURE"] = True
