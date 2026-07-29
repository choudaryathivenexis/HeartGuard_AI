"""
The SHAP waterfall figure.

Takes an explicit `theme` rather than following a global. The PDF copy is printed on
white A4 and must be pinned to light: a figure drawn for a dark surface exports as
near-white on white — an unreadable file, produced silently, that a clinician then
hands to someone else.
"""

from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from . import charts as ucharts
from . import features as fe


def waterfall_figure(shap_row, base_value, feature_names, raw_values,
                     final_prob, top_n=10, unit="mg/dL", theme=None):
    """
    Per-patient SHAP waterfall: which of THIS patient's values drove THIS score.

    Contributions are in log-odds (the model's native output space); the probability is
    shown separately rather than implying the bars sum to it, which would be wrong.

    `theme` exists because this one figure has two destinations with opposite
    requirements. On screen it must follow the viewer, light or dark. Inside the PDF it
    is printed on white A4 and must ALWAYS be light — a dark-mode viewer exporting a
    report would otherwise get near-white ink on a white page, an invisible chart in a
    file they then hand to someone else. The PDF builder passes theme='light'; the
    screen passes nothing.
    """
    p = ucharts.palette(theme)
    order = np.argsort(np.abs(shap_row))[::-1][:top_n]
    labels, vals, contrib = [], [], []
    for i in order:
        name = feature_names[i]
        raw = raw_values[i]
        if name == "cholesterol":
            shown = fe.ordinal_labels_with_units("cholesterol", unit).get(
                int(raw), str(raw)).split(" (")[0]
        elif name == "gluc":
            shown = fe.ordinal_labels_with_units("gluc", unit).get(
                int(raw), str(raw)).split(" (")[0]
        elif name == "gender":
            shown = "Male" if int(raw) == 1 else "Female"
        elif name in ("smoke", "alco", "active", "high_risk_flag"):
            shown = "Yes" if int(raw) == 1 else "No"
        else:
            shown = f"{raw:g}"
        labels.append(f"{fe.label_for(name)} = {shown}")
        vals.append(raw)
        contrib.append(float(shap_row[i]))

    fig, ax = plt.subplots(figsize=(7.6, max(3.2, 0.42 * len(labels) + 1.1)),
                           facecolor='none')
    ax.set_facecolor('none')
    colors = [p['risk_high'] if c > 0 else p['primary'] for c in contrib]
    bars = ax.barh(labels[::-1], contrib[::-1], color=colors[::-1], height=0.62)
    ax.axvline(0, color=p['fg_muted'], lw=1.1)
    span = max(abs(min(contrib)), abs(max(contrib))) or 1.0
    for bar, c in zip(bars, contrib[::-1]):
        off = span * 0.035
        ax.text(bar.get_width() + (off if c > 0 else -off),
                bar.get_y() + bar.get_height() / 2,
                f"{c:+.3f}", va='center',
                ha='left' if c > 0 else 'right',
                color=p['fg'], fontsize=7.6, fontweight='700')
    ax.set_xlim(-span * 1.38, span * 1.38)
    # The axis label used to say "red increases, blue decreases". There is no blue in
    # the palette any more, and naming colours in a label is the wrong way to encode
    # direction regardless — it is unreadable to anyone who cannot separate the two.
    # The sign on every bar already carries it.
    ax.set_xlabel("Contribution to risk (log-odds) — positive raises, negative lowers",
                  color=p['fg_muted'], fontsize=8.4)
    ax.set_title(f"Why this patient scored {final_prob:.1%}",
                 color=p['fg'], fontsize=10, fontweight='700', pad=10)
    ax.tick_params(colors=p['fg_muted'], labelsize=8)
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_color(p['spine'])
    ax.grid(True, axis='x', color=p['grid'], ls='--', lw=0.5, alpha=0.9)
    ax.set_axisbelow(True)
    plt.tight_layout()
    return fig
