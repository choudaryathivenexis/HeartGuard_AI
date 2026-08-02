"""
Assessments: writing a score, reading them back, and recording the confirmed outcome.

Every row stores the model version and the threshold that produced it. Without those,
retraining silently invalidates the interpretation of every historical assessment — the
number survives but the model that produced it is gone, so the record cannot be
explained or audited afterwards.
"""

from __future__ import annotations

from .audit import log_activity
from .connection import connect, insert_returning_id


# ─────────────────────────────────────────────
# Predictions
# ─────────────────────────────────────────────
def add_prediction(user_id, age, gender, height, weight, ap_hi, ap_lo,
                   cholesterol, gluc, smoke, alco, active,
                   predicted_class, probability, model_used,
                   patient_name="", notes="",
                   patient_ref=None, model_version="", model_manifest_sha="",
                   threshold_used=None, risk_band="",
                   extrapolated=0, applicability_notes=""):
    """
    Persist an assessment.

    Run 7 additions make the record self-describing: it now carries the patient it
    belongs to, the exact model version that produced it, and the operating point in
    force at the time. Without those, a retrained model silently invalidates the
    interpretation of every historical row.
    """
    conn = connect()
    c = conn.cursor()
    pid = insert_returning_id(c, """
        INSERT INTO predictions
        (user_id,age,gender,height,weight,ap_hi,ap_lo,cholesterol,gluc,
        smoke,alco,active,predicted_class,probability,model_used,patient_name,notes,
        patient_ref,model_version,model_manifest_sha,threshold_used,risk_band,
        extrapolated,applicability_notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (user_id, age, gender, height, weight, ap_hi, ap_lo,
          cholesterol, gluc, smoke, alco, active,
          predicted_class, probability, model_used, patient_name, notes,
          patient_ref, model_version, model_manifest_sha, threshold_used, risk_band,
          int(extrapolated), applicability_notes))
    conn.commit()
    c.execute("SELECT username FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    uname = row[0] if row else "unknown"
    log_activity(user_id, uname, "Prediction",
                 f"Risk={predicted_class} ({probability:.2%}) via {model_used}.")
    conn.close()
    return pid


def get_predictions(user_id=None):
    conn = connect()
    c = conn.cursor()
    if user_id:
        c.execute("SELECT * FROM predictions WHERE user_id=? ORDER BY timestamp DESC", (user_id,))
    else:
        c.execute("""
            SELECT p.*, u.fullname as doctor_name, u.username as doctor_username
            FROM predictions p JOIN users u ON p.user_id=u.id
            ORDER BY p.timestamp DESC
        """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def delete_prediction(pred_id, operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM predictions WHERE id=?", (pred_id,))
    conn.commit()
    log_activity(None, operator_username, "Delete Prediction", f"Prediction ID {pred_id} removed.")
    conn.close()


def clear_all_predictions(operator_username):
    conn = connect()
    c = conn.cursor()
    c.execute("DELETE FROM predictions")
    conn.commit()
    log_activity(None, operator_username, "Clear Predictions", "All predictions purged.")
    conn.close()


# ─────────────────────────────────────────────
# Outcome capture & drift monitoring  (Run 7)
# ─────────────────────────────────────────────
def record_outcome(pred_id, outcome, notes, operator_username):
    """
    Record whether a prediction was clinically confirmed.

    This single field is what turns a one-shot calculator into a monitored system:
    without ground truth arriving back, model drift is undetectable and the deployed
    performance is forever assumed rather than measured.
    """
    conn = connect()
    c = conn.cursor()
    c.execute("""UPDATE predictions
                 SET outcome=?, outcome_notes=?, outcome_by=?,
                     outcome_at=CURRENT_TIMESTAMP
                 WHERE id=?""", (outcome, notes, operator_username, pred_id))
    conn.commit()
    log_activity(None, operator_username, "Outcome Recorded",
                 f"Prediction {pred_id} outcome set to "
                 f"{'confirmed' if outcome == 1 else 'not confirmed'}.")
    conn.close()


def get_outcome_stats():
    """
    Deployed-performance summary over predictions with confirmed outcomes.

    Deliberately returns raw counts alongside derived rates: with a small number of
    recorded outcomes the rates are noise, and the caller needs to know that rather
    than be handed a confident-looking percentage.
    """
    conn = connect()
    c = conn.cursor()
    c.execute("""SELECT id, probability, predicted_class, outcome, threshold_used,
                        model_version, model_used, timestamp, outcome_at
                 FROM predictions WHERE outcome IS NOT NULL""")
    # Keep only rows whose outcome is 0 or 1.
    #
    # The arithmetic below sums this column. A row holding anything else — which is
    # what a string written by an older build looks like — makes `sum(obs)` raise
    # TypeError, and the caller catches that and returns an empty summary. The whole
    # deployed-performance panel then goes blank because of one bad row, with nothing
    # on screen to say so. Dropping the row costs one observation; keeping it cost the
    # entire feature.
    rows = [dict(r) for r in c.fetchall() if r["outcome"] in (0, 1)]
    c.execute("SELECT COUNT(*) FROM predictions")
    total = c.fetchone()[0]
    conn.close()

    n = len(rows)
    stats = {"total_predictions": total, "with_outcome": n,
             "coverage": (n / total) if total else 0.0}
    if n == 0:
        return stats, rows

    tp = sum(1 for r in rows if r["predicted_class"] == 1 and r["outcome"] == 1)
    fp = sum(1 for r in rows if r["predicted_class"] == 1 and r["outcome"] == 0)
    fn = sum(1 for r in rows if r["predicted_class"] == 0 and r["outcome"] == 1)
    tn = sum(1 for r in rows if r["predicted_class"] == 0 and r["outcome"] == 0)
    probs = [r["probability"] for r in rows if r["probability"] is not None]
    obs = [r["outcome"] for r in rows]

    stats.update({
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "sensitivity": tp / (tp + fn) if (tp + fn) else None,
        "specificity": tn / (tn + fp) if (tn + fp) else None,
        "ppv": tp / (tp + fp) if (tp + fp) else None,
        "npv": tn / (tn + fn) if (tn + fn) else None,
        "observed_rate": sum(obs) / n,
        "mean_predicted": (sum(probs) / len(probs)) if probs else None,
        "calibration_drift": ((sum(probs) / len(probs)) - (sum(obs) / n))
                             if probs else None,
        # Below this, per-metric estimates are too noisy to act on
        "reliable": n >= 30,
    })
    return stats, rows
