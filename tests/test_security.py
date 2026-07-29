"""
Security and write-path tests.

`test_routes.py` covers what each role may SEE. This covers what each role may DO —
which is where the damage is. A GET that renders the wrong page is a bug; a POST that
deletes another clinician's patient is an incident.

Runnable standalone: `python tests/test_security.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app
from backend import repositories as db

FAILURES: list[str] = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


app = create_app({"TESTING": True})


def csrf(client) -> str:
    """
    The CSRF token for this client's session, read from the session itself.

    NOT scraped from a page. Scraping /login only works while signed OUT — once
    authenticated that route redirects, so the scrape found nothing, sent an empty
    token, and every authenticated POST came back 400. Reading the session works for
    every role and every page.

    `login()` clears the session, so the token changes at sign-in; this is called fresh
    per request rather than cached.
    """
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = "test-csrf-token-value"
            sess["_csrf_token"] = token
    return token


def post(client, path, data=None, **kw):
    """POST with the session's CSRF token attached."""
    payload = dict(data or {})
    payload.setdefault("csrf_token", csrf(client))
    return client.post(path, data=payload, **kw)

SEEDS = {"admin": "admin123", "superadmin": "superadmin123", "doctor": "doctor123"}
TEMP = {"doctor_a": ("_sec_doc_a", "sec-test-pw-4471"),
        "doctor_b": ("_sec_doc_b", "sec-test-pw-4472")}
_created = []


def ensure(username, password, role="Doctor"):
    existing = next((u for u in db.get_all_users() if u["username"] == username), None)
    if existing:
        return existing
    uid, err = db.register_user(username, password, role, f"Test {username}",
                                f"{username}@heartguard.local", "")
    if uid is None:
        print(f"  [warn] could not create {username}: {err}")
        return None
    _created.append(uid)
    return db.get_user_by_id(uid)


def sign_in(client, username, password):
    return post(client, "/login",
                {"username": username, "password": password},
                follow_redirects=True)


def account_for(role):
    for user in db.get_all_users():
        if user["role"] == role and user["username"] in SEEDS:
            return user["username"], SEEDS[user["username"]]
    return None


doc_a = ensure(*TEMP["doctor_a"])
doc_b = ensure(*TEMP["doctor_b"])


# ════════════════════════════════════════════════════════════════════════
print("=== 1. write endpoints reject the wrong role ===")
# Every one of these POSTs mutates something. A redirect (302) means the guard fired;
# a 200 means the action ran, which for these paths would be a privilege escalation.
WRITE_PATHS = [
    ("/system/settings", {"allow_registration": "on"}, "SuperAdmin"),
    ("/system/models", {"model_0": "on"}, "SuperAdmin"),
    ("/system/logs/clear", {"confirm": "CLEAR LOGS"}, "SuperAdmin"),
    ("/system/backup/create", {}, "SuperAdmin"),
    ("/admin/roles", {"user_id": "1", "role": "Doctor"}, "SuperAdmin"),
    ("/admin/predictions/clear", {"confirm": "nope"}, "SuperAdmin"),
]
for path, payload, owner_role in WRITE_PATHS:
    for role in ("Doctor", "Admin"):
        if role == owner_role:
            continue
        account = TEMP["doctor_a"] if role == "Doctor" else account_for(role)
        if not account:
            continue
        with app.test_client() as c:
            sign_in(c, *account)
            r = post(c, path, data=payload, follow_redirects=False)
            check(f"{role} POST {path} is refused",
                  r.status_code in (301, 302), f"got {r.status_code}")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 2. a doctor cannot read another doctor's assessment ===")
