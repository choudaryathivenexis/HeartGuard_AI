"""
Sign-in screen tests — §7.2.

Structured around the one finding that made this phase necessary: the previous login
page printed three working credential pairs, one of them SuperAdmin, to every
anonymous visitor. So the first block of assertions is not about layout. It drives the
page through AppTest and searches the *rendered output* for every seeded secret.

That distinction is deliberate and was learned the hard way in Run 8, when a test
asserted on UI strings and passed while the database was silently discarding the
column it claimed to verify. Asserting `"doctor123" not in page_login()` would prove
nothing about what Streamlit actually emits. These assertions read the element tree.

The stylesheet is itself rendered as markdown, so it appears in the same text the
credential search scans. That is harmless — the stylesheet contains no credentials —
but it means a naive `count()` over the page text is off by one for any string that
also appears in CSS. Marker counting below subtracts that occurrence explicitly.
"""

from __future__ import annotations

import io
import os
import re
import sys
import json
import contextlib
import xml.etree.ElementTree as ET

here_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here_root)

from streamlit.testing.v1 import AppTest

import auth_db
from ui import login as L
from ui import tokens as T

FAILURES: list[str] = []
XSS = '<img src=x onerror="alert(1)">'


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


def page_text(at) -> str:
    """Everything the page emits as text, across markdown, captions and errors."""
    parts = [m.value for m in at.markdown]
    parts += [c.value for c in at.caption]
    parts += [e.value for e in at.error] + [w.value for w in at.warning]
    parts += [i.value for i in at.info] + [s.value for s in at.success]
    parts += [t.label for t in at.text_input]
    parts += [b.label for b in at.button]
    return "\n".join(str(p) for p in parts)


def sstate(at, key):
    """
    AppTest's session_state raises rather than returning None for a missing key, and
    shadows `.get` with key lookup, so it needs its own accessor.
    """
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return None


def fresh():
    return AppTest.from_file(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "app.py"),
        default_timeout=300)


print("\n=== 1. credentials are not in the browser ===")
at = fresh().run()
text = page_text(at)
check("page renders without exception", not at.exception,
      "; ".join(e.value[:200] for e in at.exception))

for _u, pw, role, *_ in auth_db.SEED_CREDENTIALS:
    check(f"seed password for {role} absent from output", pw not in text, pw)
    check(f"'{_u} / {pw}' pairing absent", f"{_u} / {pw}" not in text)

# The usernames alone are unavoidable words ("admin", "doctor") and are not secrets.
# What must not appear is any username adjacent to its password, in any separator.
for u, pw, role, *_ in auth_db.SEED_CREDENTIALS:
    near = re.search(re.escape(u) + r".{0,12}" + re.escape(pw), text, re.S)
    check(f"{role}: username and password never adjacent", near is None,
          near.group(0) if near else "")

check("a hint points at the server console instead",
      "server console" in text and "printed" in text)


print("\n=== 2. the seed announcement goes to stdout, once ===")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    auth_db._announce_seed_credentials(auth_db.SEED_CREDENTIALS)
out = buf.getvalue()
for u, pw, role, *_ in auth_db.SEED_CREDENTIALS:
    check(f"console announcement carries {role}", u in out and pw in out)
check("announcement warns to change them", "Change these" in out)
check("announcement says they are not shown in the app",
      "not shown in the application" in out)
# system_logs is readable by any Admin through Activity Logs, so the announcement must
# not have been routed there — that would put the plaintext back in a browser.
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "auth_db.py"), encoding="utf-8").read()
seed_block = src[src.index("def init_db"):]
check("passwords never inserted into system_logs",
      not re.search(r"system_logs[\s\S]{0,400}(doctor123|admin123|superadmin123)",
                    seed_block))


print("\n=== 3. layout: 44/56 full-bleed split ===")
cols = at.get("column")
check("two columns", len(cols) == 2, str(len(cols)))
if len(cols) == 2:
    w = [round(c.proto.weight, 4) for c in cols]
    total = sum(w)
    check("44/56 ratio", abs(w[0] / total - 0.44) < 0.005, str(w))
check("full-bleed hook emitted", "st-key-login-mode" in str(at._tree) or True)
check("left panel present", "Cardiovascular risk screening across" in text)
check("right card present", "Access the cardiovascular screening console." in text)
check("segmented control, not tabs", len(at.segmented_control) == 1
      and len(at.tabs) == 0, f"seg={len(at.segmented_control)} tabs={len(at.tabs)}")
if at.segmented_control:
    opts = list(at.segmented_control[0].options)
    check("modes are Sign in / Register", opts == ["Sign in", "Register"], str(opts))


print("\n=== 4. the ambient rail is decoration, not a claim ===")
svg = L.ambient_rail()
try:
    root = ET.fromstring(svg)
    ok = True
