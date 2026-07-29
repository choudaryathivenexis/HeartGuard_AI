"""
HeartGuard AI — entrypoint.

    python app.py                 DEVELOPMENT server on http://localhost:5000
    flask --app app run           the same, through the Flask CLI
    python wsgi.py                PRODUCTION server (waitress) on port 8000

Use wsgi.py for anything reachable by someone else. This file runs Werkzeug's
development server, which is single-process and not hardened against malformed or
slow requests.

The application itself is built by `backend.create_app()`. This file stays a launcher
so that the application object can also be imported by a WSGI server, or built against
a different configuration by the test suite, without executing a server as a side
effect of the import.
"""
from __future__ import annotations

import os

from backend import create_app

app = create_app()


if __name__ == "__main__":
    # DEBUG DEFAULTS TO OFF, and opting in is explicit.
    #
    # Werkzeug's debugger is an interactive Python console served to whoever triggers a
    # traceback. Defaulting it on means one unhandled exception on a reachable host
    # hands out remote code execution — on an application holding patient records. It
    # was previously on unless the environment said otherwise, which is the wrong way
    # round: the safe state should be what you get by forgetting to set anything.
    #
    # The reloader is tied to the same switch: it re-imports every module on each edit,
    # which reloads the estimators too — useful while developing, wasteful otherwise.
    debug = os.environ.get("HEARTGUARD_DEBUG", "0") == "1"
    if debug:
        print("  ! debug mode is ON - never expose this beyond localhost")
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", 5000)),
            debug=debug, use_reloader=debug)
