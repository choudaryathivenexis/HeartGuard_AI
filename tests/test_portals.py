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

from backend import config, create_app
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


# ════════════════════════════════════════════════════════════════════════
print("\n=== 11. the sign-in panel image ===")
# The image is a CSS background, so a missing or misnamed file does not raise: the
# panel renders as flat colour and everything still returns 200. Nothing about the
# page would tell you, which is precisely why it is asserted here.
_HERO = os.path.join(config.STATIC_DIR, "img", "auth-hero.webp")

check("the image ships with the project", os.path.isfile(_HERO), _HERO)
if os.path.isfile(_HERO):
    _size_kb = os.path.getsize(_HERO) / 1024
    # A login page is the first request anyone makes, often on a phone. This is not a
    # style rule — an unoptimised export of this image was 1.3 MB.
    check(f"it is small enough to serve ({_size_kb:.0f} KB)", _size_kb < 400,
          f"{_size_kb:.0f} KB is too heavy for a sign-in page")
    with open(_HERO, "rb") as _fh:
        _magic = _fh.read(12)
    check("it is a real WebP file",
          _magic[:4] == b"RIFF" and _magic[8:12] == b"WEBP", str(_magic))

with app.test_client() as c:
    page = c.get("/login").data
    check("the panel text was removed", b"auth__statement" not in page
          and b"auth__markers" not in page)
    # Served, not just present on disk: a static route that 404s looks identical to a
    # missing file from the browser's point of view.
    r = c.get("/static/img/auth-hero.webp")
    check("the image is served", r.status_code == 200, str(r.status_code))
    check("it is served as an image", (r.headers.get("Content-Type") or "")
          .startswith("image/"), str(r.headers.get("Content-Type")))
    r.close()

    css = c.get("/static/css/app.css").data.decode("utf-8", "replace")
    check("the stylesheet points at it", "auth-hero.webp" in css,
          "the panel would render as flat colour")
    # The logo has to be the themed lockup now. The white mono version was correct on
    # the old dark panel and is invisible on this one — a failure that renders as a
    # blank corner rather than as an error.
    check("the white-on-white logo is gone", b"brand_lockup_mono" not in page
          and b"#FFFFFF" not in page.split(b"auth__formside")[0],
          "the lockup may be white on a pale panel")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 12. registration validation is enforced SERVER-side ===")
# The form carries required/minlength/pattern attributes, and they are worth nothing:
# devtools removes them and curl never sees them. These cases post directly.
_VALID = {"fullname": "Dr Probe Name", "username": "_valtest_ok",
          "email": "probe@heartguard.local",
          "password": "longenough123", "confirm": "longenough123"}

BAD_CASES = [
    ("a two-character username", {"username": "ab"}),
    ("a username with spaces", {"username": "bad name"}),
    ("a username with a symbol", {"username": "drop;table"}),
    ("a malformed email", {"email": "not-an-email"}),
    ("a seven-character password", {"password": "short12", "confirm": "short12"}),
    # "Alphanumeric" is enforced as MUST CONTAIN a letter and a digit — symbols stay
    # legal, because banning them shrinks the search space an attacker has to cover.
    # See the note at the top of backend/services/validation.py.
    ("a password with no digit", {"password": "onlylettershere",
                                  "confirm": "onlylettershere"}),
    ("a password with no letter", {"password": "1234567890",
                                   "confirm": "1234567890"}),
    ("mismatched passwords", {"confirm": "somethingelse12"}),
    ("a one-character full name", {"fullname": "X"}),
    ("an empty full name", {"fullname": ""}),
]

# Self-registration can be switched off by a SuperAdmin, and /register then redirects
# to the sign-in page without looking at the payload. Every check below would "pass"
# against that redirect while proving nothing, so the state is read rather than assumed.
from backend import config as _config  # noqa: E402

if not _config.get_setting("allow_registration", True):
    print("  [skip] self-registration is disabled in this installation")
else:
    for label, override in BAD_CASES:
        payload = dict(_VALID)
        payload.update(override)
        # A distinct username per case, so a rejection cannot be mistaken for the
        # duplicate-username refusal.
        payload.setdefault("username", "_valtest_ok")
        if "username" not in override:
            payload["username"] = f"_valtest_{abs(hash(label)) % 9999}"
        with app.test_client() as c:
            names_before = {u["username"] for u in db.get_all_users()}
            r = post(c, "/register", payload, follow_redirects=True)
            created = {u["username"] for u in db.get_all_users()} - names_before
            check(f"{label} is refused", not created,
                  f"an account was created: {created}")
            check(f"  and {label} is explained to the user",
                  b"alert--danger" in r.data,
                  "refused with no message on the page")

    # A symbol-bearing password must be ACCEPTED. Without this, "no digit" and "no
    # letter" passing would be equally consistent with a rule that banned symbols —
    # which is the wrong rule, and the one this deliberately does not implement.
    with app.test_client() as c:
        _sym = dict(_VALID)
        _sym.update({"username": "_valtest_sym",
                     "password": "Str0ng!Pass#2026", "confirm": "Str0ng!Pass#2026"})
        post(c, "/register", _sym, follow_redirects=True)
        _made = next((u for u in db.get_all_users()
                      if u["username"] == "_valtest_sym"), None)
        check("a password containing symbols is accepted", _made is not None,
              "symbols are being rejected, which weakens every password")
        if _made:
            db.delete_user(_made["id"], "portal-test")

    # The control: the same payload with nothing wrong must succeed, or the tests above
    # would pass just as well against a form that refuses everybody.
    with app.test_client() as c:
        r = post(c, "/register", dict(_VALID), follow_redirects=True)
        made = next((u for u in db.get_all_users()
                     if u["username"] == _VALID["username"]), None)
        check("a valid registration still succeeds", made is not None,
              "the form refuses everything, which would make the checks above vacuous")
        if made:
            check("and it is created as a Doctor", made["role"] == "Doctor",
                  str(made["role"]))
            db.delete_user(made["id"], "portal-test")
            print(f"  [cleanup] removed {_VALID['username']}")


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for failure in FAILURES:
    print("  ", failure)
sys.exit(1 if FAILURES else 0)
