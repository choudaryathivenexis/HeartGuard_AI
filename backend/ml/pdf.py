"""
The multi-page clinical PDF.

Built with matplotlib's PdfPages rather than reportlab or fpdf: neither is installed,
matplotlib already is, and adding a PDF library for one feature would break
`pip install -r requirements.txt` on a marker's machine for no gain. The SHAP figure is
a matplotlib object already, so it embeds at vector quality instead of being rasterised.
"""

from __future__ import annotations

import io

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from . import charts as ucharts


# ════════════════════════════════════════════════════════════════════════
# PDF report
# ════════════════════════════════════════════════════════════════════════
def _pdf_text_page(pdf, title, lines, footer=None):
    # ALWAYS the light palette, never the viewer's. This page is printed on white A4:
    # a dark-mode user exporting a report would otherwise get near-white ink on a white
    # background — an unreadable file, produced silently, that they then hand to
    # someone else. `ucharts.color()` follows the viewer and is wrong here by
    # construction; `palette('light')` is pinned.
    p = ucharts.palette('light')
    fig = plt.figure(figsize=(8.27, 11.69), facecolor='white')   # A4 portrait
    fig.text(0.08, 0.955, "HeartGuard AI", fontsize=19, fontweight='bold',
             color=p['primary'])
    fig.text(0.08, 0.932, title, fontsize=11.5, color=p['fg_muted'])
    fig.text(0.08, 0.921, "_" * 92, fontsize=8, color=p['spine'])
    y = 0.885
    for line in lines:
        if line.startswith("## "):
            y -= 0.012
            fig.text(0.08, y, line[3:], fontsize=10.5, fontweight='bold',
                     color=p['ink'])
            y -= 0.019
        elif line == "---":
            fig.text(0.08, y + 0.004, "_" * 92, fontsize=8, color=p['grid'])
            y -= 0.016
        else:
            fig.text(0.08, y, line, fontsize=8.8, color=p['fg'],
                     family='DejaVu Sans')
            y -= 0.0163
        if y < 0.06:
            break
    if footer:
        fig.text(0.08, 0.032, footer, fontsize=7, color=p['fg_subtle'])
    pdf.savefig(fig, facecolor='white')
    plt.close(fig)