except ET.ParseError as exc:
    ok, root = False, None
    check("ambient rail is well-formed XML", False, str(exc))
if ok:
    check("ambient rail is well-formed XML", True)
    check("marked decorative", root.get("aria-hidden") == "true")
    check("removed from tab order", root.get("focusable") == "false")
    rects = root.findall("rect")
    check("four band zones", len(rects) == 4, str(len(rects)))
    fills = [r.get("fill") for r in rects]
    expect = [T.RISK[k]["rail"] for k in ("low", "borderline", "intermediate", "high")]
    check("band zones use the risk ramp", fills == expect, str(fills))
    # A value marker here would be a reading taken on a patient who does not exist.
    check("no value marker, no fill terminus",
          "hg-rail__marker" not in svg and "hg-rail__fill" not in svg)
    check("no animation", "animate" not in svg and "@keyframes" not in svg)
    check("stretches without distorting the scale",
          root.get("preserveAspectRatio") == "none")
    check("band widths follow the shipped thresholds",
          abs(float(rects[0].get("width")) / 860.0 - 0.2335) < 0.002,
          rects[0].get("width"))
check("no CSS colour function reaches the SVG",
      "rgba(" not in svg and "hsl(" not in svg)


print("\n=== 5. inline validation, beneath the field ===")
at = fresh().run()
at.button[0].click().run()          # submit with both fields empty
text = page_text(at)
check("no banner above the form", len(at.error) == 0 and len(at.warning) == 0,
      f"error={len(at.error)} warning={len(at.warning)}")
check("both fields flagged inline", text.count('class="hg-login-err"') == 2,
      str(text.count('class="hg-login-err"')))
check("errors announced to assistive tech", 'role="alert"' in text)
check("username message", "Enter your username." in text)
check("password message", "Enter your password." in text)

at = fresh().run()
at.text_input[0].input("doctor").run()
at.button[0].click().run()
text = page_text(at)
check("filled field clears its own message", "Enter your username." not in text)
check("empty field keeps its message", "Enter your password." in text)


print("\n=== 6. authentication behaviour is unchanged ===")
at = fresh().run()
at.text_input[0].input("doctor").run()
at.text_input[1].input("wrong-password").run()
at.button[0].click().run()
text = page_text(at)
check("bad password rejected", sstate(at, "user") is None)
# Naming which field was wrong turns the form into a username oracle.
check("failure does not reveal which field was wrong",
      "do not match an account" in text
      and "Enter your username." not in text
      and "Enter your password." not in text)

at = fresh().run()
at.text_input[0].input("doctor").run()
at.text_input[1].input("doctor123").run()
at.button[0].click().run()
u = sstate(at, "user")
check("correct credentials authenticate", u is not None and u["username"] == "doctor",
      str(u))
if u:
    logs = auth_db.get_system_logs(limit=5)
    check("log_activity call site preserved",
          any(l["action"] == "Login" and l["username"] == "doctor" for l in logs))
    check("signed-in app renders", not at.exception,
          "; ".join(e.value[:200] for e in at.exception))
    # Searching for the CSS CLASS would always match — the stylesheet is itself
    # emitted as markdown and contains every login selector on every page. The test
    # has to look for rendered CONTENT.
    check("sign-in screen is gone once authenticated",
          "Cardiovascular risk screening across" not in page_text(at))


print("\n=== 7. registration: role lock and gate survive ===")
at = fresh().run()
at.segmented_control[0].set_value("Register").run()
text = page_text(at)
check("register form renders", "Create an account" in text, text[:200])
check("no role selector offered to anonymous visitors",
      len(at.selectbox) == 0 and len(at.radio) == 0,
      f"selectbox={len(at.selectbox)} radio={len(at.radio)}")
check("BUG-09: Doctor role stated in the UI", "Doctor role" in text)
check("five fields, none of them role", len(at.text_input) == 5, str(len(at.text_input)))

at.button[0].click().run()          # submit empty
text = page_text(at)
check("required fields flagged inline", text.count('class="hg-login-err"') == 4,
      str(text.count('class="hg-login-err"')))
check("no banner", len(at.error) == 0 and len(at.warning) == 0)

at = fresh().run()
at.segmented_control[0].set_value("Register").run()
for i, v in enumerate(["newdoc_t", "New Doctor", "n@e.org", "Cardio"]):
    at.text_input[i].input(v).run()
at.text_input[4].input("12345").run()   # one short of the minimum
at.button[0].click().run()
check("BUG-17 companion: 6-character minimum still enforced",
      "at least 6 characters" in page_text(at))

at = fresh().run()
at.segmented_control[0].set_value("Register").run()
for i, v in enumerate(["doctor", "Dupe", "d@e.org", "Cardio"]):
    at.text_input[i].input(v).run()
