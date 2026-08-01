"""
The three sign-in entrances: /login, /admin/login, /superadmin/login.

WHAT IS ACTUALLY AT RISK HERE, and what each section below is defending:

  1. A role oracle. If the wrong-door refusal differs in any way from a wrong-password
     refusal, /superadmin/login becomes a tool for finding out which usernames hold
     privileged roles AND for confirming a guessed password. Section 4 asserts the two
     responses are byte-identical, which is the only form of this assertion that cannot
     be satisfied by accident.

  2. A session created and then not cleaned up. Section 5 checks that a refused
     sign-in leaves the client signed out, by asking for a guarded page afterwards.

  3. Extra doors meaning extra guesses. The lockout is keyed on (address, username)
     with no endpoint component; section 7 proves failures at one portal count at
     another, so three portals do not triple an attacker's budget.

Every lockout counter this file touches is cleared again. The activity-log entries it
produces are deliberately NOT removed: they are truthful records of a correct password
arriving at the wrong door, and a test suite that quietly deletes audit rows is a worse
thing to own than a few test entries in a demonstration log.

Runnable standalone: `python tests/test_portals.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app
from backend import repositories as db
from backend.web import auth as auth_web
from backend.web import hardening

FAILURES: list[str] = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


app = create_app({"TESTING": True})

SEEDS = {"admin": "admin123", "superadmin": "superadmin123"}
TEST_IP = "127.0.0.1"          # what the Werkzeug test client reports as REMOTE_ADDR


def csrf(client) -> str:
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = "portal-test-token"
            sess["_csrf_token"] = token
    return token


def post(client, path, data=None, **kw):
    payload = dict(data or {})
    payload.setdefault("csrf_token", csrf(client))
    return client.post(path, data=payload, **kw)


def account_for(role):
    """A live account of this role whose password the suite knows."""
    for user in db.get_all_users():
        if user["role"] == role and user["username"] in SEEDS:
            return user["username"], SEEDS[user["username"]]
    return None


admin = account_for("Admin")
superadmin = account_for("SuperAdmin")


# ════════════════════════════════════════════════════════════════════════
print("=== 1. every entrance renders at its own path ===")
EXPECTED_PATHS = {
    "auth.login": "/login",
    "auth.admin_login": "/admin/login",
    "auth.superadmin_login": "/superadmin/login",
}
with app.test_request_context():
    from flask import url_for
    for endpoint, expected in EXPECTED_PATHS.items():
        try:
            built = url_for(endpoint)
        except Exception as exc:                              # noqa: BLE001
            built = f"<{type(exc).__name__}>"
        check(f"{endpoint} is registered at {expected}", built == expected, built)

with app.test_client() as c:
    for path, heading in [("/login", b"Sign in"),
                          ("/admin/login", b"Administrator sign-in"),
                          ("/superadmin/login", b"System administrator sign-in")]:
        r = c.get(path)
        check(f"GET {path} -> 200", r.status_code == 200, str(r.status_code))
        check(f"{path} shows its own heading", heading in r.data)
        check(f"{path} carries a password field", b'name="password"' in r.data)
        # The form must post back to the door it was served from. Posting to /login
        # instead would quietly restore the universal entrance and make the role gate
        # unreachable, while the page still looked correct.
        check(f"{path} posts back to itself",
              f'action="{path}"'.encode() in r.data,
              "the form posts somewhere else")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 2. self-registration is offered on the clinical door only ===")
with app.test_client() as c:
    r = c.get("/login")
    clinical_has_tabs = b"auth__tabs" in r.data
    for path in ("/admin/login", "/superadmin/login"):
        r = c.get(path)
        # register() fixes the role to Doctor, so a Register tab here would offer an
        # account that cannot open the page it was created from.
        check(f"{path} offers no Register tab", b"auth__tabs" not in r.data)
        check(f"{path} does not link to /register", b'href="/register"' not in r.data)
    print(f"  [info] clinical door shows tabs: {clinical_has_tabs} "
          f"(depends on the allow_registration setting)")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 3. each door admits its own role ===")
if admin:
    with app.test_client() as c:
        r = post(c, "/admin/login", {"username": admin[0], "password": admin[1]},
                 follow_redirects=True)
        check("an Admin signs in at /admin/login", b"Dashboard" in r.data,
              str(r.status_code))
if superadmin:
    with app.test_client() as c:
        r = post(c, "/superadmin/login",
                 {"username": superadmin[0], "password": superadmin[1]},
                 follow_redirects=True)
        check("a SuperAdmin signs in at /superadmin/login", b"Dashboard" in r.data,
              str(r.status_code))

# The universal entrance is retained on purpose — see the PORTALS comment in
# backend/web/auth.py. If this ever fails, every existing bookmark and all three other
# test files broke with it.
if admin:
    with app.test_client() as c:
        r = post(c, "/login", {"username": admin[0], "password": admin[1]},
                 follow_redirects=True)
        check("/login still admits an Admin", b"Dashboard" in r.data, str(r.status_code))
if superadmin:
    with app.test_client() as c:
        r = post(c, "/login",
                 {"username": superadmin[0], "password": superadmin[1]},
                 follow_redirects=True)
        check("/login still admits a SuperAdmin", b"Dashboard" in r.data,
              str(r.status_code))


# ════════════════════════════════════════════════════════════════════════
print("\n=== 4. the wrong door leaks nothing ===")
if admin and superadmin:
    with app.test_client() as c:
        # Same client, so the CSRF token and every other per-session value are
        # identical between the two responses and the comparison is meaningful.
        wrong_password = post(c, "/superadmin/login",
                              {"username": superadmin[0],
                               "password": "definitely-not-the-password"})
        wrong_door = post(c, "/superadmin/login",
                          {"username": admin[0], "password": admin[1]})

        check("a correct password at the wrong door is refused",
              b"Dashboard" not in wrong_door.data)
        check("the refusal is the generic message",
              b"Incorrect username or password." in wrong_door.data)
        # The strongest available form of "no oracle": not a similar page, the SAME page.
        check("wrong-door and wrong-password responses are byte-identical",
              wrong_door.data == wrong_password.data,
              f"{len(wrong_door.data)} vs {len(wrong_password.data)} bytes")
        check("the refusal names no role",
              b"SuperAdmin" not in wrong_door.data and b"Doctor" not in wrong_door.data)

    # Roles are jobs, not ranks — the same rule that keeps clinical pages off an
    # administrator's menu. A SuperAdmin is therefore NOT admitted at /admin/login.
    with app.test_client() as c:
        r = post(c, "/admin/login",
                 {"username": superadmin[0], "password": superadmin[1]},
                 follow_redirects=True)
        check("a SuperAdmin is refused at /admin/login", b"Dashboard" not in r.data)

    hardening.clear_failures(admin[0], TEST_IP)
    hardening.clear_failures(superadmin[0], TEST_IP)
    print("  [restored] lockout counters for the seed accounts")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 5. a refused sign-in leaves no session behind ===")
if admin:
    with app.test_client() as c:
        post(c, "/superadmin/login", {"username": admin[0], "password": admin[1]})
        # If a session had been established and only the redirect withheld, this would
        # return the page instead of bouncing to the sign-in screen.
        r = c.get("/dashboard/", follow_redirects=False)
        check("the client is still signed out", r.status_code in (301, 302),
              f"got {r.status_code}")
        with c.session_transaction() as sess:
            check("no user_id was written to the session",
                  sess.get("user_id") is None, str(sess.get("user_id")))
    hardening.clear_failures(admin[0], TEST_IP)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 6. the wrong door is recorded, because only a real password reaches it ===")
if admin:
    # Identity, not COUNT. get_system_logs caps its result at `limit`, and this
    # installation's log is already longer than any cap worth passing — so
    # len(after) > len(before) is False however many entries are written, and the
    # assertion could never fail. Comparing row ids is independent of the cap.
    before_ids = {row["id"] for row in db.get_system_logs(limit=500)}
    with app.test_client() as c:
        post(c, "/superadmin/login", {"username": admin[0], "password": admin[1]})
    new_rows = [row for row in db.get_system_logs(limit=500)
                if row["id"] not in before_ids]
    refusals = [row for row in new_rows if row["action"] == "Login refused"]
    check("the refusal is written to the activity log", bool(refusals),
          f"{len(new_rows)} new entries, none of them a refusal")
    if refusals:
        check("the log entry names the account that presented the password",
              refusals[0]["username"] == admin[0], str(refusals[0]["username"]))
        check("the log entry does not store the password",
              admin[1] not in (refusals[0]["details"] or ""),
              "the submitted password was written to the activity log")
    hardening.clear_failures(admin[0], TEST_IP)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 7. the three doors share one budget of attempts ===")
PROBE = "_portal_probe_account"
hardening.clear_failures(PROBE, TEST_IP)
with app.test_client() as c:
    # Spend the allowance at the administrator door...
    for _ in range(8):
        post(c, "/admin/login", {"username": PROBE, "password": "wrong"})
    check("the limiter has tripped for this username",
          hardening.is_locked_out(PROBE, TEST_IP) > 0,
          "eight failures did not trip the lockout")
    # ...and it must be spent at the clinical door too. If the key included the
    # endpoint, this attempt would be allowed and three portals would mean three
    # times the guesses.
    r = post(c, "/login", {"username": PROBE, "password": "wrong"})
    check("the lockout applies at a different door",
          b"Too many failed attempts" in r.data,
          "the lockout was scoped to one endpoint")
hardening.clear_failures(PROBE, TEST_IP)
check("[restored] the probe lockout is cleared",
      hardening.is_locked_out(PROBE, TEST_IP) == 0)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 8. the new doors are not a CSRF hole ===")
if admin:
    for path in ("/admin/login", "/superadmin/login"):
        with app.test_client() as c:
            c.get(path)                      # establish a session and its token
            r = c.post(path, data={"username": admin[0], "password": admin[1]})
            check(f"POST {path} without a token is refused", r.status_code == 400,
                  f"got {r.status_code}")
    hardening.clear_failures(admin[0], TEST_IP)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 9. an already signed-in user is sent on ===")
if admin:
    with app.test_client() as c:
        post(c, "/login", {"username": admin[0], "password": admin[1]},
             follow_redirects=True)
        for path in ("/login", "/admin/login", "/superadmin/login"):
            r = c.get(path, follow_redirects=False)
            check(f"signed in, GET {path} redirects away",
                  r.status_code in (301, 302), f"got {r.status_code}")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 10. every door offers the way to the others ===")
with app.test_client() as c:
    for key, path in [("clinical", "/login"), ("admin", "/admin/login"),
                      ("superadmin", "/superadmin/login")]:
        r = c.get(path)
        others = auth_web._other_portals(key)
        check(f"{path} lists the other two entrances", len(others) == 2, str(others))
        for other in others:
            target = EXPECTED_PATHS[other["endpoint"]].encode()
            check(f"{path} links to {target.decode()}",
                  b'href="' + target + b'"' in r.data,
                  "a user at the wrong door has no way to the right one")


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for failure in FAILURES:
    print("  ", failure)
sys.exit(1 if FAILURES else 0)