if doc_a and doc_b:
    # Give doctor A one assessment to own.
    from backend.services import screening as screening_service
    result = screening_service.run_assessment(
        doc_a,
        {"patient_code": "PT-SEC-A", "patient_name": "Sec Patient A",
         "age": 52, "gender": 2, "height": 170, "weight": 82.0, "ap_hi": 138,
         "ap_lo": 88, "cholesterol": 2, "gluc": 1, "smoke": 0, "alco": 0,
         "active": 1},
        model_choice="Ensemble Voting", with_explanation=False)
    check("doctor A's assessment was created", not result.get("refused"),
          str(result.get("errors")))

    owned = db.get_predictions(user_id=doc_a["id"])
    if owned:
        pred_id = owned[0]["id"]
        with app.test_client() as c:
            sign_in(c, *TEMP["doctor_b"])
            r = c.get(f"/screening/report/{pred_id}.txt", follow_redirects=False)
            check("doctor B is refused doctor A's text report",
                  r.status_code in (301, 302), f"got {r.status_code}")
            r = c.get(f"/screening/report/{pred_id}.pdf", follow_redirects=False)
            check("doctor B is refused doctor A's PDF",
                  r.status_code in (301, 302), f"got {r.status_code}")
            r = post(c, f"/screening/history/{pred_id}/delete", follow_redirects=True)
            check("doctor B cannot delete doctor A's assessment",
                  any(p["id"] == pred_id for p in db.get_predictions()),
                  "the row was deleted by a clinician who does not own it")
        with app.test_client() as c:
            sign_in(c, *TEMP["doctor_a"])
            r = c.get(f"/screening/report/{pred_id}.txt")
            check("doctor A CAN read their own report", r.status_code == 200,
                  str(r.status_code))


# ════════════════════════════════════════════════════════════════════════
print("\n=== 3. destructive actions need their typed confirmation ===")
admin = account_for("SuperAdmin")
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        before = len(db.get_predictions())
        r = post(c, "/admin/predictions/clear", data={"confirm": "wrong"},
                   follow_redirects=True)
        check("clearing all assessments refuses a wrong confirmation",
              len(db.get_predictions()) == before,
              "records were destroyed without the confirmation phrase")
        logs_before = len(db.get_system_logs(limit=500))
        r = post(c, "/system/logs/clear", data={"confirm": "wrong"},
                   follow_redirects=True)
        check("clearing the audit log refuses a wrong confirmation",
              len(db.get_system_logs(limit=500)) >= logs_before,
              "the audit trail was cleared without confirmation")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 4. an admin cannot act on an equal or higher rank ===")
if admin:
    superadmins = [u for u in db.get_all_users() if u["role"] == "SuperAdmin"]
    admin_account = account_for("Admin")
    if admin_account and superadmins:
        target = superadmins[0]
        with app.test_client() as c:
            sign_in(c, *admin_account)
            post(c, f"/admin/users/{target['id']}/ban", follow_redirects=True)
            still = db.get_user_by_id(target["id"])
            check("an Admin cannot suspend a SuperAdmin",
                  still and not still.get("is_banned"),
                  "a lower rank suspended a higher one")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 5. self-administration is blocked ===")
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        me = next(u for u in db.get_all_users() if u["username"] == admin[0])
        post(c, f"/admin/users/{me['id']}/ban", follow_redirects=True)
        still = db.get_user_by_id(me["id"])
        check("an administrator cannot suspend their own account",
              still and not still.get("is_banned"),
              "locked the institution out of its own administration")
        r = post(c, "/admin/roles", data={"user_id": str(me["id"]), "role": "Doctor"},
                   follow_redirects=True)
        check("an administrator cannot demote themselves",
              db.get_user_by_id(me["id"])["role"] == "SuperAdmin",
              "self-demotion succeeded")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 6. path traversal on the backup download ===")
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        for attempt in ("../heartguard.db", "..%2Fheartguard.db",
                        "....//heartguard.db"):
            r = c.get(f"/system/backup/{attempt}/download", follow_redirects=False)
            check(f"traversal {attempt!r} does not serve a file",
                  r.status_code != 200 or b"SQLite" not in r.data[:64],
                  f"status {r.status_code}")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 7. a banned account cannot keep using its session ===")
if doc_b:
    with app.test_client() as c:
        sign_in(c, *TEMP["doctor_b"])
        r = c.get("/dashboard/")
        check("the account works before suspension", r.status_code == 200)
        db.ban_user(doc_b["id"], "security-test")
        r = c.get("/dashboard/", follow_redirects=False)
        check("the SAME session is rejected once suspended",
              r.status_code in (301, 302),
              "a revoked account kept its privileges until it chose to log out")
        db.unban_user(doc_b["id"], "security-test")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 8. login does not leak which half of the pair was wrong ===")
with app.test_client() as c:
    r1 = post(c, "/login", data={"username": "definitely_no_such_user",
                                "password": "x"}, follow_redirects=True)
    r2 = post(c, "/login", data={"username": "admin", "password": "wrong"},
                follow_redirects=True)
    check("unknown user and wrong password give the same message",
          (b"Incorrect username or password" in r1.data
           and b"Incorrect username or password" in r2.data),
          "the difference tells an attacker which usernames exist")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 9. the open-redirect guard on ?next= ===")
