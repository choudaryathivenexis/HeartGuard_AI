"""
Cross-site request forgery protection.

WHY THIS EXISTS
Flask has no CSRF protection of its own. Without it, a page on another site can make a
signed-in administrator's browser issue any POST in this application — the browser
attaches the session cookie automatically, so the request arrives fully authenticated.
The damage available here is not theoretical: suspend a clinician, reassign a role,
clear every assessment, restore an old database over the live one.

The typed confirmations on the destructive actions are NOT a defence. An attacker
writes the form, so they can type "DELETE ALL" into it as easily as the administrator
can.

WHY NOT Flask-WTF
It is the usual answer and it is a good library, but it pulls in WTForms for a feature
that is one token and one comparison. This project's dependency list is short on
purpose — every entry is something a marker has to install successfully.

HOW IT WORKS
A random token is minted per session and stored in the session cookie, which is signed
with the app's secret key and therefore not writable by another origin. Every unsafe
request must echo that token back, in a form field or a header. Same-origin pages can
read it (the template renders it); cross-origin pages cannot.
"""
from __future__ import annotations

import hmac
import secrets

from flask import abort, request, session

__all__ = ["init_csrf", "current_token"]

_SESSION_KEY = "_csrf_token"
_FORM_FIELD = "csrf_token"
_HEADER = "X-CSRF-Token"

# GET/HEAD/OPTIONS/TRACE are defined as safe methods and must not change state, so they
# are not checked. Anything that mutates goes through the check.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def current_token() -> str:
    """The token for this session, minted on first use."""
    token = session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_SESSION_KEY] = token
    return token


def _submitted_token() -> str:
    return (request.form.get(_FORM_FIELD)
            or request.headers.get(_HEADER)
            or "")


def _explain_failure(app, expected: str, submitted: str) -> str:
    """
    Say WHY the check failed, when the reason is knowable.

    There is one misconfiguration that produces this failure on every single request and
    looks nothing like its cause: SESSION_COOKIE_SECURE set while the site is served
    over plain HTTP. The browser accepts the cookie and then refuses to send it back, so
    the server never sees a session, `expected` is always empty, and every sign-in
    returns 400. "Your session expired" is actively misleading there — the session was
    never received.

    It is worth naming because it is exactly what happens when the container image
    (which sets HEARTGUARD_HTTPS for its deployed use) is run locally over http.
    """
    if not expected and app.config.get("SESSION_COOKIE_SECURE") \
            and request.scheme != "https":
        return ("The session cookie is marked Secure, so the browser will not send it "
                "over plain HTTP and sign-in cannot complete. Serve this over HTTPS, "
                "or unset HEARTGUARD_HTTPS when running locally.")
    if not submitted:
        return ("The form was submitted without its security token. Reload the page "
                "and try again.")
    return ("Your session expired, or the form was not submitted from this "
            "application. Reload the page and try again.")


def init_csrf(app) -> None:
    """Register the check and expose `csrf_token()` to templates."""

    @app.before_request
    def _protect():
        if request.method in _SAFE_METHODS:
            return None
        expected = session.get(_SESSION_KEY)
        submitted = _submitted_token()
        # compare_digest, not `==`: a plain comparison returns early on the first
        # differing byte, which leaks the token a character at a time to anyone able to
        # time the response.
        if not expected or not submitted or not hmac.compare_digest(expected,
                                                                    submitted):
            abort(400, description=_explain_failure(app, expected, submitted))
        return None

    @app.context_processor
    def _inject():
        return {"csrf_token": current_token}
