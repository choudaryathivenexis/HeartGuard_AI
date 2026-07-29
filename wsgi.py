"""
Production entry point.

    python wsgi.py                  serve with waitress on 0.0.0.0:8000
    waitress-serve --port=8000 wsgi:application
    gunicorn -w 4 wsgi:application  (Linux)

WHY NOT `python app.py` IN PRODUCTION
`app.py` runs Flask's built-in server, which is Werkzeug's development server. It is
single-process, not hardened against malformed or slow requests, and Werkzeug prints a
warning saying so on every start. It is correct for development and wrong for anything
reachable by someone else.

Waitress is used rather than gunicorn because gunicorn does not run on Windows, and
this application is developed and marked on Windows. Waitress is pure Python, runs
everywhere, and needs no configuration file.

CONFIGURATION, ALL VIA ENVIRONMENT
    HEARTGUARD_SECRET_KEY   signing key; falls back to the one persisted in
                            system_settings.json, which is generated on first run
    HOST / PORT             bind address, default 0.0.0.0:8000
    THREADS                 worker threads, default 8
    HEARTGUARD_HTTPS        set to 1 when served behind TLS, so the session cookie
                            gets the Secure flag
"""
from __future__ import annotations

import os

from backend import create_app

application = create_app()
app = application  # some tooling looks for `app`


def _serve() -> None:
    from waitress import serve

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    threads = int(os.environ.get("THREADS", 8))

    print(f"  HeartGuard AI on http://{host}:{port}  ({threads} threads)")
    if not os.environ.get("HEARTGUARD_SECRET_KEY"):
        print("  ! HEARTGUARD_SECRET_KEY is not set - using the key persisted in\n"
              "    system_settings.json. Set it explicitly for a real deployment.")
    if os.environ.get("HEARTGUARD_HTTPS") != "1":
        print("  ! HEARTGUARD_HTTPS is not set - the session cookie will NOT carry\n"
              "    the Secure flag. Set it to 1 when serving behind TLS.")

    # ident is suppressed: the default advertises the server and version in every
    # response header, which is free reconnaissance.
    serve(application, host=host, port=port, threads=threads, ident=None)


if __name__ == "__main__":
    _serve()
