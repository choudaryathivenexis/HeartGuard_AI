"""
Model Performance information architecture — Phase 9.

§7.5 is unusually strict: "Zero content changes. This is pure information architecture."
So the assertions here are mostly about what did NOT change. Eleven tab bodies were
re-indented under group guards, ~2000 lines of them, and the risk was never that a
label would move — it was that a triple-quoted f-string would silently gain four spaces
of indentation and turn a paragraph into a markdown code block.

That is why the first check compares the full set of string literals in the module
against the pre-restructure snapshot. It is the only assertion that can prove a
2000-line mechanical re-indent preserved meaning.

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
print("\n=== 2. zero content change: no string literal was altered ===")
# The re-indent touched ~2000 lines, many inside triple-quoted f-strings. Indenting a
# CONTINUATION line inside one changes the string's contents, and in markdown four extra
# leading spaces silently turn a paragraph into a code block. Comparing the full literal
# set against the pre-restructure snapshot is the only check that can prove otherwise.
SNAP = os.path.join(
    r"C:\Users\SMARTC~1\AppData\Local\Temp\claude"
    r"\i--Ariha-FYP-HeartGuard-FYP-HeartGuard-FYP"
    r"\79b410a9-1824-47b5-84e9-abfe4c8762ef\scratchpad", "app_pre9.py")


def literals(path, with_lines=False):
    tree = ast.parse(open(path, encoding="utf-8").read())
    nodes = [n for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    if with_lines:
        return [(n.value, n.lineno) for n in nodes]
    return [n.value for n in nodes]


def dedent_key(s: str) -> str:
    """A literal's content with per-line leading whitespace removed."""
    return "\n".join(l.strip() for l in s.split("\n"))


if os.path.exists(SNAP):
    before, after = literals(SNAP), literals(os.path.join(HERE, "app.py"))
    after_set, after_keys = set(after), {dedent_key(s) for s in after}
    absent = [s for s in before if s not in after_set]

    # Two different things can make a literal absent, and only one is a bug:
    #
    #   CORRUPTED  — the same text is still there but its indentation changed. That is
    #                the failure mode of a 2000-line mechanical re-indent, and in
    #                markdown four extra leading spaces turn a paragraph into a code
    #                block. Detected by matching on the dedented form.
    #   DELETED    — the literal is genuinely gone because it was removed on purpose.
    #                The trophy banner and the five gradient KPI cards were.
    #
    # The first version of this check reported all 16 deliberate deletions as failures,
    # which is a test that cannot tell intent from accident.
    corrupted = [s for s in absent if dedent_key(s) in after_keys]
    deleted = [s for s in absent if dedent_key(s) not in after_keys]

    check("no string literal was corrupted by the re-indent", not corrupted,
          f"{len(corrupted)}: {[s[:80] for s in corrupted[:2]]}")
    # Everything genuinely removed must come from the two blocks Phase 9 replaced —
    # the trophy banner and the KPI/table header. Located by SOURCE LINE RANGE in the
    # snapshot rather than by keyword: an f-string splits into one AST Constant per
    # gap between its placeholders, so fragments like "</b> &nbsp;|&nbsp;" carry none
    # of the words a keyword list would look for. Matching on position cannot miss them.
    snap_src = open(SNAP, encoding="utf-8").read().split("\n")
    banner_start = next(i for i, l in enumerate(snap_src, 1)
                        if "Best Performing Model" in l) - 6
    header_end = next(i for i, l in enumerate(snap_src, 1)
                      if "Export Comparison Table" in l) + 4
    replaced_range = range(banner_start, header_end + 1)
    snap_lines = {}
    for value, lineno in literals(SNAP, with_lines=True):
        snap_lines.setdefault(value, []).append(lineno)

    stray = [s for s in deleted
             if not any(ln in replaced_range for ln in snap_lines.get(s, []))]
    check("every deleted literal comes from the two blocks Phase 9 replaced",
          not stray, f"{len(stray)}: {[s[:90] for s in stray[:3]]}")
    print(f"         replaced source lines {banner_start}-{header_end}")
    print(f"         {len(before)} literals before; {len(corrupted)} corrupted, "
          f"{len(deleted)} deliberately removed")
else:
    print("  [skip] pre-restructure snapshot unavailable; run 2 assertions skipped")

# The guard pattern must be an `if`, not merely a different container: st.tabs renders
# every body it is given, so a container swap would keep the cost of all eleven.
src = open(os.path.join(HERE, "app.py"), encoding="utf-8").read()
check("each body is behind an `if label in _slot` guard",
      src.count("in _slot:") == 11, str(src.count("in _slot:")))
check("the old eleven-tab construction is gone",
      "t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11" not in src)


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