def build_pdf_report(meta, indicators, prediction, operating, reliability,
                     waterfall_fig=None, counterfactuals=None, percentile=None):
    """
    Multi-page clinical PDF, built with matplotlib's PdfPages.

    matplotlib rather than reportlab/fpdf deliberately: neither is installed, and
    matplotlib is already a hard dependency. Adding a PDF library for one feature
    would break `pip install -r requirements.txt` on a marker's machine for no gain,
    and the SHAP figure is a matplotlib object already — it embeds natively at vector
    quality instead of being rasterised.
    """
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        lines = [
            "## PATIENT",
            f"Patient ID        : {meta.get('patient_id', '')}",
            f"Patient Name      : {meta.get('patient_name', '')}",
            f"Assessment Date   : {meta.get('timestamp', '')}",
            f"Assessed By       : {meta.get('clinician', '')} ({meta.get('role', '')})",
            "---",
            "## CLINICAL INDICATORS",
        ]
        lines += [f"{k:<20}: {v}" for k, v in indicators.items()]
        lines += [
            "---",
            "## AI RISK ASSESSMENT",
            f"{'Model':<20}: {prediction.get('model', '')}",
            f"{'Model Version':<20}: {prediction.get('version', '')}",
            f"{'Risk Probability':<20}: {prediction.get('probability', 0):.2%}",
            f"{'Risk Band':<20}: {prediction.get('band', '')}",
            f"{'Recommendation':<20}: {prediction.get('action', '')}",
        ]
        if percentile:
            lines.append(f"{'Peer Comparison':<20}: higher than "
                         f"{percentile['pct']}% of patients ({percentile['label']})")
        lines += [
            "---",
            "## OPERATING POINT (age-stratified)",
            f"{'Age Band':<20}: {operating.get('band', '')}",
            f"{'Threshold':<20}: {operating.get('threshold', 0):.3f}",
            f"{'Sensitivity':<20}: {operating.get('sensitivity', 0):.1%}",
            f"{'Specificity':<20}: {operating.get('specificity', 0):.1%}",
            f"{'PPV / NPV':<20}: {operating.get('ppv', 0):.1%} / {operating.get('npv', 0):.1%}",
            "",
            "This threshold is tuned for SCREENING sensitivity, not diagnostic",
            "accuracy. It deliberately flags more patients for follow-up in order",
            "to reduce missed cases. A positive result indicates the need for",
            "further testing, NOT the presence of disease.",
        ]
        if reliability:
            lines += [
                "---",
                "## MODEL RELIABILITY FOR THIS PATIENT GROUP",
                f"{'Discrimination':<20}: AUC {reliability.get('auc', 0):.3f}"
                + (f" (95% CI {reliability['auc_ci_low']:.3f}-{reliability['auc_ci_high']:.3f})"
                   if reliability.get('auc_ci_low') is not None else ""),
                f"{'Calibration gap':<20}: {reliability.get('calibration_gap', 0):+.3f}",
                f"{'Measured on':<20}: {reliability.get('n', 0):,} held-out patients",
            ]
            if reliability.get("auc", 1) < 0.75:
                lines += ["",
                          "CAUTION: the model discriminates less well in this age band",
                          "than overall. Weight clinical judgement more heavily."]
        lines += [
            "---",
            "## NOTES",
            meta.get("notes", "") or "None",
        ]
        _pdf_text_page(
            pdf, "Cardiovascular Risk Assessment Report", lines,
            footer=("AI-generated clinical decision support. Not a diagnosis. "
                    "Final determination must be made by a licensed professional."))

        if waterfall_fig is not None:
            # Callers should build this with waterfall_figure(theme='light'), and
            # app.py does. This repaint stays as a safety net for any caller that
            # hands over a figure built for the screen: on white A4, dark-theme ink is
            # invisible, and the failure is silent — the PDF opens, the chart is blank.
            # It cannot recover the BAR colours, which is why the theme argument is the
            # real fix and this is only the backstop.
            p = ucharts.palette('light')
            waterfall_fig.patch.set_facecolor('white')
            for ax in waterfall_fig.get_axes():
                ax.set_facecolor('white')
                ax.title.set_color(p['ink'])
                ax.xaxis.label.set_color(p['fg_muted'])
                for t in ax.get_xticklabels() + ax.get_yticklabels():
                    t.set_color(p['fg_muted'])
                for txt in ax.texts:
                    txt.set_color(p['fg'])
            pdf.savefig(waterfall_fig, facecolor='white', bbox_inches='tight')

        if counterfactuals:
            cf_lines = ["## MODIFIABLE RISK FACTORS",
                        "Projected effect of each intervention on this patient's",
                        "risk score. Computed by re-scoring the model with the",
                        "indicated value changed; not a clinical guarantee.",
                        "",
                        f"{'Intervention':<34}{'New risk':>10}{'Change':>10}",
                        "-" * 54]
            for r in counterfactuals:
                cf_lines.append(f"{r['Intervention']:<34}{r['New risk']:>9.1%}"
                                f"{r['Change']:>+10.1%}")
            _pdf_text_page(pdf, "Care Planning — What-If Analysis", cf_lines)

        d = pdf.infodict()
        d["Title"] = f"HeartGuard Risk Assessment — {meta.get('patient_id', '')}"
        d["Author"] = meta.get("clinician", "HeartGuard AI")
        d["Subject"] = "Cardiovascular risk assessment (clinical decision support)"
        d["Creator"] = f"HeartGuard AI {prediction.get('version', '')}"

    buf.seek(0)
    return buf
