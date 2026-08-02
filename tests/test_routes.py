"""
Route smoke tests: every GET page, for every role, must render.

Runnable without pytest (`python tests/test_routes.py`) so the gate does not depend on
a runner that is absent from requirements.txt — the same convention the rest of this
suite follows.

WHAT THIS CATCHES that a unit test cannot: a template that references a variable the
view does not pass, a url_for pointing at an endpoint that was renamed, and a role
guard that lets the wrong person in. All three are invisible until something renders.
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


app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False})


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


def sign_in(client, username, password):
    return post(client, "/login",
                {"username": username, "password": password},
                follow_redirects=True)


def _first_user(role):
    return next((u for u in db.get_all_users() if u["role"] == role), None)


# ════════════════════════════════════════════════════════════════════════
print("=== 1. public routes ===")
with app.test_client() as c:
    r = c.get("/login")
    check("GET /login renders", r.status_code == 200, str(r.status_code))
    check("login page carries the sign-in form", b'name="password"' in r.data)
    r = c.get("/", follow_redirects=False)
    check("GET / redirects to login", r.status_code in (301, 302), str(r.status_code))
    r = c.get("/dashboard/", follow_redirects=False)
    check("dashboard is guarded when signed out",
          r.status_code in (301, 302), str(r.status_code))
    check("guard redirects to login", "/login" in r.headers.get("Location", ""))


# ════════════════════════════════════════════════════════════════════════
print("\n=== 2. authentication ===")
with app.test_client() as c:
    r = sign_in(c, "admin", "definitely-not-the-password")
    check("bad password is rejected", b"Incorrect username or password" in r.data)
    r = sign_in(c, "admin", "admin123")
    check("valid credentials sign in", b"Dashboard" in r.data, str(r.status_code))
    r = c.get("/logout", follow_redirects=True)
    check("logout returns to the sign-in screen", b'name="password"' in r.data)


# ════════════════════════════════════════════════════════════════════════
# Every page, per role. The expectation is 200 for pages the role may open and a
# redirect for pages it may not — never a 500, which is what a broken template gives.
ROLE_PAGES = {
    "Admin": {
        200: ["/dashboard/", "/patients/", "/reports/", "/reports/export.csv",
              "/performance/", "/admin/doctors", "/admin/predictions",
              "/admin/dataset", "/system/analytics", "/account/profile"],
        302: ["/screening/", "/screening/history", "/admin/admins", "/admin/roles",
              "/system/settings", "/system/models", "/system/logs", "/system/backup"],
    },
    "SuperAdmin": {
        200: ["/dashboard/", "/performance/", "/admin/doctors", "/admin/admins",
              "/admin/roles", "/system/settings", "/system/models", "/system/logs",
              "/system/backup", "/system/analytics", "/account/profile"],
        302: ["/screening/", "/screening/history"],
    },
    "Doctor": {
        200: ["/dashboard/", "/screening/", "/screening/history", "/patients/",
              "/reports/", "/performance/", "/account/profile"],
        302: ["/admin/admins", "/admin/roles", "/system/settings", "/system/logs",
              "/system/backup", "/admin/predictions"],
    },
}

SEED_PASSWORDS = {"admin": "admin123", "superadmin": "superadmin123",
                  "doctor": "doctor123"}

# A throwaway Doctor, created for the run and removed at the end.
#
# The seeded `doctor` account cannot be relied on: its role is editable from inside the
# application, so in a database that has been used it may be anything. Rather than skip
# the entire Doctor surface — which is the clinical half of the product — the suite
# makes an account it controls the password for, and deletes it afterwards.
TEMP_DOCTOR = ("_routetest_doctor", "route-test-pw-8891")


def _ensure_temp_doctor() -> bool:
    """
    Make sure the throwaway Doctor exists, whoever created it.

    A leftover account from an interrupted run used to leave this False, which silently
    skipped every Doctor assertion — the suite reported all-green while never touching
    the clinical half of the product. Existing-or-created both count as usable; only
    the password has to be one we know, and a leftover has the same one.

    `register_user` returns (user_id, error), not (ok, message).
    """
    if any(u["username"] == TEMP_DOCTOR[0] for u in db.get_all_users()):
        return True
    user_id, error = db.register_user(
        TEMP_DOCTOR[0], TEMP_DOCTOR[1], "Doctor",
        "Route Test Doctor", "routetest@heartguard.local", "")
    if error:
        print(f"  [warn] could not create the test Doctor: {error}")
    return user_id is not None


_temp_created = _ensure_temp_doctor()


def _account_for(role):
    """An account of this role whose password the suite knows."""
    if role == "Doctor" and _temp_created:
        return TEMP_DOCTOR
    for user in db.get_all_users():
        if user["role"] == role and user["username"] in SEED_PASSWORDS:
            return user["username"], SEED_PASSWORDS[user["username"]]
    return None


for role, expectations in ROLE_PAGES.items():
    print(f"\n=== 3. pages for {role} ===")
    account = _account_for(role)
    if not account:
        print(f"  [skip] no {role} account with a known password")
        continue
    username, password = account

    with app.test_client() as c:
        signed = sign_in(c, username, password)
        if b"Dashboard" not in signed.data:
            print(f"  [skip] could not sign in as {username}")
            continue
        for path in expectations[200]:
            r = c.get(path)
            check(f"{role} GET {path} -> 200", r.status_code == 200,
                  f"got {r.status_code}")
        for path in expectations[302]:
            r = c.get(path, follow_redirects=False)
            check(f"{role} GET {path} is refused", r.status_code in (301, 302),
                  f"got {r.status_code}")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 4. charts render as PNG ===")
admin = _first_user("Admin")
if admin and admin["username"] == "admin":
    with app.test_client() as c:
        sign_in(c, "admin", "admin123")
        for path in ["/charts/model-discrimination.png", "/charts/risk-mix.png"]:
            r = c.get(path)
            check(f"GET {path}", r.status_code == 200, str(r.status_code))
            if r.status_code == 200:
                check(f"{path} is a PNG", r.data[:8] == b"\x89PNG\r\n\x1a\n")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 5. escaping (stored XSS guard) ===")
with app.test_client() as c:
    sign_in(c, "admin", "admin123")
    r = c.get("/admin/predictions")
    # Jinja autoescapes by default; this asserts it is actually on for these pages,
    # because the database really does contain a row with a script payload in it.
    check("no unescaped <img onerror= reaches the page",
          b'<img src=x onerror=' not in r.data)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 6. end-to-end assessment (Doctor) ===")
doctor = _account_for("Doctor")
if doctor:
    with app.test_client() as c:
        sign_in(c, *doctor)
        before = len(db.get_predictions())
        r = post(c, "/screening/", data={
            "patient_code": "PT-ROUTETEST", "patient_name": "Route Test Patient",
            "age": 68, "gender": 2, "height": 172, "weight": 96.0,
            "ap_hi": 165, "ap_lo": 98, "cholesterol": 3, "gluc": 2,
            "smoke": 1, "alco": 0, "active": 0,
            "model": "Ensemble Voting", "notes": "route smoke test",
        }, follow_redirects=True)
        check("assessment POST renders a result", r.status_code == 200,
              str(r.status_code))
        check("a verdict is shown", b"Screening result" in r.data)
        check("the assessment was persisted", len(db.get_predictions()) == before + 1)

        # The two text fields are validated too, and neither used to be. A blank or
        # malformed patient code is not cosmetic: it is the identifier a repeat visit
        # attaches to, and the column is UNIQUE NOT NULL.
        for label, override in [
            ("an empty patient code", {"patient_code": ""}),
            ("a patient code with spaces", {"patient_code": "PT 001"}),
            ("a one-character patient name", {"patient_name": "X"}),
            ("an empty patient name", {"patient_name": ""}),
        ]:
            payload = {
                "patient_code": "PT-ROUTETEST", "patient_name": "Route Test Patient",
                "age": 68, "gender": 2, "height": 172, "weight": 96.0,
                "ap_hi": 165, "ap_lo": 98, "cholesterol": 3, "gluc": 2,
                "smoke": 1, "alco": 0, "active": 0, "model": "Ensemble Voting",
            }
            payload.update(override)
            count_before = len(db.get_predictions())
            post(c, "/screening/", data=payload, follow_redirects=True)
            check(f"{label} is refused",
                  len(db.get_predictions()) == count_before,
                  "an assessment was stored against an invalid patient identifier")

        # Refusal path: an impossible blood pressure must be refused, not scored.
        r = post(c, "/screening/", data={
            "patient_code": "PT-ROUTETEST", "patient_name": "Route Test Patient",
            "age": 50, "gender": 2, "height": 170, "weight": 80.0,
            "ap_hi": 90, "ap_lo": 180, "cholesterol": 1, "gluc": 1,
            "smoke": 0, "alco": 0, "active": 1, "model": "Ensemble Voting",
        }, follow_redirects=True)
        check("impossible physiology is refused", b"Assessment not run" in r.data)

        rows = db.get_predictions()
        mine = next((x for x in rows if x["patient_name"] == "Route Test Patient"), None)
        if mine:
            r = c.get(f"/screening/report/{mine['id']}.txt")
            check("text report downloads", r.status_code == 200, str(r.status_code))
            check("report names the patient", b"Route Test Patient" in r.data)
            r = c.get(f"/screening/report/{mine['id']}.pdf")
            check("PDF report downloads", r.status_code == 200, str(r.status_code))
            check("PDF has a PDF header", r.data[:5] == b"%PDF-")
            # Clean up the row this test created.
            db.delete_prediction(mine["id"], "route-test")


# Remove the throwaway account so the suite leaves the database as it found it.
if _temp_created:
    temp = next((u for u in db.get_all_users() if u["username"] == TEMP_DOCTOR[0]), None)
    if temp:
        db.delete_user(temp["id"], "route-test")
        print(f"\n  [cleanup] removed {TEMP_DOCTOR[0]}")


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for failure in FAILURES:
    print("  ", failure)
sys.exit(1 if FAILURES else 0)
