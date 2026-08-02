"""
Vercel entry point.

Vercel's Python runtime imports this file and serves the WSGI callable named `app`.
There is no server to start: the platform is the server, and each request arrives as an
invocation of this module's application object.

WHAT THIS FILE HAS TO DO BEFORE IMPORTING THE APPLICATION, and why each matters on a
serverless host and nowhere else:

  sys.path      The function's working directory is not guaranteed to be the project
                root, so `import backend` is not guaranteed to resolve. Inserting the
                repository root makes it deterministic.

  MPLCONFIGDIR  matplotlib writes a font cache on first import. On a read-only
                deployment its default location cannot be created, so it falls back to
                a temporary directory AND prints a warning on every cold start; worse,
                the font cache is then rebuilt each time, which is seconds of CPU on a
                request somebody is waiting for. /tmp is the one writable path.

                Set BEFORE `backend` is imported. matplotlib reads this at import time
                and never again — setting it afterwards is a no-op that looks correct.

  DATABASE_URL  Not set here. It is configured in the Vercel dashboard, along with
                HEARTGUARD_SECRET_KEY. Without DATABASE_URL the application falls back
                to SQLite, which on this host means a database inside a read-only
                bundle: it would fail on the first write, which is the sign-in audit
                entry. See README for the required variables.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

# Behind Vercel's proxy, over HTTPS. Defaults rather than assignments so that a value
# set in the dashboard still wins.
os.environ.setdefault("HEARTGUARD_TRUST_PROXY", "1")
os.environ.setdefault("HEARTGUARD_HTTPS", "1")

from backend import create_app  # noqa: E402  (must follow the environment set-up)

app = create_app()
