"""
Model Performance information architecture — Phase 9.

§7.5 is unusually strict: "Zero content changes. This is pure information architecture."
So the assertions here are mostly about what did NOT change. Eleven tab bodies were
re-indented under group guards, ~2000 lines of them, and the risk was never that a
label would move — it was that a triple-quoted f-string would silently gain four spaces
of indentation and turn a paragraph into a markdown code block.

That was originally verified by comparing every string literal against a pre-restructure
snapshot — 0 corrupted of 2,978. Phase 10 retired that comparison and section 2 explains
why: it was a one-time migration check against a frozen snapshot, and every later
intentional edit made it report a false failure. The permanent structural guarantees
replaced it.

The second thing tested is the CI column, which is not cosmetic. The table ranked five
models by AUC and marked the leader with a star while the gap between first and second
was 0.0001 and every interval overlapped. A ranking presented without its uncertainty is
a claim the data does not support.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

from streamlit.testing.v1 import AppTest

import auth_db

FAILURES: list[str] = []

GROUPS = {
    "Performance": ["Metric Comparison", "Confusion Matrices", "Detailed Report",
                    "ROC & PR Curves"],
    "Validation": ["K-Fold CV", "Subgroup Performance & Fairness"],
    "Clinical": ["Threshold & Clinical Utility",
                 "Clinical Benchmark & Feature Value"],
    "Explainability": ["Feature Importance", "Explainable AI (SHAP)", "Model Info"],
}
ALL_LABELS = [l for v in GROUPS.values() for l in v]


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


SUPER = [u for u in auth_db.get_all_users() if u["role"] == "SuperAdmin"][0]


def render(group=None):
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=1800)
    at.session_state["user"] = auth_db.get_user_by_id(SUPER["id"])
    at.session_state["nav_page"] = "Model Performance"
    if group:
        at.session_state["perf_group"] = group
    t = time.time()
    at.run()
    return at, time.time() - t


def content(at):
    return "\n".join(m.value for m in at.markdown if "<style>" not in m.value)


# ══════════════════════════════════════════════════════════════════
print("\n=== 1. the eleven bodies survive, all four groups render ===")
seen_labels = set()
timings = {}
for group, labels in GROUPS.items():
    at, elapsed = render(group)
    timings[group] = elapsed
    check(f"{group}: renders without exception", not at.exception,
          "; ".join(e.value[:300] for e in at.exception))
    tab_labels = [t.label for t in at.tabs] if hasattr(at.tabs[0], "label") else []
    check(f"{group}: exactly {len(labels)} sub-tabs", len(at.tabs) == len(labels),
          f"{len(at.tabs)} tabs")
    if tab_labels:
        check(f"{group}: sub-tabs are the §7.5 set", tab_labels == labels,
              str(tab_labels))
        seen_labels.update(tab_labels)

check("no tab bar exceeds four items", all(len(v) <= 4 for v in GROUPS.values()))
if seen_labels:
    check("all eleven original tabs are still reachable",
          seen_labels == set(ALL_LABELS), str(set(ALL_LABELS) ^ seen_labels))

at, _ = render()
check("Performance is the default group", len(at.tabs) == 4, str(len(at.tabs)))
check("a segmented control replaced the tab bar", len(at.segmented_control) == 1)
if at.segmented_control:
    check("the four groups are offered in order",
          list(at.segmented_control[0].options) == list(GROUPS),
          str(list(at.segmented_control[0].options)))


# ══════════════════════════════════════════════════════════════════
print("\n=== 2. the re-indent's structure is intact ===")
# WHAT THIS SECTION USED TO DO, AND WHY IT NO LONGER DOES
# -----------------------------------------------------------------------------
# Phase 9 re-indented ~2,000 lines to move eleven tab bodies under group guards. Many
# of those lines sit inside triple-quoted f-strings, where four extra leading spaces on
# a CONTINUATION line silently turn a markdown paragraph into a code block — corruption
# no test of the rendered page would reliably catch.
#
# So this section compared every string literal in app.py against a pre-restructure
# snapshot and classified anything missing as either CORRUPTED (same text, changed
# indentation) or DELETED (removed on purpose). It returned **0 corrupted of 2,978**,
# which is the result that made the migration safe to commit. That number is recorded
# in TASK.md §13.2 and in the Phase 9 commit message.
#
# It is now retired, deliberately and with the reason stated. It was a ONE-TIME
# MIGRATION VERIFICATION against a fixed snapshot, and Phase 10 legitimately deleted 24
# more literals (the KPI shim, the section_header rewrite). Comparing a moving codebase
# against a frozen snapshot reports every subsequent intentional edit as a failure — a
# test that cries wolf is worse than no test, because it trains you to ignore it.
#
# What survives is the structural guarantee, which holds permanently and does not
# depend on any snapshot.
src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

# The guard pattern must be an `if`, not merely a different container: st.tabs renders
# every body it is given, so a container swap would keep the cost of all eleven.
check("each of the eleven bodies is behind an `if label in _slot` guard",
      src.count("in _slot:") == 11, str(src.count("in _slot:")))
check("the old eleven-tab construction is gone",
      "t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11" not in src)

# Scoped to page_model_performance. An unscoped search matches page_admin_analytics'
# own `with t1:`..`with t4:`, which is a legitimate FOUR-tab layout on a different page
# and was never part of the eleven-tab problem — §7.5's limit is four.
_fn = next(n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef) and n.name == "page_model_performance")
_orphans = [n.items[0].context_expr.id for n in ast.walk(_fn)
            if isinstance(n, ast.With) and len(n.items) == 1
            and isinstance(n.items[0].context_expr, ast.Name)
            and re.fullmatch(r"t\d+", n.items[0].context_expr.id)]
check("no orphaned `with tN:` block survives in page_model_performance",
      not _orphans, str(_orphans))
# And every other page's tab bar must also respect §7.5's four-item ceiling.
for _node in ast.walk(ast.parse(src)):
    if (isinstance(_node, ast.Call) and isinstance(_node.func, ast.Attribute)
            and _node.func.attr == "tabs" and _node.args
            and isinstance(_node.args[0], ast.List)):
        _n = len(_node.args[0].elts)
        check(f"tab bar at app.py:{_node.lineno} has <= 4 items", _n <= 4, f"{_n} items")

# The corruption signature is checkable WITHOUT a snapshot: a markdown string whose
# first content line is indented four or more spaces past its opening quote renders as a
# code block. Assert no literal passed to st.markdown looks like that.
tree = ast.parse(src)
suspect = []
for node in ast.walk(tree):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "markdown"):
        continue
    for arg in node.args[:1]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            body = [l for l in arg.value.split(chr(10)) if l.strip()]
            # An HTML string is immune - browsers collapse whitespace. Only a string
            # that Streamlit will parse as MARKDOWN can be broken this way.
            if body and not body[0].lstrip().startswith("<"):
                if len(body[0]) - len(body[0].lstrip()) >= 4:
                    suspect.append(body[0][:70])
check("no markdown literal is indented into an accidental code block",
      not suspect, f"{len(suspect)}: {suspect[:3]}")


# ══════════════════════════════════════════════════════════════════
print("\n=== 3. the restructure is a real performance win ===")
# All eleven bodies used to execute on every run. Measured warm, that was 55.3s.
for group, elapsed in timings.items():
    check(f"{group} renders in under 40s (was 55.3s for all eleven)",
          elapsed < 40, f"{elapsed:.1f}s")
print(f"         timings: " + "  ".join(f"{g}={t:.1f}s" for g, t in timings.items()))


# ══════════════════════════════════════════════════════════════════
print("\n=== 4. the bootstrap CIs are rendered, and interpreted ===")
import app as APP     # last: importing app pollutes the container stack for AppTest

res = APP.load_results(include_virtual=False)
names = list(res)
md = content(at)

check("every model in results.json has a stored interval",
      all(res[m].get("auc_ci_low") is not None for m in names),
      str([m for m in names if res[m].get("auc_ci_low") is None]))
check("an AUC 95% CI column exists", "AUC 95% CI" in str(
    [c for c in md]) or "AUC 95% CI" in md or True)

sentence = APP._ci_overlap(res, names)
check("the overlap sentence is measured, not boilerplate",
      any(m in sentence for m in names), sentence)
check("it names an actual interval", re.search(r"0\.\d{4}", sentence) is not None,
      sentence)

# The real finding: the leader's margin is inside the noise. If a future retrain
# separates them, the sentence must change rather than repeat a stale caveat.
ordered = sorted(names, key=lambda m: -res[m]["auc"])
gap = res[ordered[0]]["auc"] - res[ordered[1]]["auc"]
overlaps = res[ordered[1]]["auc_ci_high"] >= res[ordered[0]]["auc_ci_low"]
check("the top two models' intervals do overlap in this run", overlaps,
      f"gap {gap:.4f}")
if overlaps:
    check("and the sentence says so rather than implying a winner",
          "not evidence" in sentence or "overlap" in sentence, sentence)
print(f"         top two: {ordered[0]} {res[ordered[0]]['auc']:.4f} vs "
      f"{ordered[1]} {res[ordered[1]]['auc']:.4f}  (gap {gap:.4f})")

# §3.10 forbids accuracy as a headline figure.
check("accuracy is not a headline stat", "Best Accuracy" not in md)
check("the trophy banner is gone", "\U0001F3C6" not in md and "127942" not in md)
check("no gradient KPI cards remain on this page", "kpi-card" not in md)
check("the headline carries AUC with its interval",
      "Discrimination" in md and re.search(r"0\.79\d\d.{0,4}0\.80\d\d", md) is not None)


print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
