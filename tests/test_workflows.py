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
print("\n=== 3. backup download / restore round-trip ===")
if superadmin:
    import io
    import json as _json

    with app.test_client() as c:
        sign_in(c, *superadmin)

        r = c.get("/system/backup/download")
        check("the backup downloads", r.status_code == 200, str(r.status_code))
        check("it is offered as an attachment",
              "attachment" in (r.headers.get("Content-Disposition") or ""),
              str(r.headers.get("Content-Disposition")))
        payload = r.data
        r.close()

        document = _json.loads(payload.decode("utf-8"))
        check("it declares the HeartGuard backup format",
              document.get("format") == "heartguard-backup", str(document.get("format")))
        check("it carries every table",
              set(document.get("tables", {})) ==
              {"users", "patients", "predictions", "system_logs", "training_runs",
               "app_settings"},
              str(sorted(document.get("tables", {}))))
        check("the user table is populated",
              len(document["tables"]["users"]) == len(db.get_all_users()),
              f"{len(document['tables']['users'])} vs {len(db.get_all_users())}")

        # The session signing key must not travel in a backup: a file that contains it
        # lets whoever holds it forge a session for any account, and backup files get
        # emailed and copied around.
        setting_keys = {row["key"] for row in document["tables"]["app_settings"]}
        check("the session signing key is redacted", "secret_key" not in setting_keys,
              "the backup file contains the session key")

        users_before = len(db.get_all_users())
        predictions_before = len(db.get_predictions())

        # A wrong confirmation must not touch the database.
        post(c, "/system/backup/restore",
             {"confirm": "wrong",
              "backup": (io.BytesIO(payload), "backup.json")},
             content_type="multipart/form-data", follow_redirects=True)
        check("restore refuses a wrong confirmation",
              len(db.get_all_users()) == users_before,
              "the live database was replaced without confirmation")

        # Neither must a file that is not a backup — even with the right confirmation.
        post(c, "/system/backup/restore",
             {"confirm": "RESTORE",
              "backup": (io.BytesIO(b'{"format": "something-else"}'), "evil.json")},
             content_type="multipart/form-data", follow_redirects=True)
        check("restore refuses a foreign document",
              len(db.get_all_users()) == users_before,
              "an unrecognised file was restored over the database")

        # The real thing: restoring the document just downloaded must be an identity
        # operation. If the delete/insert order, the column list or the id handling is
        # wrong, this is where the row counts stop matching.
        rr = post(c, "/system/backup/restore",
                  {"confirm": "RESTORE",
                   "backup": (io.BytesIO(payload), "backup.json")},
                  content_type="multipart/form-data", follow_redirects=True)
        check("the restore is accepted", rr.status_code == 200, str(rr.status_code))
        check("every account survived the round-trip",
              len(db.get_all_users()) == users_before,
              f"{len(db.get_all_users())} accounts, was {users_before}")
        check("every assessment survived the round-trip",
              len(db.get_predictions()) == predictions_before,
              f"{len(db.get_predictions())} assessments, was {predictions_before}")

        # And the database must still accept new rows afterwards. On Postgres the
        # identity sequences are left pointing at 1 by a restore that inserts explicit
        # ids, so the next INSERT collides with a restored row — a restore that looks
        # successful and breaks the first thing anyone does next.
        new_id, err = db.register_user("_backup_probe", "probe-pw-1234", "Doctor",
                                       "Backup Probe", "probe@heartguard.local", "")
        check("a new row can still be inserted after a restore",
              new_id is not None, f"insert failed after restore: {err}")
        if new_id is not None:
            db.delete_user(new_id, "workflow-test")
            print("  [cleanup] removed _backup_probe")


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

# On a database that has never been used there is nothing to record an outcome
# AGAINST, and this section used to skip silently — which meant the outcome path was
# never exercised on a fresh installation, i.e. on exactly the deployment most likely
# to be broken. Make the row it needs, and remove it afterwards.
_seeded_prediction = None
if not rows and admin:
    _actor = next((u for u in db.get_all_users() if u["role"] == "Doctor"), None) \
        or next(iter(db.get_all_users()), None)
    if _actor:
        _seeded_prediction = db.add_prediction(
            _actor["id"], 61, 2, 168, 88, 148, 92, 2, 1, 0, 0, 1,
            1, 0.63, "Ensemble Voting", patient_name="Workflow Seed",
            notes="created by test_workflows to exercise the outcome path",
            risk_band="High", threshold_used=0.44, model_version="test")
        rows = db.get_predictions()
        print(f"  [setup] created prediction {_seeded_prediction}")

if rows and admin:
    row = rows[0]
    original_outcome = row.get("outcome")
    with app.test_client() as c:
        sign_in(c, *admin)
        post(c, f"/patients/outcome/{row['id']}",
             {"outcome": "confirmed", "outcome_notes": "workflow test"},
             follow_redirects=True)
        updated = next(r for r in db.get_predictions() if r["id"] == row["id"])
        # 1, not "confirmed". The column is INTEGER and every calculation compares
        # against 1; storing the form's own word is what made the deployed-performance
        # statistics silently empty. See shared/formatting.py.
        check("the outcome is recorded as the stored integer",
              updated.get("outcome") == 1, repr(updated.get("outcome")))

        # And it must now actually COUNT. This is the assertion whose absence let the
        # bug live: the write succeeded, so a test of the write alone passed.
        stats, _rows = db.get_outcome_stats()
        check("the recorded outcome reaches the statistics",
              stats.get("with_outcome", 0) >= 1, str(stats.get("with_outcome")))

        post(c, f"/patients/outcome/{row['id']}", {"outcome": "not-a-valid-value"},
             follow_redirects=True)
        updated = next(r for r in db.get_predictions() if r["id"] == row["id"])
        check("an invalid outcome value is refused",
              updated.get("outcome") == 1, repr(updated.get("outcome")))

        db.record_outcome(row["id"], original_outcome, "", "workflow-test")
        print("  [restored] outcome")

if _seeded_prediction is not None:
    db.delete_prediction(_seeded_prediction, "workflow-test")
    print(f"  [cleanup] removed prediction {_seeded_prediction}")


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

        # THE PROFILE FORM MUST ENFORCE THE REGISTRATION POLICY.
        #
        # It used to check only that a new password was 8 characters, while
        # registration checked far more — so an account created under the full policy
        # could be edited straight past it. Each case below must leave the existing
        # password working; if any of them takes effect, the sign-in that follows fails
        # and says so.
        WEAK = [
            ("a mismatched pair", "abcdefgh12", "different12"),
            ("a password with no digit", "onlylettershere", "onlylettershere"),
            ("a password with no letter", "1234567890", "1234567890"),
            ("a seven-character password", "short12", "short12"),
        ]
        for label, pw, confirm in WEAK:
            post(c, "/account/profile",
                 {"fullname": "Workflow Test Name", "email": me["email"],
                  "specialisation": "", "password": pw, "confirm": confirm},
                 follow_redirects=True)
            _ok, status = db.validate_login(admin[0], admin[1])
            check(f"profile refuses {label}", status == "ok",
                  f"the password was changed; sign-in status is now {status!r}")

        # An invalid email must not save either — this form had no email rule at all.
        post(c, "/account/profile",
             {"fullname": "Workflow Test Name", "email": "not-an-email",
              "specialisation": ""}, follow_redirects=True)
        check("profile refuses a malformed email",
              db.get_user_by_id(me["id"])["email"] == me["email"],
              str(db.get_user_by_id(me["id"])["email"]))

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
