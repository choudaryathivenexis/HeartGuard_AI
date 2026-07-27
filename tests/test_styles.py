"""
The stylesheet's DELIVERY contract.

This file exists because of a bug that every other suite was blind to, and that is worth
stating plainly: the entire stylesheet was being rendered onto the login page as
thousands of lines of visible text. The app looked like it was dumping errors. It was not
— it was printing its own CSS as prose.

TWO CAUSES, BOTH MINE
    1. `st.markdown` runs its argument through a Markdown parser before the HTML reaches
       the page, and Markdown turns any line indented four or more spaces into a code
       block. 223 lines of the stylesheet were indented that far, so the parser cut out
       of the <style> element partway down and emitted the rest as text.
    2. Phase 10's `_legacy_block()` rewrite was written with FOUR braces (`{{{{`) through
       a shell heredoc, so the f-string collapsed them to `{{` in the output instead of
       `{`. Twelve rules shipped as invalid CSS.

WHY NOTHING CAUGHT IT
    Every check I had asked the wrong question.
      * AppTest sees a markdown element and reports success whether its content renders
        as a stylesheet or as prose. It does not render CSS at all.
      * My brace-balance check counted `{` against `}` — and `{{ … }}` balances
        perfectly. Balance is not validity.
      * My "key selectors present" check passed too, because `.panel {{` still contains
        `.panel`.
    A test that confirms a string is present says nothing about whether the browser can
    use it. These assertions target the delivery mechanism and the payload's validity,
    which is where the failure actually lived.
"""

from __future__ import annotations

import inspect
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

import streamlit as st

from ui import styles as S

FAILURES: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


css = S.stylesheet.__wrapped__()
lines = css.split("\n")


print("=== 1. the payload cannot be mangled by a Markdown parser ===")
# The exact failure mode. Four spaces of indentation is a code block in every Markdown
# implementation, so no line may start with whitespace.
indented = [l for l in lines if l[:1] in (" ", "\t")]
check("no line begins with whitespace", not indented,
      f"{len(indented)} indented lines, e.g. {indented[:2]}")
check("no blank lines (they terminate raw-HTML passthrough)",
      not [l for l in lines if not l.strip()])
# A Markdown list marker is the character FOLLOWED BY A SPACE. Requiring the space
# matters: with indentation stripped, `--hg-border: #D8DDE4;` starts with `-` and
# `* { box-shadow: none; }` starts with `*`, and both are perfectly ordinary CSS. The
# first version of this check rejected them and reported a failure with an empty detail
# string, which is how I noticed it was wrong rather than the stylesheet.
md_risk = [l for l in lines
           if re.match(r"(?:[-*+>#]\s|```|~~~|\d+\.\s)", l)]
check("no line would parse as a Markdown block", not md_risk,
      str([l[:50] for l in md_risk[:3]]))


print("\n=== 2. the payload is valid CSS, not merely balanced ===")
# `{{ … }}` balances and still breaks every rule it wraps. Balance is not validity.
check("no literal doubled braces", not re.findall(r"\{\{|\}\}", css),
      str(len(re.findall(r"\{\{|\}\}", css))))
check("braces balance", css.count("{") == css.count("}"),
      f"{css.count('{')} open, {css.count('}')} close")
check("no unresolved f-string placeholder survived",
      not re.findall(r"\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}", css),
      str(re.findall(r"\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}", css)[:3]))
check("@import is the first rule, or browsers drop it",
      css.lstrip().startswith("@import"))
check("no CSS colour function leaked where a hex belongs",
      "var(--hg-undefined" not in css)

# Every declaration block must contain at least one `prop: value;`. An empty or broken
# block is the signature of a mangled rule.
blocks = re.findall(r"\{([^{}]*)\}", css)
empty = [b for b in blocks if b.strip() and ":" not in b]
check("every declaration block contains a declaration", not empty,
      f"{len(empty)}: {[b[:50] for b in empty[:2]]}")

