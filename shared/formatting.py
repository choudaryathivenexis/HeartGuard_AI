"""
HeartGuard AI — Formatters
==========================
Decimal discipline, enforced here rather than at each call site.

A clinical instrument that reports the same quantity to different precisions in
different places is not trustworthy. Before this module the codebase mixed `:.1%`,
`:.2%`, `:.3f` and `:.4f` for the same underlying values depending on which call site
you happened to be reading.

The contract:

    probability   1 decimal as a percentage      34.0%
    AUC           4 decimals                     0.8000
    sens/spec     3 decimals                     0.835
    counts        thousands-separated             13,729
    threshold     3 decimals                      0.371
    calibration   signed, 3 decimals             +0.011

`esc()` lives here too, so components can escape without importing from app.py.
Every user-controlled string interpolated into HTML must pass through it — that is
what closed BUG-12, and the redesign multiplies the number of interpolation sites.
"""

from __future__ import annotations

import html
from datetime import datetime

EM_DASH = "—"
EN_DASH = "–"


# ════════════════════════════════════════════════════════════════════════
# Escaping — the security primitive
# ════════════════════════════════════════════════════════════════════════
def esc(value) -> str:
    """
    Escape a user-controlled value for interpolation into HTML.

    Applies to anything that came from the database or a form: patient names, user
    names, emails, specialisations, notes, filter strings. BUG-12 was these values
    reaching `unsafe_allow_html` markup unescaped.
    """
    return html.escape(str(value if value is not None else ""))


# ════════════════════════════════════════════════════════════════════════
# Numbers
# ════════════════════════════════════════════════════════════════════════
def pct(value, decimals: int = 1) -> str:
    """Probability as a percentage. 0.3402 -> '34.0%'"""
    if value is None:
        return EM_DASH
    return f"{float(value) * 100:.{decimals}f}%"


def auc(value) -> str:
    """Discrimination, always 4 decimals. 0.8 -> '0.8000'"""
    if value is None:
        return EM_DASH
    return f"{float(value):.4f}"


def metric3(value) -> str:
    """Sensitivity / specificity / PPV / NPV, always 3 decimals."""
    if value is None:
        return EM_DASH
    return f"{float(value):.3f}"


def threshold(value) -> str:
    """Operating point, always 3 decimals."""
    if value is None:
        return EM_DASH
    return f"{float(value):.3f}"


def count(value) -> str:
    """Row counts, thousands-separated. 13729 -> '13,729'"""
    if value is None:
        return EM_DASH
    return f"{int(value):,}"


def signed(value, decimals: int = 3) -> str:
    """Calibration gaps and deltas, always signed. -0.005 -> '-0.005'"""
    if value is None:
        return EM_DASH
    return f"{float(value):+.{decimals}f}"


def signed_pct(value, decimals: int = 1) -> str:
    """Signed percentage change. -0.212 -> '-21.2%'"""
    if value is None:
        return EM_DASH
    return f"{float(value) * 100:+.{decimals}f}%"


def per_1000(value) -> str:
    """Missed cases per 1,000, no decimals."""
    if value is None:
        return EM_DASH
    return f"{float(value):.0f}"


def interval(lo, hi, formatter=auc) -> str:
    """
    95% confidence interval in the house style: '[0.7925–0.8072]'.

    En dash, not hyphen — a hyphen between two numbers reads as subtraction.
    Returns an empty string when either bound is missing, so call sites can
    concatenate unconditionally.
    """
    if lo is None or hi is None:
        return ""
    return f"[{formatter(lo)}{EN_DASH}{formatter(hi)}]"


def value_with_ci(value, lo, hi, formatter=auc) -> str:
    """'0.8000 [0.7925–0.8072]' — a point estimate is never shown bare."""
    base = formatter(value)
    ci = interval(lo, hi, formatter)
    return f"{base} {ci}".strip()


def ratio(numer, denom) -> str:
    """'1 in 6' phrasing for miss rates."""
    if not denom:
        return EM_DASH
    return f"1 in {max(1, round(float(denom) / max(float(numer), 1e-9)))}"


# ════════════════════════════════════════════════════════════════════════
# Dates & identifiers
# ════════════════════════════════════════════════════════════════════════
def timestamp(value, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value is None or value == "":
        return EM_DASH
    if isinstance(value, datetime):
        return value.strftime(fmt)
    s = str(value)
    for parse in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, parse).strftime(fmt)
        except ValueError:
            continue
    return s


def datestamp(value) -> str:
    return timestamp(value, "%Y-%m-%d")


def short_sha(value, length: int = 12) -> str:
    """Truncate a digest for display. Full value belongs in a tooltip."""
    if not value:
        return EM_DASH
    s = str(value)
    return s[:length] if len(s) > length else s


# ════════════════════════════════════════════════════════════════════════
# Clinical vocabulary — fixed, non-negotiable (§3.10)
# ════════════════════════════════════════════════════════════════════════
# A tool with 0.835 sensitivity misses roughly one diseased patient in six. Copy must
# never imply otherwise, and no visual treatment may make a "Low" verdict read as
# reassurance. These are the only permitted phrasings for a screening outcome.
BAND_ACTION = {
    "low":          "Below the action threshold. Routine review.",
    "borderline":   "Below the action threshold. Lifestyle advice and re-assessment advised.",
    "intermediate": "Above the action threshold. Further testing indicated.",
    "high":         "Above the action threshold. Further testing indicated without delay.",
}

RELIABILITY_RATING = (
    (0.80, "Strong"),
    (0.75, "Moderate"),
    (0.00, "Limited"),
)


def reliability_rating(auc_value) -> str:
    """'Strong' / 'Moderate' / 'Limited' — never 'Confidence: high'."""
    if auc_value is None:
        return "Unknown"
    for floor, label in RELIABILITY_RATING:
        if float(auc_value) >= floor:
            return label
    return "Limited"


def discrimination_phrase(band_label, auc_value, lo=None, hi=None) -> str:
    """
    'Discrimination in 55–59: Moderate (AUC 0.7298 [0.7120–0.7480])'

    The house phrasing for model reliability. Never 'Confidence: high' — that hides
    both the metric and its interval.
    """
    rating = reliability_rating(auc_value)
    ci = interval(lo, hi)
    tail = f" {ci}" if ci else ""
    return (f"Discrimination in {band_label}: {rating} "
            f"(AUC {auc(auc_value)}{tail})")


__all__ = [
    "esc", "pct", "auc", "metric3", "threshold", "count", "signed", "signed_pct",
    "per_1000", "interval", "value_with_ci", "ratio",
    "timestamp", "datestamp", "short_sha",
    "BAND_ACTION", "reliability_rating", "discrimination_phrase",
    "EM_DASH", "EN_DASH",
]