with app.test_client() as c:
    r = post(c, "/login?next=https://example.com/phish",
               data={"username": "admin", "password": "admin123"},
               follow_redirects=False)
    location = r.headers.get("Location", "")
    check("an absolute ?next= is not honoured", "example.com" not in location,
          location)
with app.test_client() as c:
    r = post(c, "/login?next=//example.com/phish",
               data={"username": "admin", "password": "admin123"},
               follow_redirects=False)
    check("a protocol-relative ?next= is not honoured",
          "example.com" not in r.headers.get("Location", ""),
          r.headers.get("Location", ""))


# ════════════════════════════════════════════════════════════════════════
print("\n=== 10. registration cannot choose its own role ===")
with app.test_client() as c:
    post(c, "/register", data={
        "username": "_sec_escalate", "fullname": "Escalation Attempt",
        "email": "esc@heartguard.local", "specialisation": "",
        "password": "escalate-pw-1", "confirm": "escalate-pw-1",
        "role": "SuperAdmin"}, follow_redirects=True)
    created = next((u for u in db.get_all_users()
                    if u["username"] == "_sec_escalate"), None)
    if created:
        check("a posted role field is ignored", created["role"] == "Doctor",
              f"registered as {created['role']}")
        db.delete_user(created["id"], "security-test")
    else:
        print("  [skip] registration is disabled in this configuration")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 11. cross-site request forgery ===")
# Without this, a page on another site can make a signed-in administrator's browser
# issue any POST here — the browser attaches the session cookie automatically, so the
# request arrives fully authenticated. The typed confirmations are no defence: the
# attacker writes the form, so they can type "DELETE ALL" into it too.
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        # Authenticated, but no token — exactly what a forged cross-site form sends.
        r = c.post("/system/backup/create", data={}, follow_redirects=False)
        check("a POST with no CSRF token is rejected", r.status_code == 400,
              f"got {r.status_code}")
        r = c.post("/system/backup/create", data={"csrf_token": "not-the-token"},
                   follow_redirects=False)
        check("a POST with a WRONG CSRF token is rejected", r.status_code == 400,
              f"got {r.status_code}")
        # And the legitimate path still works. This one really does create a backup,
        # so it is removed again — the earlier version left one file behind on every
        # run, which is how five stray snapshots accumulated in backups/.
        from backend.web import system as _system_web
        _before = set(os.listdir(_system_web.BACKUP_DIR)) \
            if os.path.isdir(_system_web.BACKUP_DIR) else set()
        r = post(c, "/system/backup/create", follow_redirects=False)
        check("a POST with the correct token still succeeds",
              r.status_code in (301, 302), f"got {r.status_code}")
        for _name in (set(os.listdir(_system_web.BACKUP_DIR)) - _before):
            os.remove(os.path.join(_system_web.BACKUP_DIR, _name))

    with app.test_client() as c:
        # GET must never be blocked by the check — safe methods do not change state.
        r = c.get("/login")
        check("GET is unaffected by the CSRF check", r.status_code == 200)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 12. response security headers ===")
with app.test_client() as c:
    r = c.get("/login")
    for header, expected in [
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
    ]:
        check(f"{header} is set", r.headers.get(header) == expected,
              repr(r.headers.get(header)))
    csp = r.headers.get("Content-Security-Policy", "")
    check("a Content-Security-Policy is sent", bool(csp))
    check("the CSP forbids scripts outright", "script-src 'none'" in csp, csp[:80])
    check("the CSP forbids framing", "frame-ancestors 'none'" in csp, csp[:80])


# ════════════════════════════════════════════════════════════════════════
print("\n=== 13. login rate limiting ===")
from backend.web import hardening

hardening.clear_failures("_ratelimit_probe", client_ip="127.0.0.1")
with app.test_client() as c:
    # Below the threshold the message stays the generic one.
    for _ in range(7):
        r = post(c, "/login", {"username": "_ratelimit_probe", "password": "wrong"},
                 follow_redirects=True)
    check("attempts below the limit are still processed",
          b"Incorrect username or password" in r.data)
    # Crossing it locks the pair out.
    for _ in range(3):
        r = post(c, "/login", {"username": "_ratelimit_probe", "password": "wrong"},
                 follow_redirects=True)
    check("repeated failures trip a lockout", b"Too many failed attempts" in r.data,
          "brute force is unthrottled")

