"""
End-to-end workflow tests: every write path actually performs its action.

`test_security.py` proves the wrong person cannot do these things. This proves the
RIGHT person can — that the action reaches the database and the page reflects it.
A guard that refuses everyone is not a working feature.

Every test restores what it changed.

Runnable standalone: `python tests/test_workflows.py`
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import config, create_app
from backend import repositories as db
from backend.domain import artifacts

FAILURES: list[str] = []


def check(name, condition, detail=""):
    if condition:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


app = create_app({"TESTING": True})
SEEDS = {"admin": "admin123", "superadmin": "superadmin123"}


def csrf(client) -> str:
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = "workflow-test-token"
            sess["_csrf_token"] = token
    return token


def post(client, path, data=None, **kw):
    payload = dict(data or {})
    payload.setdefault("csrf_token", csrf(client))
    return client.post(path, data=payload, **kw)


def sign_in(client, username, password):
    return post(client, "/login", {"username": username, "password": password},
                follow_redirects=True)


def account_for(role):
    for user in db.get_all_users():
        if user["role"] == role and user["username"] in SEEDS:
            return user["username"], SEEDS[user["username"]]
    return None


superadmin = account_for("SuperAdmin")
admin = account_for("Admin")


# ════════════════════════════════════════════════════════════════════════
print("=== 1. system settings round-trip ===")
if superadmin:
    original_reg = config.get_setting("allow_registration", True)
    original_thr = config.get_setting("risk_threshold")
    with app.test_client() as c:
        sign_in(c, *superadmin)
        post(c, "/system/settings",
             {"allow_registration": "on", "risk_threshold": "0.42"},
             follow_redirects=True)
        check("the threshold override is saved",
              config.get_setting("risk_threshold") == 0.42,
              str(config.get_setting("risk_threshold")))

        # And it must actually change the decision, not just the settings file.
        from backend.domain import risk
        check("the saved override reaches the risk domain",
              abs(risk.risk_threshold("Ensemble Voting") - 0.42) < 1e-9,
              str(risk.risk_threshold("Ensemble Voting")))

        # A blank field clears it — the documented way back to per-model thresholds.
        post(c, "/system/settings",
             {"allow_registration": "on", "risk_threshold": ""},
             follow_redirects=True)
        check("a blank field clears the override",
              config.get_setting("risk_threshold") is None,
              str(config.get_setting("risk_threshold")))

        # Out-of-range input is refused rather than stored.
        post(c, "/system/settings",
             {"allow_registration": "on", "risk_threshold": "5"},
             follow_redirects=True)
        check("an out-of-range threshold is refused",
              config.get_setting("risk_threshold") is None,
              str(config.get_setting("risk_threshold")))

        post(c, "/system/settings", {"risk_threshold": ""}, follow_redirects=True)
        check("registration can be turned off",
              config.get_setting("allow_registration") is False,
              str(config.get_setting("allow_registration")))
    config.set_setting("allow_registration", original_reg)
    config.set_setting("risk_threshold", original_thr)
    print("  [restored] settings")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 2. model toggles round-trip ===")
if superadmin:
    original = dict(artifacts.load_model_config())
    with app.test_client() as c:
        sign_in(c, *superadmin)
        # Enable only the first model.
        post(c, "/system/models", {"model_0": "on"}, follow_redirects=True)
        saved = artifacts.load_model_config()
        first = list(config.MODEL_FILES)[0]
        check("the toggle is persisted", saved.get(first) is True, str(saved))
        check("the other models were switched off",
              all(v is False for k, v in saved.items() if k != first), str(saved))

        from backend.ml import registry
        check("the registry reflects the toggle",
              set(registry.active_models()) == {first},
              str(sorted(registry.active_models())))

        # Turning everything off must be refused — an empty ensemble scores nothing.
        post(c, "/system/models", {}, follow_redirects=True)
        check("disabling every model is refused",
              any(artifacts.load_model_config().values()),
              "the institution was left with no scoring model")
    artifacts.save_model_config(original)
    from backend.ml import registry
    registry.reload_registry()
    check("[restored] every model re-enabled",
          len(registry.active_models()) == len(original))


# ════════════════════════════════════════════════════════════════════════
print("\n=== 3. backup create / download / restore ===")
if superadmin:
    from backend.web import system as system_web
    with app.test_client() as c:
        sign_in(c, *superadmin)
        before = os.listdir(system_web.BACKUP_DIR) if \
            os.path.isdir(system_web.BACKUP_DIR) else []
        post(c, "/system/backup/create", follow_redirects=True)
        after = os.listdir(system_web.BACKUP_DIR)
        created = [f for f in after if f not in before]
        check("a backup file is created", len(created) == 1, str(created))

        if created:
            name = created[0]
            r = c.get(f"/system/backup/{name}/download")
            check("the backup downloads", r.status_code == 200, str(r.status_code))
            check("it is a SQLite database", r.data[:15] == b"SQLite format 3",
                  str(r.data[:15]))
            # CLOSE IT. `send_file` streams from an open handle, and the test client
            # does not close the response for you — on Windows the file then cannot be
            # deleted. This is a test-harness detail, not a product bug: a real request
            # is closed by the server once the body has been sent, which was confirmed
            # by deleting the file successfully straight after `r.close()`.
            r.close()

            # A wrong confirmation must not overwrite the live database.
            users_before = len(db.get_all_users())
            post(c, f"/system/backup/{name}/restore", {"confirm": "wrong"},
                 follow_redirects=True)
            check("restore refuses a wrong confirmation",
                  len(db.get_all_users()) == users_before,
                  "the live database was overwritten without confirmation")

            os.remove(os.path.join(system_web.BACKUP_DIR, name))
            print(f"  [cleanup] removed {name}")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 4. dataset upload guards ===")
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        size_before = os.path.getsize(config.DATASET_CSV)
        # A non-CSV must be refused outright.
        r = post(c, "/admin/dataset",
                 {"dataset": (__import__("io").BytesIO(b"not a csv"), "evil.exe")},
                 content_type="multipart/form-data", follow_redirects=True)
        check("a non-CSV upload is refused",
              os.path.getsize(config.DATASET_CSV) == size_before,
              "the training dataset was replaced by a non-CSV file")
        r = post(c, "/admin/dataset", {}, content_type="multipart/form-data",
                 follow_redirects=True)
        check("an empty upload is refused",
              os.path.getsize(config.DATASET_CSV) == size_before)


# ════════════════════════════════════════════════════════════════════════
print("\n=== 5. recording a clinical outcome ===")
rows = db.get_predictions()
if rows and admin:
    row = rows[0]
    original_outcome = row.get("outcome")
    with app.test_client() as c:
        sign_in(c, *admin)
        post(c, f"/patients/outcome/{row['id']}",
             {"outcome": "confirmed", "outcome_notes": "workflow test"},
             follow_redirects=True)
        updated = next(r for r in db.get_predictions() if r["id"] == row["id"])
        check("the outcome is recorded", updated.get("outcome") == "confirmed",
              str(updated.get("outcome")))

        post(c, f"/patients/outcome/{row['id']}", {"outcome": "not-a-valid-value"},
             follow_redirects=True)
        updated = next(r for r in db.get_predictions() if r["id"] == row["id"])
        check("an invalid outcome value is refused",
              updated.get("outcome") == "confirmed", str(updated.get("outcome")))

        db.record_outcome(row["id"], original_outcome or "unknown", "", "workflow-test")
        print("  [restored] outcome")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 6. profile update round-trip ===")
if admin:
    me = next(u for u in db.get_all_users() if u["username"] == admin[0])
    original_name = me["fullname"]
    with app.test_client() as c:
        sign_in(c, *admin)
        post(c, "/account/profile",
             {"fullname": "Workflow Test Name", "email": me["email"],
              "specialisation": me.get("specialisation") or ""},
             follow_redirects=True)
        check("the profile name is updated",
              db.get_user_by_id(me["id"])["fullname"] == "Workflow Test Name",
              db.get_user_by_id(me["id"])["fullname"])

        # A mismatched password pair must change nothing.
        post(c, "/account/profile",
             {"fullname": "Workflow Test Name", "email": me["email"],
              "specialisation": "", "password": "abcdefgh", "confirm": "different"},
             follow_redirects=True)
        still_valid, status = db.validate_login(admin[0], admin[1])
        check("a mismatched password pair leaves the password alone",
              status == "ok", f"sign-in status is now {status!r}")

    db.update_user_profile(me["id"], original_name, me["email"],
                           me.get("specialisation") or "")
    print("  [restored] profile")


# ════════════════════════════════════════════════════════════════════════
print("\n=== 7. CSV export contains the caseload ===")
if admin:
    with app.test_client() as c:
        sign_in(c, *admin)
        r = c.get("/reports/export.csv")
        check("the export downloads", r.status_code == 200, str(r.status_code))
        body = r.data.decode("utf-8", "replace")
        check("it has a header row", body.startswith("id,timestamp,"), body[:40])
        check("it has one line per assessment",
              len(body.strip().splitlines()) == len(db.get_predictions()) + 1,
              f"{len(body.strip().splitlines())} lines for "
              f"{len(db.get_predictions())} rows")


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for failure in FAILURES:
    print("  ", failure)
sys.exit(1 if FAILURES else 0)