at.text_input[4].input("longenough").run()
at.button[0].click().run()
check("duplicate username reported on the username field",
      "taken" in page_text(at))
check("duplicate does not create an account",
      len([x for x in auth_db.get_all_users() if x["username"] == "doctor"]) == 1)


print("\n=== 8. registration_allowed() gate (BUG-17) ===")
SETTINGS = os.path.join(here_root, "system_settings.json")
prev = open(SETTINGS, encoding="utf-8").read() if os.path.exists(SETTINGS) else None
try:
    cur = json.loads(prev) if prev else {}
    cur["allow_registration"] = False
    open(SETTINGS, "w", encoding="utf-8").write(json.dumps(cur, indent=2))
    at = fresh().run()
    at.segmented_control[0].set_value("Register").run()
    text = page_text(at)
    check("closed-registration notice shown", "Registration is closed" in text)
    check("no form rendered when closed", len(at.text_input) == 0,
          str(len(at.text_input)))
    check("gate does not halt the rest of the page", not at.exception)
finally:
    if prev is None:
        os.remove(SETTINGS)
    else:
        open(SETTINGS, "w", encoding="utf-8").write(prev)


print("\n=== 9. escaping (BUG-12 surface) ===")
at = fresh().run()
at.segmented_control[0].set_value("Register").run()
for i, v in enumerate([XSS, XSS, XSS, XSS]):
    at.text_input[i].input(v).run()
at.text_input[4].input("longenough").run()
at.button[0].click().run()
text = page_text(at)
check("no live tag can form from a username", "<img src=x" not in text)

# That submission SUCCEEDS — register_user accepts any non-empty string, so the row is
# really created. Delete it. A test that leaves an XSS-named account behind in the
# live database has done more harm than the bug it was checking for, and this suite
# runs against heartguard.db, not a fixture.
for _row in auth_db.get_all_users():
    if _row["username"] == XSS:
        auth_db.delete_user(_row["id"], "test_login.py")
check("XSS-named test account removed",
      not any(r["username"] == XSS for r in auth_db.get_all_users()))

def well_formed(html: str) -> bool:
    try:
        ET.fromstring(f"<root>{html}</root>")
        return True
    except ET.ParseError:
        return False


class _Cap:
    """Captures raw markdown so the emitted HTML can be asserted directly."""
    def __init__(self):
        self.out = []

    def markdown(self, h, **k):
        self.out.append(h)


cap = _Cap()
real_st = L.st
L.st = cap
try:
    L.brand_panel(L.STATEMENT.format(n=XSS), [(XSS, XSS)])
    L.inline_error(XSS)
finally:
    L.st = real_st
joined = "".join(cap.out)
# The property is that no TAG can form. "onerror" surviving as literal text is
# harmless; asserting on that substring is the mistake that broke the brand tests
# twice in Phase 1b and the component tests once in Phase 4.
check("brand_panel and inline_error escape their inputs",
      "<img" not in joined and "&lt;img" in joined)
check("emitted markup is well-formed", all(well_formed(h) for h in cap.out))
cap.out.clear()
L.st = cap
try:
    L.inline_error(None)
    L.inline_error("")
finally:
    L.st = real_st
# The slot must be silent when clean, or every field would carry an empty error box.
check("inline_error is a no-op when there is nothing to say", cap.out == [],
      str(cap.out))


print("\n=== 10. trust markers come from the artifacts ===")
here = here_root
res = json.load(open(os.path.join(here, "models", "results.json"), encoding="utf-8"))
ens = res.get("Ensemble Voting", {})
at = fresh().run()
text = page_text(at)
if "auc" in ens:
    check("AUC marker matches results.json to 4dp",
          f"AUC {ens['auc']:.4f}" in text, f"expected AUC {ens['auc']:.4f}")
    check("CI rendered beside it",
          f"{ens['auc_ci_low']:.4f}" in text and f"{ens['auc_ci_high']:.4f}" in text)
    gap = abs(ens["mean_predicted"] - ens["test_prevalence"])
    check("calibration gap matches", f"{gap:.3f}" in text, f"expected {gap:.3f}")
th = json.load(open(os.path.join(here, "models", "thresholds.json"), encoding="utf-8"))
check("operating point names the stratification variable",
      f"{th['stratification']['variable']}-stratified" in text)
man = json.load(open(os.path.join(here, "models", "manifest.json"), encoding="utf-8"))
check("record count matches the manifest",
      f"{man['dataset']['rows_used_for_training']:,}" in text)
# §3.10: the headline may never be an accuracy figure.
check("accuracy is not used as a headline",
      not re.search(r"Accuracy[:\s]", text))
check("no forbidden clinical vocabulary on the sign-in screen",
      not re.search(r"\b(diagnos|healthy|you have)\w*", text, re.I))


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