# Selector sanity: nothing should start with a stray brace or digit.
selectors = re.findall(r"(?:^|\}|\*/)\s*([^{}@/][^{}]{0,120}?)\s*\{", css)
bad_sel = [s for s in selectors if s.strip().startswith(("{", "}"))]
check("no malformed selectors", not bad_sel, str(bad_sel[:3]))


print("\n=== 2b. every block is individually well-formed ===")
# Checked per block, not just on the assembled sheet, because the assembled check tells
# you something is wrong and this one tells you WHERE. Both of Phase 10's escaping bugs
# lived in a single block; with only a whole-sheet assertion I would have been grepping
# 45 KB to find them.
PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_.\[\]'\"]*\}")
for name in sorted(n for n in dir(S) if n.startswith("_") and n.endswith("_block")):
    try:
        out = getattr(S, name)()
    except Exception as exc:
        check(f"{name} builds", False, f"{type(exc).__name__}: {exc}")
        continue
    issues = []
    if re.search(r"\{\{|\}\}", out):
        issues.append("literal doubled braces — an f-string needs exactly two to emit one")
    if PLACEHOLDER.search(out):
        issues.append(f"unresolved placeholder {PLACEHOLDER.search(out).group(0)}")
    if out.count("{") != out.count("}"):
        issues.append(f"unbalanced ({out.count('{')} vs {out.count('}')})")
    check(f"{name} is well-formed", not issues, "; ".join(issues))


print("\n=== 3. the delivery mechanism does not Markdown-process ===")
src = inspect.getsource(S.inject)
check("inject() uses st.html", "st.html(" in src)
check("st.html exists in this Streamlit version", hasattr(st, "html"))
check("inject() keeps a markdown fallback for older Streamlit",
      "st.markdown(" in src and "hasattr(st" in src)
check("the <style> wrapper is present", "<style>" in src)
check("font preconnect ships with it", "preconnect" in src)

# And prove it end to end: after a real run, no markdown element may carry the sheet.
import warnings
warnings.filterwarnings("ignore")
from streamlit.testing.v1 import AppTest
import auth_db

doctor = [u for u in auth_db.get_all_users() if u["role"] == "Doctor"][0]
at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=900)
at.session_state["user"] = auth_db.get_user_by_id(doctor["id"])
at.session_state["nav_page"] = "Dashboard"
at.run()
check("the signed-in page renders", not at.exception,
      "; ".join(e.value[:200] for e in at.exception))
leaked = [m.value for m in at.markdown
          if "<style>" in m.value or "--hg-border:" in m.value or "}\n." in m.value]
check("NO markdown element carries the stylesheet", not leaked,
      f"{len(leaked)} leaked, first starts {leaked[0][:60] if leaked else ''}")

# The login page is where the failure was visible, so check it specifically.
at2 = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=900).run()
check("the sign-in page renders", not at2.exception,
      "; ".join(e.value[:200] for e in at2.exception))
leaked2 = [m.value for m in at2.markdown if "--hg-" in m.value and "{" in m.value
           and "var(--hg-" not in m.value]
check("the sign-in page emits no raw CSS as markdown", not leaked2,
      f"{len(leaked2)} leaked")


print("\n=== 4. budget and scoping ===")
kb = len(css.encode()) / 1024
check(f"under the 60 KB budget ({kb:.1f} KB)", kb < 60, f"{kb:.1f} KB")
check("no .st-emotion-cache-* selectors", "st-emotion-cache" not in css)
check("data URIs survived minification", css.count("data:image") == 18,
      str(css.count("data:image")))
check("both themes are emitted", "--hg-surface" in css and "prefers-color-scheme" in css)

# Cheap smoke test that the sheet still contains what the phases built.
for sel in (".hg-verdict", ".hg-rail__track", ".hg-cf__row", ".hg-stat-grid",
            ".hg-login-brand", ".hg-danger", ".hg-peer", ".hg-alert--extrapolation",
            ".panel", ".alert-info"):
    check(f"{sel} is defined", re.search(re.escape(sel) + r"\s*[,{]", css) is not None)


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