# A correct password clears the counter, so a clinician who mistypes a few times and
# then gets it right is not locked out.
hardening.clear_failures("_ratelimit_probe", client_ip="127.0.0.1")
check("a successful sign-in clears the counter",
      hardening.is_locked_out("_ratelimit_probe", client_ip="127.0.0.1") == 0)

# And the lockout must not have spilled onto a real account.
admin_probe = account_for("SuperAdmin")
if admin_probe:
    with app.test_client() as c:
        r = sign_in(c, *admin_probe)
        check("a lockout on one username does not affect another",
              b"Dashboard" in r.data, "a real account was collaterally locked out")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 14. proxy headers are trusted only when configured ===")
# Behind a reverse proxy `request.remote_addr` is the PROXY's address, identical for
# every visitor. The rate limiter keys on (ip, username), so with a constant ip an
# attacker guessing at `admin` locks out the real administrator — the limiter becomes a
# denial-of-service tool aimed at real accounts. ProxyFix restores the true client
# address, but must NOT be on without a proxy in front, or a client sets its own
# X-Forwarded-For and gets a fresh identity per attempt.
import importlib


def _app_with(**env):
    for key in ("HEARTGUARD_TRUST_PROXY", "HEARTGUARD_HTTPS"):
        os.environ.pop(key, None)
    os.environ.update(env)
    for name in [n for n in list(sys.modules)
                 if n.startswith(("backend", "frontend", "shared"))]:
        del sys.modules[name]
    module = importlib.import_module("backend")
    return module.create_app({"TESTING": True})


def _observe(app):
    seen = {}

    @app.before_request
    def _capture():
        from flask import request as rq
        seen["ip"] = rq.remote_addr
        seen["scheme"] = rq.scheme

    with app.test_client() as client:
        client.get("/login", headers={"X-Forwarded-For": "203.0.113.9",
                                      "X-Forwarded-Proto": "https"})
    return seen


untrusted = _observe(_app_with())
check("a spoofed X-Forwarded-For is ignored by default",
      untrusted["ip"] != "203.0.113.9", untrusted["ip"])
check("the scheme is not taken from a header by default",
      untrusted["scheme"] == "http", untrusted["scheme"])

trusted = _observe(_app_with(HEARTGUARD_TRUST_PROXY="1"))
check("with a trusted proxy the real client address is used",
      trusted["ip"] == "203.0.113.9", trusted["ip"])
check("with a trusted proxy https is detected",
      trusted["scheme"] == "https", trusted["scheme"])


# ════════════════════════════════════════════════════════════════════════
print("\n=== 15. a Secure cookie on plain HTTP explains itself ===")
# This misconfiguration breaks every sign-in and looks nothing like its cause: the
# browser accepts the cookie and refuses to return it, so the server never sees a
# session and the CSRF check fails on every request. It is what happens when the
# container image is run locally over http.
secure_app = _app_with(HEARTGUARD_HTTPS="1")
check("HEARTGUARD_HTTPS sets the Secure flag",
      secure_app.config.get("SESSION_COOKIE_SECURE") is True)
with secure_app.test_client() as c:
    r = c.post("/login", data={"username": "admin", "password": "admin123"})
    text = r.data.decode("utf-8", "replace")
    check("sign-in over plain HTTP is refused", r.status_code == 400,
          str(r.status_code))
    check("the message names the Secure cookie as the cause",
          "marked Secure" in text)
    check("it does not blame an expired session",
          "session expired" not in text)

# Restore a clean environment for anything that runs after this.
for key in ("HEARTGUARD_TRUST_PROXY", "HEARTGUARD_HTTPS"):
    os.environ.pop(key, None)


# ── cleanup ─────────────────────────────────────────────────────────────
for pred in db.get_predictions():
    if pred.get("patient_name") == "Sec Patient A":
        db.delete_prediction(pred["id"], "security-test")
for uid in _created:
    if db.get_user_by_id(uid):
        db.delete_user(uid, "security-test")
print(f"\n  [cleanup] removed {len(_created)} test accounts")

print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for failure in FAILURES:
    print("  ", failure)
sys.exit(1 if FAILURES else 0)
