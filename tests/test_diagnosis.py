"""
Diagnosis page tests — §7.3, the highest-stakes screen.

Two things are being tested and they are not the same thing.

THE FIRST is that the redesign changed nothing clinical. The page was restructured
substantially — the inputs left st.form, the result moved into session state, the
global importance chart was replaced by per-patient SHAP — and every one of those
changes is a chance to have silently altered what gets scored or what gets stored. So
the pipeline order is pinned, and the five out-of-distribution scenarios from Run 8 are
re-run against DATABASE CONTENTS, not rendered strings.

That distinction is the single most important lesson in this project's history. The
Run 7 verification of BUG-23 asserted only on UI text and PASSED — while the
`extrapolated` flag was being discarded before it reached the INSERT, because the
parameter had been added to add_prediction's signature but not to its SQL. A test that
checks what the user sees is not a test that the system recorded it.

THE SECOND is that the new presentation cannot mislead. §7.3 fixes a vertical priority
and §3.10 fixes the vocabulary, and both exist because a 64px probability is
authoritative-looking whether or not the model has ever seen a patient like this one.
So: the extrapolation banner must precede the verdict in DOCUMENT ORDER, negligible
counterfactuals must carry no direction, and the forbidden words must appear nowhere.
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import sqlite3
import warnings
import xml.etree.ElementTree as ET

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)

from streamlit.testing.v1 import AppTest

import auth_db
from ui import diagnosis as UD

FAILURES: list[str] = []
XSS = '<img src=x onerror="alert(1)">'
DB = os.path.join(HERE, "heartguard.db")
BACKUP = os.path.join(HERE, "heartguard.db.p6bak")


def check(name, cond, detail=""):
    if cond:
        print(f"  [ ok ] {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


DOCTOR = [u for u in auth_db.get_all_users() if u["role"] == "Doctor"][0]


def content(at) -> str:
    """
    Rendered markdown with the injected stylesheet removed.

    Getting this filter wrong invalidates almost every assertion below, and the first
    two attempts did:

      * filtering on `--hg-` also drops every component carrying an inline custom
        property, which is most of them including the verdict;
      * filtering on a leading `<style` misses it entirely, because inject() emits two
        <link rel=preconnect> tags first.

    The stylesheet defines a rule for every class this file searches for, so any
    version of this filter that lets it through turns `"hg-peer--void" in md` into a
    constant True. Match on the tag appearing anywhere in the block.
    """
    return "\n".join(m.value for m in at.markdown if "<style>" not in m.value)


def fresh():
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=900)
    at.session_state["user"] = auth_db.get_user_by_id(DOCTOR["id"])
    at.session_state["nav_page"] = "Heart Disease Prediction"
    return at.run()


def fill(at, pid, name, *, age=52, h=165, w=70.0, sbp=120, dbp=80, submit=True):
    at.text_input[0].input(pid).run()
    at.text_input[1].input(name).run()
    at.number_input[0].set_value(age).run()
    at.number_input[1].set_value(h).run()
    at.number_input[2].set_value(float(w)).run()
    at.number_input[3].set_value(sbp).run()
    at.number_input[4].set_value(dbp).run()
    if submit:
        at.button[0].click().run()
    return at


def rows_for(name_like):
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM predictions WHERE patient_name LIKE ? ORDER BY id",
                  (name_like,)).fetchall()
    c.close()
    return r


shutil.copy(DB, BACKUP)
try:
    # ══════════════════════════════════════════════════════════════
    print("\n=== 1. structure: 58/42, four panels, eleven indicators ===")
    at = fresh()
    check("renders without exception", not at.exception,
          "; ".join(e.value[:300] for e in at.exception))
    # at.get("column") is a flat, tree-ordered list, so it includes the two-up columns
    # inside each input panel. Find the outer pair by weight rather than by position.
    weights = [round(c.proto.weight, 4) for c in at.get("column")]
    check("58/42 split present", {0.58, 0.42} <= set(weights), str(sorted(set(weights))))

    md = content(at)
    for panel in ("Patient", "Demographics", "Vitals", "Laboratory", "Lifestyle"):
        check(f"{panel} panel present", f">{panel}<" in md, panel)

    labels = [n.label for n in at.number_input] + [s.label for s in at.selectbox]
    check("eleven clinical indicators", len(labels) == 12,   # 11 + scoring model
          str(len(labels)))
    check("supported-range tooltip retained on every numeric input",
          all(n.help for n in at.number_input),
          str([n.label for n in at.number_input if not n.help]))
    check("empty state, not a hotlinked image", "No assessment yet" in md)
    # The old empty state hotlinked a Wikimedia PNG, which breaks on any machine
    # without internet and violates the vendor-don't-hotlink rule. Checking for
    # "http://" outright would false-positive on every SVG xmlns.
    check("no external image hotlink",
          "upload.wikimedia.org" not in md and not at.get("imgs"),
          "wikimedia" if "upload.wikimedia.org" in md else "st.image present")

    # ══════════════════════════════════════════════════════════════
    print("\n=== 2. applicability rails are live and above the submit ===")
    check("expander present and directly above submit",
          any("applicability" in e.label.lower() for e in at.expander))
    check("one rail per constrained feature",
          md.count("hg-rail--env") == len(UD.CONSTRAINED_FEATURES),
          f"{md.count('hg-rail--env')} vs {len(UD.CONSTRAINED_FEATURES)}")

    # The marker must MOVE as the clinician types. This is the property that made
    # leaving st.form necessary; if it fails, the rails are lying about the patient.
    at2 = fresh()
    before = re.findall(r'hg-rail__marker[^"]*" style="left:([\d.]+)%', content(at2))
    at2.number_input[0].set_value(64).run()          # age 45 -> 64
    after = re.findall(r'hg-rail__marker[^"]*" style="left:([\d.]+)%', content(at2))
    check("marker tracks the input before submit", before and before != after,
          f"{before[:2]} -> {after[:2]}")

    # An out-of-envelope value must be visibly outside, not clamped to the edge.
    at3 = fresh()
    at3.number_input[3].set_value(245).run()          # systolic beyond max 240
    check("out-of-range value marked as extrapolation on the rail",
          "extrapolat" in content(at3).lower())

    # ══════════════════════════════════════════════════════════════
    print("\n=== 3. the five OOD scenarios, asserted on the DATABASE ===")
    # age, sbp, dbp, expect_hard_extrapolation, expect_peer, label
    CASES = [
        (82, 150, 88, True,  False, "82yo — above age support"),
        (19, 110, 70, True,  False, "19yo — below age support"),
        (55, 245, 195, True, False, "55yo BP 245/195 — beyond BP support"),
        (52, 132, 84, False, True,  "52yo typical — fully supported"),
        (64, 138, 86, False, True,  "64yo — inside support, near p99"),
    ]
    for i, (age, sbp, dbp, exp_hard, exp_peer, label) in enumerate(CASES):
        at = fill(fresh(), f"PT-P6OOD-{i}", f"P6 OOD {i}",
                  age=age, sbp=sbp, dbp=dbp)
        md = content(at)
        banner = "Outside model applicability" in md
        withheld = "hg-peer--void" in md
        shown = "hg-peer" in md and not withheld
        ok = (banner == exp_hard and withheld == exp_hard and shown == exp_peer
              and not at.exception)
        check(f"UI — {label}", ok,
              f"banner={banner} withheld={withheld} shown={shown} "
              f"exc={len(at.exception)}")

    print()
    for i, (age, sbp, dbp, exp_hard, _, label) in enumerate(CASES):
        r = rows_for(f"P6 OOD {i}")
        if len(r) != 1:
            check(f"DB — {label}: exactly one row", False, f"{len(r)} rows")
            continue
        row = r[0]
        check(f"DB — {label}: extrapolated={int(exp_hard)}",
              bool(row["extrapolated"]) == exp_hard,
              f"stored {row['extrapolated']}")
        if exp_hard:
            check(f"DB — {label}: applicability_notes recorded",
                  bool(row["applicability_notes"]), "empty")
        check(f"DB — {label}: model_version stamped",
              bool(row["model_version"]), "empty")
        check(f"DB — {label}: threshold_used stamped",
              row["threshold_used"] is not None and row["threshold_used"] > 0,
              str(row["threshold_used"]))
        check(f"DB — {label}: risk_band stamped", bool(row["risk_band"]), "empty")
        check(f"DB — {label}: linked to a patient entity",
              row["patient_ref"] is not None, "unlinked")

    # ══════════════════════════════════════════════════════════════
    print("\n=== 4. one row per submit, none per re-render ===")
    at = fill(fresh(), "PT-P6-ONCE", "P6 Once Only")
    n1 = len(rows_for("P6 Once Only"))
    check("submit writes exactly one row", n1 == 1, str(n1))
    # The result now lives in session state and redraws on every keystroke. If the
    # redraw path could rescore, this is where a second row would appear.
    at.number_input[0].set_value(53).run()
    at.number_input[2].set_value(71.0).run()
    n2 = len(rows_for("P6 Once Only"))
    check("editing an input after submit writes no further row", n2 == 1, str(n2))
    check("the previous result stays on screen while editing",
          "Screening result" in content(at))

    # ══════════════════════════════════════════════════════════════
    print("\n=== 5. physiology refusal (BUG-26) ===")
    at = fill(fresh(), "PT-P6-PHYS", "P6 Implausible", sbp=90, dbp=180)
    md = content(at)
    check("refused, not scored", "not scored" in md.lower(), md[:200])
    check("no probability rendered", "hg-verdict__prob" not in md)
    check("nothing written to the database", len(rows_for("P6 Implausible")) == 0,
          str(len(rows_for("P6 Implausible"))))

    at = fill(fresh(), "", "")
    check("missing identification refuses without scoring",
          "required" in content(at).lower()
          and "hg-verdict__prob" not in content(at))

    # ══════════════════════════════════════════════════════════════
    print("\n=== 6. strict vertical priority (§7.3) ===")
    at = fill(fresh(), "PT-P6-ORD", "P6 Order", age=82, sbp=150, dbp=88)
    md = content(at)
    i_banner = md.find("Outside model applicability")
    i_verdict = md.find("hg-verdict__prob")
    i_op = md.find("hg-op")
    i_rel = md.find("hg-rel")
    check("extrapolation banner precedes the verdict",
          0 <= i_banner < i_verdict, f"banner@{i_banner} verdict@{i_verdict}")
    check("verdict precedes the operating point",
          0 <= i_verdict < i_op, f"verdict@{i_verdict} op@{i_op}")
    check("operating point precedes reliability",
          0 <= i_op < i_rel or i_rel < 0, f"op@{i_op} rel@{i_rel}")
    check("banner is not inside an expander",
          all("applicab" not in e.label.lower() or "Outside" not in str(e)
              for e in at.expander))
    check("peer comparison withheld with a reason", "hg-peer--void" in md)
    check("verdict carries the extrapolated marking",
          "extrapolat" in md[i_verdict:i_verdict + 1200].lower())

    # ══════════════════════════════════════════════════════════════
    print("\n=== 7. clinical vocabulary (§3.10) ===")
    # Kept under its own name: sections 8-10 and 13 all assert against this run, and
    # `at` is reassigned by the XSS run in section 11.
    at_ok = at = fill(fresh(), "PT-P6-VOCAB", "P6 Vocabulary")
    md = content(at)
    text = re.sub(r"<[^>]+>", " ", md)
    for word in ("diagnosis", "you have", "healthy", "disease present"):
        check(f"never says {word!r}", word not in text.lower(),
              text[max(0, text.lower().find(word) - 60):][:140])
    check("says 'Screening result'", "Screening result" in md)
    check("accuracy is not a headline", not re.search(r"Accuracy[:\s]*\d", text))

    # ══════════════════════════════════════════════════════════════
    print("\n=== 8. SHAP replaces the global importance chart ===")
    res = at.session_state["diag_result"]
    check("per-patient SHAP computed", res["shap"] is not None,
          str(res.get("shap_error")))
    check("caption is 'Contributions for this patient'",
          "Contributions for this patient" in md)
    check("old caption gone", "Top Risk Factors" not in md)
    check("log-odds stated, not implied to sum to the probability",
          "log-odds" in md and "do not sum" in md)
    if res["explainer_surrogate"]:
        check("surrogate explainer disclosed",
              "surrogate" in md and (res["explainer"] or "") in md,
              f"explainer={res['explainer']}")

    # ══════════════════════════════════════════════════════════════
    print("\n=== 9. counterfactuals route through the monotonic model ===")
    check("scored on XGBoost, not the ensemble", res["cf_model"] == "XGBoost",
          str(res["cf_model"]))
    check("panel names the constrained model in its footnote",
          "monotonically constrained" in md and "not the ensemble" in md)
    rows = res.get("counterfactuals") or []
    check("counterfactual rows produced", len(rows) > 0, str(len(rows)))
    # The engine classifies sub-noise changes as negligible; the UI must then show NO
    # direction. A signed delta beside "no material change" reads as a reason to act.
    neg = [r for r in rows if r["Verdict"] == "negligible"]
    if neg:
        blocks = re.findall(r'<div class="hg-cf__row[^"]*">(.*?)</div>\s*(?=<div class="hg-cf)',
                            md, re.S)
        none_rows = [b for b in re.findall(r'hg-cf__row hg-cf--none.*?</span></div>',
                                           md, re.S)]
        check("negligible rows carry no signed delta",
              all("+" not in b.split("hg-cf__delta")[1].split("</span>")[0]
                  and "−" not in b.split("hg-cf__delta")[1].split("</span>")[0]
                  for b in none_rows if "hg-cf__delta" in b),
              str(none_rows)[:200])
        check("negligible rows say 'no material change'",
              all("no material change" in b for b in none_rows))
    para = [r for r in rows if r["Verdict"] == "paradoxical"]
    if para:
        check("paradoxical rows framed as a model limitation, never advice",
              "model limitation" in md and "not advice" in md)

    # ══════════════════════════════════════════════════════════════
    print("\n=== 10. downloads are offered ===")
    dls = [d.label for d in at.get("download_button")]
    check("plain-text report offered", any(".txt" in d for d in dls), str(dls))
    check("PDF report offered", any("PDF" in d for d in dls), str(dls))
    check("no disabled PDF button", not [b for b in at.button if "PDF" in b.label],
          str([b.label for b in at.button if "PDF" in b.label]))

    # ══════════════════════════════════════════════════════════════
    print("\n=== 11. escaping (BUG-12) ===")
    at = fill(fresh(), XSS, XSS)
    md = content(at)
    check("no live tag can form from patient identifiers", "<img src=x" not in md)
    check("payload arrived and was escaped", "&lt;img" in md or "&amp;lt;" in md)
    # Component-level: feed the payload straight into every diagnosis renderer.
    out = "".join([
        UD.counterfactual_panel(
            [{"Intervention": XSS, "New risk": 0.3, "Change": -0.05,
              "Verdict": "benefit"}], 0.4, 0.35, XSS),
        UD.model_breakdown({XSS: 0.5}, {XSS: 1}, {XSS: 0.35}),
        UD.explainer_disclosure(XSS, XSS, True),
        UD.peer_percentile(50, XSS, 100),
        UD.peer_withheld(),
    ])
    check("diagnosis renderers escape their inputs",
          "<img" not in out and "&lt;img" in out)
    try:
        ET.fromstring(f"<root>{out}</root>")
        check("diagnosis markup is well-formed", True)
    except ET.ParseError as exc:
        check("diagnosis markup is well-formed", False, str(exc))

    # ══════════════════════════════════════════════════════════════
    print("\n=== 12. no CSS colour function reaches matplotlib ===")
    from ui import charts as CH
    from ui import tokens as T
    for theme in ("light", "dark"):
        p = CH.palette(theme)
        bad = {k: v for k, v in p.items() if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v)}
        check(f"{theme} palette is pure hex", not bad, str(bad))
    check("unknown series falls back rather than colliding",
          CH.series_color("Not A Model") == CH.palette()["reference"])
    check("known series keyed by name, not position",
          CH.series_color("XGBoost") == T.SERIES["XGBoost"])

    # ══════════════════════════════════════════════════════════════
    print("\n=== 13. exported records ===")
    # An extrapolated assessment must carry its warning into the exported file — the
    # file outlives the screen, and a report without the caveat is the artefact that
    # ends up in a patient's notes.
    at_ex = fill(fresh(), "PT-P6-EXDL", "P6 Export Extrap", age=82, sbp=150, dbp=88)
    res_ex = at_ex.session_state["diag_result"]
    res_ok = at_ok.session_state["diag_result"]

    # ─────────────────────────────────────────────────────────────
    # LAST, AND ONLY ONCE: `import app` executes the page body in a bare context,
    # which leaves Streamlit's dg_stack pointing inside a container that never
    # closed. Every AppTest run afterwards fails with "st.button() can't be used in
    # an st.form()" — an error that looks exactly like a product bug and is not one.
    # Every AppTest interaction above must therefore be complete before this line.
    # ─────────────────────────────────────────────────────────────
    import app as APP
    doc = auth_db.get_user_by_id(DOCTOR["id"])

    body = APP._text_report(res_ok, doc)
    check("text report keeps the screening-not-diagnosis sentence",
          "indicates the need for further testing, not disease" in body)
    check("text report discloses the operating point",
          "OPERATING POINT" in body and "Decision threshold" in body)
    check("text report names the model version that produced it",
          res_ok["version"]["version"] in body)
    check("text report states the risk band", res_ok["band_label"] in body)

    pdf, err = APP._pdf_report(res_ok, doc)
    check("PDF generates without error", pdf is not None, str(err))
    if pdf is not None:
        raw = pdf.getvalue() if hasattr(pdf, "getvalue") else pdf
        check("PDF is a real PDF", raw[:4] == b"%PDF", str(raw[:8]))
        check("PDF is substantial, not a stub", len(raw) > 20_000, str(len(raw)))

    body_ex = APP._text_report(res_ex, doc)
    check("extrapolated text report carries the warning",
          "OUTSIDE MODEL APPLICABILITY" in body_ex and "EXTRAPOLATION" in body_ex)
    check("extrapolated text report records the peer suppression",
          "withheld" in body_ex.lower())
    pdf_ex, err_ex = APP._pdf_report(res_ex, doc)
    check("extrapolated PDF still generates", pdf_ex is not None, str(err_ex))

finally:
    # Remove every row this suite created, then restore. The suite runs against the
    # live database, not a fixture; Phase 5 shipped a test that left an XSS-named
    # account behind and that must not become a habit.
    try:
        c = sqlite3.connect(DB)
        c.execute("DELETE FROM predictions WHERE patient_name LIKE 'P6 %' "
                  "OR patient_name LIKE ?", (XSS,))
        c.execute("DELETE FROM patients WHERE patient_code LIKE 'PT-P6%' "
                  "OR patient_code LIKE ?", (XSS,))
        c.commit()
        c.close()
    finally:
        if os.path.exists(BACKUP):
            os.remove(BACKUP)

print("\n" + "=" * 66)
print(f"FAILURES: {len(FAILURES)}")
for f in FAILURES:
    print("  ", f)
sys.exit(1 if FAILURES else 0)
