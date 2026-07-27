import streamlit as st
import os, json, pickle, time, subprocess, sys, html
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime
import base64
import auth_db
import pages_ext as px
import feature_engineering as fe
import clinical_ui as cu
from ui import styles as ui_styles
from ui import brand as ui_brand
from ui import components as uic
from ui import format as fmt
from ui import login as ui_login
from ui import charts as ucharts
from ui import diagnosis as ud


# ══════════════════════════════════════════════════════════════════
# SHARED HELPERS (added Run 3 — see TASK.md)
# ══════════════════════════════════════════════════════════════════
def esc(value):
    """
    Escape a user-controlled value before interpolating it into raw HTML.

    FIXED (BUG-12): profile fields (fullname / username / email) were being injected
    straight into `unsafe_allow_html` markup, so a user could store HTML that executes
    for anyone who views their record.
    """
    return html.escape(str(value if value is not None else ""))


def gradient_hex(j, n, start=(220, 38, 38), end=(50, 138, 238)):
    """
    Interpolated colour as a matplotlib-safe hex string.

    FIXED (BUG-01 / BUG-02): the previous code built CSS `rgba(r,g,b,a)` strings and
    handed them to `ax.barh(color=...)`. Matplotlib rejects CSS colour syntax with
    `ValueError: Invalid RGBA argument`, which crashed the entire Model Performance
    page — for every role — and took Tabs 6, 7 and 8 (ROC/PR, K-Fold, SHAP) down with it.
    """
    t = (j / max(n - 1, 1)) if n > 1 else 0.0
    r = int(start[0] + (end[0] - start[0]) * t)
    g = int(start[1] + (end[1] - start[1]) * t)
    b = int(start[2] + (end[2] - start[2]) * t)
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def _support_hint(field):
    """
    Human-readable supported range for an input, from the training envelope.

    Part of BUG-23: the form accepted ages 1-120 while the model was fitted on 30-65,
    and nothing anywhere said so. Showing the range at the point of entry makes
    extrapolation avoidable rather than merely detectable after the fact.
    """
    env = cu.load_input_ranges().get("features", {}).get(field)
    if not env:
        return None
    return (f"Model supported range: {env['min']:g}–{env['max']:g} "
            f"(typical {env['p1']:g}–{env['p99']:g}). Values outside this are "
            f"extrapolation and will be flagged.")


def load_benchmarks():
    """Clinical benchmark + incremental feature value analysis (models/benchmarks.json)."""
    try:
        bp = os.path.join(MODELS_DIR, "benchmarks.json")
        if os.path.exists(bp):
            with open(bp) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def load_thresholds():
    """Per-model operating points derived at training time (models/thresholds.json)."""
    try:
        tp = os.path.join(MODELS_DIR, "thresholds.json")
        if os.path.exists(tp):
            with open(tp) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_risk_threshold(model_name="Ensemble Voting"):
    """
    Decision threshold for a given model.

    Resolution order:
      1. An explicit `risk_threshold` in system_settings.json (SuperAdmin override)
      2. The model's derived operating point from models/thresholds.json
      3. 0.5 as a last resort

    WHY THIS IS NOT 0.5 (Run 4)
    ---------------------------
    0.50 is the default for a balanced-accuracy objective. This is a *screening* tool:
    it triages patients into further testing rather than diagnosing them, so a missed
    case costs far more than a false alarm. At 0.50 the app missed 31% of diseased
    patients. The thresholds now come from the holdout ROC, chosen as the highest
    threshold still achieving >= 85% sensitivity — which more than halves the miss rate
    (157 -> 74 per 1,000).
    """
    try:
        sp = os.path.join(BASE_DIR, "system_settings.json")
        if os.path.exists(sp):
            with open(sp) as f:
                override = json.load(f).get("risk_threshold")
            if override is not None:
                return float(override)
    except Exception:
        pass

    th = load_thresholds().get("models", {})
    if model_name in th:
        return float(th[model_name]["recommended"])
    if "Ensemble Voting" in th:
        return float(th["Ensemble Voting"]["recommended"])
    return 0.5


def get_stratified_threshold(model_name, age):
    """
    Age-band-specific operating point (Run 5).

    WHY AGE-STRATIFIED
    ------------------
    Baseline cardiovascular risk ranges from 28% under 45 to 65% over 60 in this
    cohort. A single global cut-point therefore delivered wildly unequal care:
    63% sensitivity for under-45s, while flagging 95% of over-60s (specificity 0.106,
    i.e. useless as triage). Per-band thresholds equalise sensitivity at ~85%
    everywhere and restore usable specificity in the older bands.

    Every established cardiovascular risk instrument — Framingham, SCORE2, QRISK3 —
    is age-stratified for exactly this reason.

    A SuperAdmin override, if set, still wins over everything.
    """
    try:
        sp = os.path.join(BASE_DIR, "system_settings.json")
        if os.path.exists(sp):
            with open(sp) as f:
                override = json.load(f).get("risk_threshold")
            if override is not None:
                return float(override)
    except Exception:
        pass

    strat = load_thresholds().get("stratified", {})
    band_map = strat.get(model_name) or strat.get("Ensemble Voting") or {}
    for label, info in band_map.items():
        if info.get("age_min", 0) <= age < info.get("age_max", 999):
            return float(info["threshold"])
    return get_risk_threshold(model_name)


def get_subgroup_performance(model_name="Ensemble Voting"):
    """Measured per-subgroup performance recorded at training time."""
    res = load_results(include_virtual=True).get(model_name) or \
          load_results(include_virtual=True).get("Ensemble Voting") or {}
    return res.get("subgroups", {})


def patient_subgroup_reliability(age, model_name="Ensemble Voting"):
    """
    The model's measured performance for the age band this patient falls in.

    Surfacing this is the actual fix for 'nobody would know': aggregate AUC hid that
    discrimination varies from 0.84 (under 45) to 0.73 (55-59). A clinician cannot
    calibrate their trust in a score without knowing how well it performs for this
    kind of patient.
    """
    subs = get_subgroup_performance(model_name).get("Age band", [])
    label = fe.age_band_label(age)
    for lv in subs:
        if lv["level"] == label:
            return lv
    return None


def get_risk_bands(model_name="Ensemble Voting", active_threshold=None):
    """
    Four-tier risk bands derived from the model's ROC (Run 4).

    A bare HIGH/LOW verdict throws away most of the clinical information in a
    probability. These bands map to distinct actions:

      Low          below the rule-out point (>=95% sensitivity) - confidently excluded
      Borderline   between rule-out and the action threshold    - monitor / lifestyle
      Intermediate above the action threshold                   - further testing
      High         above the rule-in point (>=90% specificity)  - escalate directly
    """
    th = load_thresholds().get("models", {})
    entry = th.get(model_name) or th.get("Ensemble Voting")
    if entry and entry.get("risk_bands"):
        b = entry["risk_bands"]
        low, border, inter = (float(b["low_max"]), float(b["borderline_max"]),
                              float(b["intermediate_max"]))
    else:
        t = get_risk_threshold(model_name)
        low, border, inter = (max(t - 0.15, 0.05), t, min(t + 0.20, 0.95))

    # The band boundary must track whatever threshold is actually in force — the
    # SuperAdmin override or, from Run 5, the patient's age-stratified value.
    # Otherwise the displayed band can contradict the binary verdict.
    active = active_threshold if active_threshold is not None else get_risk_threshold(model_name)
    if abs(active - border) > 1e-9:
        border = active
        low = min(low, border)
        inter = max(inter, border)
    return (low, border, inter)


def classify_risk_band(prob, model_name="Ensemble Voting", active_threshold=None):
    """Return (band_label, colour, recommended action) for a probability."""
    low_max, border_max, inter_max = get_risk_bands(model_name, active_threshold)
    if prob < low_max:
        return ("LOW RISK", ucharts.color('risk_low'),
                "No significant cardiovascular risk pattern detected. Routine review.")
    if prob < border_max:
        return ("BORDERLINE", ucharts.color('risk_borderline'),
                "Below the screening action threshold. Lifestyle advice and re-assessment advised.")
    if prob < inter_max:
        return ("INTERMEDIATE RISK", ucharts.color('risk_intermediate'),
                "Above the screening action threshold. Further cardiovascular testing indicated.")
    return ("HIGH RISK", ucharts.color('risk_high'),
            "Strong cardiovascular risk pattern. Immediate clinical review advised.")


def registration_allowed():
    """Honour the `allow_registration` system setting (BUG-17)."""
    try:
        sp = os.path.join(BASE_DIR, "system_settings.json")
        if os.path.exists(sp):
            with open(sp) as f:
                return bool(json.load(f).get("allow_registration", True))
    except Exception:
        pass
    return True


# Stable per-model display metadata — keyed by name, never by position (BUG-19).
MODEL_SHORT_NAMES = {
    "Logistic Regression": "LR",
    "Support Vector Machine (SVM)": "SVM",
    "Decision Tree": "DT",
    "Random Forest": "RF",
    "XGBoost": "XGB",
}
# Model colours live in the token module as T.SERIES and are reached through
# ucharts.series_color(name). A dict here would be evaluated at import time, before any
# script run, freezing one theme; and it would hand models RISK hues, which 3.10
# reserves for clinical meaning.

# ══════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════════════════
# page_icon was the literal letter "H". It is now the Caliper Mark, rendered to PNG by
# ui/brand.py via Pillow (already a matplotlib dependency, so requirements.txt does not
# grow). favicon_path() returns None if generation failed, and Streamlit falls back to
# its default icon — a missing favicon must never prevent the app from starting.
st.set_page_config(
    page_title="HeartGuard AI - Cardiovascular Risk Portal",
    page_icon=ui_brand.favicon_path() or "H",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_VERSION = "HeartGuard AI v2.1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_PATH = os.path.join(BASE_DIR, "heart.csv")


# ── Background image helper ──────────────────────────────────────
def get_bg_b64():
    img_path = os.path.join(BASE_DIR, "heart_bg.png")
    if os.path.exists(img_path):
        with open(img_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None


# ==================================================================
# GLOBAL STYLESHEET
# ==================================================================
# The previous 154-line inline block lived here. It is now generated from
# ui/tokens.py so the palette has exactly one definition - the same discipline
# feature_engineering.py enforces for the feature contract.
#
# Injection order is load-bearing: set_page_config -> inject() -> any widget.
# The stylesheet is cached, so it is built once per process rather than rebuilt on
# every rerun (which would flash unstyled content as the <style> block re-mounts).
ui_styles.inject()

# ══════════════════════════════════════════════════════════════════
# MODEL LOADING
# ══════════════════════════════════════════════════════════════════
@st.cache_resource
def load_models():
    scaler_path = os.path.join(MODELS_DIR, "scaler.pkl")
    if not os.path.exists(scaler_path):
        return None, {}
    try:
        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        labels = {
            "Logistic Regression": "logistic_regression.pkl",
            "Support Vector Machine (SVM)": "svm.pkl",
            "Decision Tree": "decision_tree.pkl",
            "Random Forest": "random_forest.pkl",
            "XGBoost": "xgboost.pkl",
        }
        models = {}
        for name, fname in labels.items():
            p = os.path.join(MODELS_DIR, fname)
            if os.path.exists(p):
                with open(p, "rb") as f:
                    models[name] = pickle.load(f)
        return scaler, models
    except Exception as e:
        st.error(f"Model loading error: {e}")
        return None, {}


def load_config():
    cfg_path = os.path.join(MODELS_DIR, "config.json")
    defaults = {k: True for k in ["Logistic Regression", "Support Vector Machine (SVM)",
                                   "Decision Tree", "Random Forest", "XGBoost"]}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            return json.load(f)
    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(cfg_path, "w") as f:
        json.dump(defaults, f)
    return defaults


def save_config(cfg):
    with open(os.path.join(MODELS_DIR, "config.json"), "w") as f:
        json.dump(cfg, f)


def load_results(include_virtual=False):
    """
    Trained-model results from results.json.

    Run 4 added a virtual "Ensemble Voting" entry so the app's default prediction path
    gets its own derived operating point. It is NOT a saved estimator — it has no
    confusion matrix, feature importances or cross-validation — so it is excluded by
    default. Only the threshold analysis (Tab 9) asks for it via include_virtual=True.
    """
    rp = os.path.join(MODELS_DIR, "results.json")
    if not os.path.exists(rp):
        return {}
    with open(rp) as f:
        data = json.load(f)
    if include_virtual:
        return data
    return {k: v for k, v in data.items() if not v.get("is_virtual")}


# ══════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "Login"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════
def logout():
    u = st.session_state.user
    auth_db.log_activity(u['id'], u['username'], "Logout", "User session ended.")
    st.session_state.user = None
    st.rerun()


def role_badge(role):
    cls = {"Doctor": "rb-doctor", "Admin": "rb-admin", "SuperAdmin": "rb-superadmin"}.get(role, "rb-admin")
    label = {"Doctor": "Doctor", "Admin": "Admin", "SuperAdmin": "Super Admin"}.get(role, role)
    return f'<span class="role-badge {cls}">{label}</span>'


def kpi(val, label, color=None, bg=None, border=None):
    """
    Legacy signature, new rendering.

    The colour arguments are accepted and IGNORED. Every call site passed its own hex
    plus a gradient and a border colour, which is how the dashboards ended up with six
    competing hues; Phase 8 replaced that with `stat_grid`, and this shim converts the
    16 remaining admin call sites without touching their argument lists.

    Tone is not inferred from the discarded colour. A label mentioning risk gets a
    clinical tone; everything else stays neutral, because colouring an inventory count
    the same crimson as a clinical finding is what made these strips unreadable.
    """
    low = str(label).lower()
    tone = ("high" if ("high risk" in low or "banned" in low)
            else "low" if ("low risk" in low or "active" in low) else "default")
    return uic.stat(str(label), str(val), tone=tone)


def section_header(icon, title, subtitle=""):
    """
    Adapter onto uic.page_header, kept so the 16 existing call sites need not change
    in this phase. `icon` is accepted and ignored: the old signature passed single
    letters ("K", "S", "T", "F", "B") as pseudo-icons, which the icon set replaces.
    Call sites migrate to page_header directly as each page is rebuilt.
    """
    uic.page_header(title, subtitle or None)


# ══════════════════════════════════════════════════════════════════
# LOGIN / REGISTER PAGE
# ══════════════════════════════════════════════════════════════════
def login_facts():
    """
    The record count and trust markers for the sign-in panel (§7.2).

    Derived from the shipped artifacts, never written into the copy: a hard-coded
    "AUC 0.8000" on the sign-in screen becomes a false claim the first time anyone
    retrains. A missing artifact drops its marker rather than substituting a
    plausible-looking number — the panel simply carries fewer lines.

    The prediction path defaults to the ensemble, so the ensemble is what the marker
    reports. Quoting the best single model here while the app scores with a different
    one would make the headline figure describe something the user never touches.
    """
    rows = int(cu.model_version_info().get("rows", 0) or 0)
    markers = []

    res = load_results(include_virtual=True)
    m = res.get("Ensemble Voting") or {}
    if "auc" in m:
        auc_txt = f"AUC {fmt.auc(m['auc'])}"
        if m.get("auc_ci_low") is not None and m.get("auc_ci_high") is not None:
            auc_txt += " " + fmt.interval(m["auc_ci_low"], m["auc_ci_high"], fmt.auc)
        markers.append(("Discrimination", auc_txt))

    th = load_thresholds()
    pol, strat = th.get("policy", {}), th.get("stratification", {})
    if pol.get("target_sensitivity") and strat.get("variable"):
        markers.append(("Operating point",
                        f"Sensitivity {pol['target_sensitivity']:.2f} · "
                        f"{strat['variable']}-stratified"))

    if m.get("mean_predicted") is not None and m.get("test_prevalence") is not None:
        markers.append(("Calibration gap",
                        fmt.metric3(abs(m["mean_predicted"] - m["test_prevalence"]))))

    return rows, markers


def page_login():
    """
    §7.2 — full-bleed 44/56 split.

    The authentication contract is untouched: the same validate_login call, the same
    three statuses, the same log_activity on success, the same registration_allowed
    gate (BUG-17) and the same Doctor-only role lock (BUG-09). What changed is where
    failures are reported. They used to be st.error banners above the form; §7.2 asks
    for validation beneath the field it concerns, which needs the message to survive
    into the next run — hence the two session_state error dicts. They are cleared on
    every submit so a corrected field's message disappears with it.
    """
    rows, markers = login_facts()

    with ui_login.split() as (left, right):
        with left:
            ui_login.brand_panel(
                ui_login.STATEMENT.format(n=fmt.count(rows) if rows else "68,645"),
                markers)

        with right:
            mode = "Sign in"
            with st.container(key="login-seg"):
                mode = st.segmented_control(
                    "Mode", ["Sign in", "Register"], default="Sign in",
                    key="login_mode_seg", label_visibility="collapsed") or "Sign in"

            if mode == "Sign in":
                _login_form()
            else:
                _register_form()


def _login_form():
    err = st.session_state.get("login_err", {})
    with ui_login.card("Sign in", "Access the cardiovascular screening console."):
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Your username")
            ui_login.inline_error(err.get("username"))
            password = st.text_input("Password", type="password",
                                     placeholder="Your password")
            ui_login.inline_error(err.get("password"))
            ui_login.inline_error(err.get("form"))
            submitted = st.form_submit_button("Sign in", type="primary",
                                              width="stretch")
            if submitted:
                e = {}
                if not username:
                    e["username"] = "Enter your username."
                if not password:
                    e["password"] = "Enter your password."
                if not e:
                    user, status = auth_db.validate_login(username.strip(), password)
                    if status == "ok":
                        st.session_state.user = user
                        st.session_state.login_err = {}
                        auth_db.log_activity(user['id'], username, "Login",
                                             f"Authenticated as {user['role']}.")
                        st.rerun()
                    elif status == "banned":
                        e["form"] = ("This account is suspended. Contact the "
                                     "administrator to restore access.")
                    else:
                        # Deliberately does not say which of the two was wrong: naming
                        # the field turns the form into a username oracle.
                        e["form"] = "That username and password do not match an account."
                st.session_state.login_err = e
                st.rerun()
        ui_login.seed_hint()


def _register_form():
    # FIXED (BUG-17): the `allow_registration` system setting is now enforced.
    # It was previously saved and displayed but read by no one.
    if not registration_allowed():
        with ui_login.card("Register"):
            uic.alert("warning", "Registration is closed",
                      "An administrator has disabled public sign-up. Ask them to "
                      "create an account for you.")
        return

    err = st.session_state.get("reg_err", {})
    ok = st.session_state.pop("reg_ok", None)
    with ui_login.card("Create an account",
                       "New accounts are issued the Doctor role."):
        if ok:
            uic.alert("success", "Account created",
                      f"Sign in as {fmt.esc(ok)} using the password you chose.")
        with st.form("reg_form"):
            r_user = st.text_input("Username", placeholder="Choose a username")
            ui_login.inline_error(err.get("username"))
            r_full = st.text_input("Full name", placeholder="e.g. Dr. Ahmed Khan")
            ui_login.inline_error(err.get("fullname"))
            r_email = st.text_input("Email", placeholder="you@hospital.org")
            ui_login.inline_error(err.get("email"))
            r_spec = st.text_input("Specialisation", placeholder="e.g. Cardiologist")
            r_pass = st.text_input("Password", type="password",
                                   placeholder="At least 6 characters")
            ui_login.inline_error(err.get("password"))
            # FIXED (BUG-09): self-service registration is locked to the Doctor
            # role. The dropdown previously offered SuperAdmin to anonymous
            # visitors, and was already exploited — two accounts in the live
            # database had elevated themselves this way. Elevation now happens
            # only through Role & Permission Management, by an existing SuperAdmin.
            r_role = "Doctor"
            r_sub = st.form_submit_button("Create account", type="primary",
                                          width="stretch")
            if r_sub:
                e = {}
                if not r_user:
                    e["username"] = "Choose a username."
                if not r_full:
                    e["fullname"] = "Enter your full name."
                if not r_email:
                    e["email"] = "Enter an email address."
                if not r_pass:
                    e["password"] = "Choose a password."
                elif len(r_pass) < 6:
                    e["password"] = "Use at least 6 characters."
                if not e:
                    uid, _err = auth_db.register_user(
                        r_user.strip(), r_pass, r_role, r_full, r_email, r_spec)
                    if uid:
                        st.session_state.reg_ok = r_user.strip()
                    else:
                        e["username"] = "That username is taken. Choose another."
                st.session_state.reg_err = e
                st.rerun()
        st.caption("Contact an administrator if you need elevated access.")


# ══════════════════════════════════════════════════════════════════
# SIDEBAR (after login)
# ══════════════════════════════════════════════════════════════════
def render_sidebar(user, pages):
    """
    Render the shell sidebar and return the selected page label.

    The routing contract is unchanged: this still returns a page LABEL that app.py's
    router matches on, so no route moves. What changed is the mechanism — a single
    st.radio became one button per item inside a keyed container, because a radio
    cannot carry an icon, cannot be grouped under eyebrow labels, and cannot take the
    per-item active treatment §7.1 specifies (a 2px verdigris left border).

    Selection therefore lives in session state rather than in the widget. A click is
    detected during the sidebar pass, so items already drawn above it still show the
    previous active state — hence the rerun, which repaints the whole sidebar with the
    new selection before any main content is built.
    """
    active = st.session_state.get("nav_page")
    if active not in pages:
        # First visit, or a role change removed the page that was selected.
        active = pages[0]
        st.session_state.nav_page = active

    selected = uic.sidebar_nav(user, pages, active)
    if selected != active:
        st.session_state.nav_page = selected
        st.rerun()

    _ver = cu.model_version_info()
    if uic.sidebar_footer(APP_VERSION, _ver.get("version", "")):
        logout()
    return st.session_state.nav_page


# ══════════════════════════════════════════════════════════════════
#
# Rebuilt in Phase 6 against §7.3. The clinical pipeline is byte-for-byte the same
# sequence it was before — physiology check, applicability check, feature build, scale,
# per-model probability, age-stratified threshold, band classification, patient upsert,
# add_prediction — and the assertions in tests/test_diagnosis.py pin that order.
#
# THREE STRUCTURAL CHANGES, each with a reason:
#
# 1. The inputs left st.form. §7.3 requires the applicability rails to show "the
#    patient's current value as a live marker" so a clinician sees they are about to
#    extrapolate BEFORE submitting. A form withholds its widget values until submit,
#    which would draw every marker at its default while the fields above showed
#    something else. A marker that disagrees with its own field is worse than none.
#
# 2. The result is therefore held in session state. Without a form, any keystroke
#    reruns the script, and a result rendered inline would vanish the moment the
#    clinician touched a field to compare. Scoring and the DB write still happen ONLY
#    inside the submit branch, so the one-row-per-submit contract is unchanged.
#
# 3. The global feature_importances_ chart is gone. It was a static, model-level
#    ranking — identical for every patient — captioned "Top Risk Factors" directly
#    beneath that patient's score. It read as personalised reasoning while containing
#    none. Replaced by the per-patient SHAP waterfall the engine has been able to
#    produce since Run 7.
# ══════════════════════════════════════════════════════════════════
DIAG_FIELDS = ("age", "gender", "height", "weight", "ap_hi", "ap_lo",
               "cholesterol", "gluc", "smoke", "alco", "active")


def _diag_inputs():
    """
    The eleven clinical indicators, grouped into the four panels §7.3 specifies.

    Ordered the way a clinician acquires them: demographics are free, vitals need a
    cuff and scales, laboratory needs a blood draw, lifestyle needs a conversation.
    Each numeric input keeps the supported-range tooltip added for BUG-23, and values
    are deliberately NOT clamped to the envelope — a real 82-year-old must be
    enterable — but the score they produce is then labelled an extrapolation.
    """
    v = {}
    with uic.panel("Patient"):
        a, b = st.columns(2)
        v["p_id"] = a.text_input("Patient code", key="diag_pid",
                                 placeholder="e.g. PT-00123")
        v["p_name"] = b.text_input("Patient name", key="diag_pname",
                                   placeholder="e.g. Ahmed Khan")

    with uic.panel("Demographics"):
        a, b = st.columns(2)
        v["age"] = a.number_input("Age (years)", 1, 120, 45, key="diag_age",
                                  help=_support_hint("age"))
        v["gender"] = b.selectbox("Gender", [(1, "Male"), (0, "Female")],
                                  format_func=lambda x: x[1], key="diag_gender")[0]

    with uic.panel("Vitals"):
        a, b = st.columns(2)
        v["height"] = a.number_input("Height (cm)", 100, 250, 165, key="diag_height",
                                     help=_support_hint("height"))
        v["weight"] = b.number_input("Weight (kg)", 20.0, 200.0, 70.0, step=0.5,
                                     key="diag_weight", help=_support_hint("weight"))
        c, d = st.columns(2)
        v["ap_hi"] = c.number_input("Systolic BP (mmHg)", 60, 250, 120,
                                    key="diag_aphi", help=_support_hint("ap_hi"))
        v["ap_lo"] = d.number_input("Diastolic BP (mmHg)", 40, 200, 80,
                                    key="diag_aplo", help=_support_hint("ap_lo"))

    with uic.panel("Laboratory"):
        a, b = st.columns(2)
        # FIXED (BUG-04): options use the dataset's 0-indexed encoding
        # (0=Normal, 1=Above, 2=Well Above). The form previously sent 1/2/3, so
        # "Normal" scored as above-normal and "Well Above Normal" sent a value (3)
        # that appears nowhere in the training data.
        v["cholesterol"] = a.selectbox("Cholesterol", fe.CHOLESTEROL_LEVELS,
                                       format_func=lambda x: x[1], key="diag_chol")[0]
        v["gluc"] = b.selectbox("Glucose", fe.GLUCOSE_LEVELS,
                                format_func=lambda x: x[1], key="diag_gluc")[0]

    with uic.panel("Lifestyle"):
        a, b, c = st.columns(3)
        yn = [(1, "Yes"), (0, "No")]
        v["smoke"] = a.selectbox("Smoker", yn, format_func=lambda x: x[1],
                                 key="diag_smoke")[0]
        v["alco"] = b.selectbox("Alcohol", yn, format_func=lambda x: x[1],
                                key="diag_alco")[0]
        v["active"] = c.selectbox("Active", yn, format_func=lambda x: x[1],
                                  key="diag_active")[0]
    return v


def _applicability_expander(inputs):
    """
    §7.3: the applicability expander stays directly above the submit button, redesigned
    as a table of miniature Reference Rails.

    Derived features are included because BUG-26 established that they can breach the
    envelope while every entered value sits inside it — a tall, light patient produces
    a BMI the model never saw from a height and weight it saw constantly.
    """
    env = cu.load_input_ranges()
    if not env.get("features"):
        return
    live = dict(inputs)
    try:
        live["bmi"] = fe.compute_bmi(inputs["weight"], inputs["height"])
    except Exception:
        pass
    labels = {k: fe.label_for(k) for k in ud.CONSTRAINED_FEATURES}
    with st.expander("Model applicability — is this patient one the model has seen?"):
        st.markdown(
            f'<p class="hg-note">Fitted on <b>{fmt.count(env.get("trained_rows", 0))}'
            f'</b> patients. The bar shows the full observed range; the shaded zone is '
            f'the typical 1st–99th percentile; the hatched shoulders are sparse '
            f'territory. A marker outside the bar is an extrapolation and is labelled '
            f'as one on the result.</p>', unsafe_allow_html=True)
        st.markdown(ud.applicability_rails(env, live, labels), unsafe_allow_html=True)


def page_diagnosis(user):
    uic.page_header(
        "Heart disease screening",
        "Cardiovascular risk estimated from eleven clinical indicators, with the "
        "model's operating point and applicability disclosed on every result.")

    scaler, all_models = load_models()
    cfg = load_config()
    active_models = {k: v for k, v in all_models.items() if cfg.get(k, True)}

    if not active_models or scaler is None:
        uic.alert("warning", "No trained models available",
                  "Ask a SuperAdmin to run model training before using this page.")
        return

    col_form, col_out = st.columns([58, 42], gap="large")

    with col_form:
        vals = _diag_inputs()
        with uic.panel("Model"):
            model_opts = ["Ensemble Voting (All Models)"] + list(active_models.keys())
            model_choice = st.selectbox("Scoring model", model_opts, key="diag_model")
            notes = st.text_area("Clinical notes (optional)", height=68,
                                 key="diag_notes")
        _applicability_expander(vals)
        submit = st.button("Run assessment", type="primary",
                           width="stretch", key="diag_submit")

    if submit:
        st.session_state.diag_result = _run_assessment(
            user, vals, model_choice, notes, scaler, active_models)

    with col_out:
        with st.container(key="diag-result"):
            res = st.session_state.get("diag_result")
            if res is None:
                uic.empty_state(
                    "No assessment yet",
                    "Enter the patient's indicators and select Run assessment. The "
                    "result appears here with its operating point and reliability.")
            elif res.get("refused"):
                _render_refusal(res)
            else:
                _render_result(res, user)


# ──────────────────────────────────────────────────────────────────
# Scoring — unchanged pipeline, extracted so the render path can rerun without it
# ──────────────────────────────────────────────────────────────────
def _run_assessment(user, vals, model_choice, notes, scaler, active_models):
    """
    Score one patient and persist the row. Returns a plain dict for rendering.

    Extracted from the render path so that redrawing the result — which now happens on
    every keystroke, because the inputs are no longer inside a form — cannot rescore
    the patient or write a second database row.
    """
    p_id, p_name = vals["p_id"].strip(), vals["p_name"].strip()
    if not p_id or not p_name:
        return {"refused": "fields",
                "errors": ["Patient code and patient name are both required."]}

    inputs = {k: vals[k] for k in DIAG_FIELDS}

    # ── BUG-26: physiological validity, checked BEFORE scoring ──
    # Distinct from the applicability guard below. Extrapolation means "a real patient
    # the model has not seen" and earns a warning; this means "not a possible
    # measurement" and must be refused. 90/180 was previously accepted and returned a
    # confident LOW RISK verdict.
    phys_errors = fe.validate_physiology(inputs)
    if phys_errors:
        return {"refused": "physiology", "errors": phys_errors}

    # ── BUG-23: applicability check ─────────────────────────────
    # A risk estimate is only valid for the population it was fitted on. This runs
    # BEFORE anything is rendered, because a hard extrapolation invalidates the peer
    # percentile and the care plan, not just the score.
    app_warn, extrapolated = cu.check_applicability(inputs)
    app_notes = "; ".join(
        f"{w['label']}={w['value']:g} outside {w['supported'][0]:g}-"
        f"{w['supported'][1]:g} ({w['severity']})" for w in app_warn)

    # FIXED (BUG-05): engineered features come from the shared module, so training and
    # inference cannot drift apart.
    features = fe.build_feature_row(**inputs)
    feats_s = scaler.transform([features])

    # FIXED (BUG-18): one decision rule for both paths.
    # Run 4: the threshold is derived per model from the holdout ROC at a >=85%
    # sensitivity target, not hardcoded at 0.5.
    # Run 5: each model scored at ITS OWN age-stratified operating point.
    age = inputs["age"]
    probs = {mn: float(mo.predict_proba(feats_s)[0][1])
             for mn, mo in active_models.items()}
    member_thresholds = {mn: get_stratified_threshold(mn, age) for mn in probs}
    preds = {mn: int(p >= member_thresholds[mn]) for mn, p in probs.items()}

    if "Ensemble" in model_choice:
        final_prob = float(np.mean(list(probs.values())))
        used_label = "Ensemble Voting"
    else:
        final_prob = probs[model_choice]
        used_label = model_choice

    risk_threshold = get_stratified_threshold(used_label, age)
    final_pred = int(final_prob >= risk_threshold)
    band_label, band_color, band_action = classify_risk_band(
        final_prob, used_label, active_threshold=risk_threshold)
    thr_meta = load_thresholds().get("models", {}).get(used_label, {})
    sub_rel = patient_subgroup_reliability(age, used_label)
    age_band = fe.age_band_label(age)
    ver = cu.model_version_info()

    # Run 7: link the assessment to a patient entity and stamp it with the model
    # version and operating point that produced it.
    # BUG-24: linking to a patient entity must never be able to lose the assessment.
    link_error = None
    try:
        patient_ref = auth_db.upsert_patient(p_id, p_name, inputs["gender"], user['id'])
    except Exception as pe:
        patient_ref, link_error = None, type(pe).__name__

    auth_db.add_prediction(
        user['id'], inputs["age"], inputs["gender"], inputs["height"],
        inputs["weight"], inputs["ap_hi"], inputs["ap_lo"],
        inputs["cholesterol"], inputs["gluc"], inputs["smoke"], inputs["alco"],
        inputs["active"], final_pred, final_prob, used_label, p_name, notes,
        patient_ref=patient_ref,
        model_version=ver["version"],
        model_manifest_sha=ver["manifest_sha"],
        threshold_used=risk_threshold,
        risk_band=band_label,
        extrapolated=int(extrapolated),
        applicability_notes=app_notes)

    # Peer comparison, GATED on applicability (BUG-23). searchsorted against an
    # age×sex reference distribution is meaningless when the patient's age has no
    # stratum: an 82-year-old would be silently ranked against 60–65 year-olds and
    # told they are typical. Withheld rather than approximated.
    pct_v = pct_label = pct_n = None
    if not extrapolated:
        pct_v, pct_label, pct_n = cu.risk_percentile(final_prob, age, inputs["gender"])

    res = {
        "refused": None, "inputs": inputs, "p_id": p_id, "p_name": p_name,
        "notes": notes, "probs": probs, "preds": preds,
        "member_thresholds": member_thresholds,
        "final_prob": final_prob, "final_pred": final_pred,
        "used_label": used_label, "model_choice": model_choice,
        "threshold": risk_threshold, "band_label": band_label,
        "band_action": band_action, "thr_meta": thr_meta, "sub_rel": sub_rel,
        "age_band": age_band, "version": ver, "patient_ref": patient_ref,
        "link_error": link_error, "app_warn": app_warn,
        "extrapolated": extrapolated, "app_notes": app_notes,
        "percentile": pct_v, "pct_label": pct_label, "pct_n": pct_n,
        "features": features, "feats_scaled": feats_s,
    }
    res.update(_explain(res, scaler, active_models))
    return res


def _explain(res, scaler, active_models):
    """
    Per-patient SHAP and the counterfactual table.

    Both are computed once, here, and cached in the result — they are the two
    expensive operations on this page and the render path now runs on every keystroke.

    §7.3 routes counterfactuals through the MONOTONIC XGBOOST, not the ensemble. The
    reason is not preference: XGBoost carries monotone_constraints, so a change in a
    protective direction cannot raise its predicted risk. Averaging it with
    unconstrained members reintroduces exactly the paradoxical rows the constraint
    exists to prevent, and the panel would then report "lower your blood pressure" as
    an increase in risk.
    """
    out = {"shap": None, "shap_error": None, "explainer": None,
           "explainer_surrogate": False, "counterfactuals": None, "cf_model": None}

    feat_names = _feature_names()
    try:
        exp_name, surrogate = cu.resolve_explainer_model(
            res["model_choice"], active_models)
        out["explainer"], out["explainer_surrogate"] = exp_name, surrogate
        model = active_models.get(exp_name)
        if model is not None:
            vals, base, err = cu.explain_patient(
                model, res["feats_scaled"], feat_names)
            if err:
                out["shap_error"] = err
            else:
                out["shap"] = (vals, base)
    except Exception as exc:
        out["shap_error"] = type(exc).__name__

    cf_name = "XGBoost" if "XGBoost" in active_models else None
    if cf_name is None:
        # No constrained model available. Report nothing rather than falling back to
        # the ensemble — a paradoxical row from an unconstrained average would be
        # indistinguishable from a real model limitation.
        out["cf_model"] = None
    else:
        try:
            out["cf_model"] = cf_name
            out["counterfactuals"] = cu.counterfactual_table(
                {cf_name: active_models[cf_name]}, scaler, {cf_name: 1.0},
                res["inputs"], res["final_prob"])
        except Exception:
            out["counterfactuals"] = None
    return out


def _feature_names():
    try:
        fp = os.path.join(MODELS_DIR, "features.json")
        if os.path.exists(fp):
            with open(fp) as f:
                return json.load(f)
    except Exception:
        pass
    return list(fe.FEATURE_ORDER)


# ──────────────────────────────────────────────────────────────────
# Rendering — strict vertical priority, §7.3
# ──────────────────────────────────────────────────────────────────
def _render_refusal(res):
    if res["refused"] == "fields":
        uic.alert("warning", "Missing patient identification", res["errors"][0])
        return
    # BUG-26. "Not scored" is stated in the title, not buried in the body: the absence
    # of a number is the finding.
    uic.alert("danger", "Implausible measurement — not scored",
              "These values cannot describe a real patient, so no risk estimate was "
              "produced. Correct them and run the assessment again.",
              items=res["errors"])


def _render_result(res, user):
    # 0 ── WHOSE RESULT IS THIS ─────────────────────────────────────
    # Not decoration. The result now persists in session state across reruns, so a
    # clinician who starts entering a second patient sees the FIRST patient's verdict
    # still on screen beside the new form. Without the code and name attached, the two
    # are indistinguishable. This label is what makes the persistence safe.
    st.markdown(
        '<div class="hg-result-id">'
        + uic.identifier(res["p_id"], "Patient")
        + uic.identifier(res["p_name"], "Name")
        + uic.identifier(res["version"]["version"], "Model")
        + '</div>', unsafe_allow_html=True)

    # 1 ── EXTRAPOLATION BANNER, above everything, never collapsed ──
    if res["extrapolated"]:
        hard = [w for w in res["app_warn"] if w["severity"] == "hard"]
        uic.alert(
            "extrapolation", "Outside model applicability",
            "This patient falls outside the population the model was fitted on. The "
            "estimate below is an extrapolation: it has not been validated for this "
            "patient and must not be relied upon for a clinical decision. Peer "
            "comparison is withheld.",
            items=[f"{w['label']} = {w['value']:g} — fitted on "
                   f"{w['supported'][0]:g}–{w['supported'][1]:g}" for w in hard])
    elif res["app_warn"]:
        uic.alert(
            "warning", "Sparse training support",
            "Within the model's observed range but beyond the typical 1st–99th "
            "percentile. The estimate is usable but less certain than for a typical "
            "patient.",
            items=[f"{w['label']} = {w['value']:g}" for w in res["app_warn"]])

    if res["link_error"]:
        # BUG-24: the assessment is saved either way; say what was lost.
        uic.alert("warning", "Not linked to a patient record",
                  f"The assessment was saved, but linking it to the patient timeline "
                  f"failed ({res['link_error']}). It will not appear under this "
                  f"patient's history.")

    # 2 ── THE VERDICT ───────────────────────────────────────────────
    bands = _band_edges(res["used_label"])
    uic.risk_verdict(res["final_prob"], res["band_label"],
                     _band_key(res["band_label"]), bands, res["threshold"],
                     res["band_action"], extrapolated=res["extrapolated"])

    # 3 ── OPERATING POINT ───────────────────────────────────────────
    src = res["sub_rel"] or res["thr_meta"] or {}
    uic.operating_point(
        res["threshold"], src.get("sensitivity"), src.get("specificity"),
        src.get("ppv"), src.get("npv"),
        source=(f"Derived for ages {res['age_band'].lower()} from out-of-fold "
                f"predictions at a {_target_sensitivity():.0%} sensitivity target."
                if res["sub_rel"] else
                "Derived from out-of-fold predictions at a "
                f"{_target_sensitivity():.0%} sensitivity target."))

    # 4 ── RELIABILITY FOR THIS PATIENT'S BAND ───────────────────────
    # Run 5: aggregate metrics hid that discrimination ranges from 0.84 (under 45) to
    # 0.73 (55–59). A clinician cannot calibrate trust in a score without that.
    sr = res["sub_rel"]
    if sr:
        uic.reliability_panel(
            sr.get("auc"), sr.get("auc_ci_low"), sr.get("auc_ci_high"),
            sr.get("calibration_gap"), sr.get("n"),
            band_label=res["age_band"], overall=_overall_auc(res["used_label"]))
        if (sr.get("auc") or 1) < 0.75:
            # Wording preserved verbatim from Run 5 — §7.3 requires it unchanged.
            uic.alert("warning", "Interpret with extra caution",
                      "The model discriminates less well in this age band than "
                      "overall. Weight clinical judgement more heavily than the score.")

    # 5 ── PER-PATIENT SHAP ──────────────────────────────────────────
    _render_shap(res)

    # 6 ── COUNTERFACTUALS ───────────────────────────────────────────
    _render_counterfactuals(res)

    # 7 ── PEER PERCENTILE ───────────────────────────────────────────
    if res["extrapolated"]:
        st.markdown(ud.peer_withheld(), unsafe_allow_html=True)
    elif res["percentile"] is not None:
        st.markdown(ud.peer_percentile(res["percentile"], res["pct_label"],
                                       res["pct_n"]), unsafe_allow_html=True)

    # Model agreement, when the ensemble was used.
    if "Ensemble" in res["model_choice"]:
        uic.section("Member models",
                    "Each model scored at its own age-stratified operating point.")
        st.markdown(ud.model_breakdown(res["probs"], res["preds"],
                                       res["member_thresholds"]),
                    unsafe_allow_html=True)

    # 8 ── DOWNLOADS ─────────────────────────────────────────────────
    _render_downloads(res, user)


def _render_shap(res):
    """
    §7.3 item 5. The caption is "Contributions for this patient", not "Top Risk
    Factors" — the old caption made a claim the old chart could not support, because
    the old chart was a global feature ranking identical for every patient.
    """
    uic.section("Contributions for this patient")
    if res.get("shap") is None:
        uic.alert("info", "Explanation unavailable",
                  "SHAP could not be computed for this model"
                  + (f" ({res['shap_error']})." if res.get("shap_error") else "."))
        return
    vals, base = res["shap"]
    fig = cu.waterfall_figure(vals, base, _feature_names(),
                              res["features"], res["final_prob"])
    ucharts.render(fig)
    st.markdown(
        '<p class="hg-note">Bars are contributions in log-odds, the model\'s native '
        'output space. They do not sum to the probability above, and they are not '
        'causal — they describe how this model reached this number for these '
        'inputs.</p>', unsafe_allow_html=True)
    st.markdown(ud.explainer_disclosure(res["used_label"], res["explainer"] or "",
                                        res["explainer_surrogate"]),
                unsafe_allow_html=True)


def _render_counterfactuals(res):
    """§7.3 item 6. Routed through the monotonic XGBoost — see _explain."""
    uic.section("What would change this score")
    if res.get("cf_model") is None:
        uic.alert("info", "Simulation unavailable",
                  "The monotonically constrained model is not loaded. Simulation is "
                  "not run on the ensemble, because an unconstrained member can make "
                  "a protective change register as increased risk.")
        return
    rows = res.get("counterfactuals")
    if not rows:
        uic.alert("info", "No applicable interventions",
                  "None of the standard interventions apply to this patient — "
                  "proposing a change they cannot make is noise.")
        return
    st.markdown(ud.counterfactual_panel(rows, res["final_prob"],
                                        res["threshold"], res["cf_model"]),
                unsafe_allow_html=True)


def _render_downloads(res, user):
    txt = _text_report(res, user)
    a, b = st.columns(2)
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    with a:
        st.download_button("Download report (.txt)", txt,
                           file_name=f"heartguard_{res['p_id']}_{stamp}.txt",
                           mime="text/plain", width="stretch",
                           key="diag_dl_txt")
    with b:
        pdf, pdf_error = _pdf_report(res, user)
        if pdf is None:
            # Named, not swallowed. The first version of this returned a bare None on
            # any exception and rendered a disabled button, which hid two real key
            # mismatches against build_pdf_report's contract for an entire test cycle.
            st.button("Download report (PDF)", disabled=True,
                      width="stretch", key="diag_dl_pdf_off",
                      help=f"PDF generation failed: {pdf_error}")
        else:
            st.download_button("Download report (PDF)", pdf,
                               file_name=f"heartguard_{res['p_id']}_{stamp}.pdf",
                               mime="application/pdf", width="stretch",
                               key="diag_dl_pdf")


def _pdf_report(res, user):
    """
    The multi-page clinical PDF from Run 7, wired to the UI for the first time.

    The waterfall figure is rebuilt here rather than reused from the screen render:
    ui.charts.render closes every figure it draws, deliberately, because Streamlit
    reruns per keystroke and matplotlib keeps unclosed figures in a global registry.

    Returns (bytes_or_None, error_string). The key names below are build_pdf_report's,
    not this page's — `percentile['pct']` and `operating['band']` in particular — and
    getting either wrong produces a KeyError that a bare `except` turns into a
    permanently disabled button with no explanation. It did, for one test cycle.

    `_or_zero` exists because the report formats every rate with `:.1%`, and dict.get
    with a default returns None rather than the default when the key is PRESENT and
    None — which it is for any model whose threshold profile lacks NPV.
    """
    def _or_zero(v):
        return 0.0 if v is None else v

    try:
        sr = res["sub_rel"] or {}
        src = sr or res["thr_meta"] or {}
        wf = None
        if res.get("shap") is not None:
            vals, base = res["shap"]
            # theme='light': this copy is printed on white A4. Without the pin, a
            # dark-mode user exports a report whose chart is near-white on white.
            wf = cu.waterfall_figure(vals, base, _feature_names(),
                                     res["features"], res["final_prob"],
                                     theme="light")
        pdf = cu.build_pdf_report(
            meta={"patient_id": res["p_id"], "patient_name": res["p_name"],
                  "prepared_by": f"{user['fullname']} ({user['role']})",
                  "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "model": res["used_label"],
                  "model_version": res["version"]["version"],
                  "manifest_sha": res["version"]["manifest_sha"],
                  "notes": res["notes"] or "None"},
            indicators=res["inputs"],
            prediction={"probability": res["final_prob"],
                        "band": res["band_label"],
                        "action": res["band_action"],
                        "extrapolated": res["extrapolated"],
                        "applicability": res["app_warn"]},
            operating={"threshold": res["threshold"],
                       "band": res["age_band"],
                       "sensitivity": _or_zero(src.get("sensitivity")),
                       "specificity": _or_zero(src.get("specificity")),
                       "ppv": _or_zero(src.get("ppv")),
                       "npv": _or_zero(src.get("npv"))},
            reliability={"auc": _or_zero(sr.get("auc")),
                         "auc_ci_low": sr.get("auc_ci_low"),
                         "auc_ci_high": sr.get("auc_ci_high"),
                         "calibration_gap": _or_zero(sr.get("calibration_gap")),
                         "n": sr.get("n") or 0} if sr else None,
            waterfall_fig=wf,
            counterfactuals=res.get("counterfactuals"),
            percentile=(None if res["extrapolated"] or res["percentile"] is None
                        else {"pct": res["percentile"], "label": res["pct_label"],
                              "n": res["pct_n"]}))
        if wf is not None:
            plt.close(wf)
        return pdf, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _text_report(res, user):
    """
    The plain-text report, preserved. Every clinical sentence in it is unchanged from
    Run 7 — this is a record a clinician may already have filed, and rewording it
    would make two archived reports of the same assessment disagree.
    """
    i = res["inputs"]
    src = res["sub_rel"] or res["thr_meta"] or {}
    sr = res["sub_rel"] or {}
    chol_label = fe.CHOLESTEROL_LABELS.get(i["cholesterol"], str(i["cholesterol"]))
    gluc_label = fe.GLUCOSE_LABELS.get(i["gluc"], str(i["gluc"]))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    warn = ""
    if res["extrapolated"]:
        warn = ("*** WARNING - OUTSIDE MODEL APPLICABILITY ***\n"
                + "\n".join(
                    f"  {w['label']} = {w['value']:g} (model fitted on "
                    f"{w['supported'][0]:g}-{w['supported'][1]:g})"
                    for w in res["app_warn"] if w['severity'] == 'hard')
                + "\nThis risk estimate is an EXTRAPOLATION beyond the population the "
                  "model\nwas trained on. It has NOT been validated for this patient "
                  "and must not\nbe relied upon for a clinical decision. Peer "
                  "comparison was withheld.\n")
    peer = (f"higher than {res['percentile']}% of patients ({res['pct_label']})"
            if res["percentile"] is not None else "withheld (outside applicability)")
    ci = (f" (95% CI {sr['auc_ci_low']:.3f}-{sr['auc_ci_high']:.3f})"
          if sr.get("auc_ci_low") is not None else "")
    return f"""==================================================
HEARTGUARD AI - PATIENT RISK ASSESSMENT REPORT
==================================================
Date/Time  : {ts}
Prepared By: {user['fullname']} ({user['role']})
Patient ID : {res['p_id']}
Patient    : {res['p_name']}

CLINICAL INDICATORS:
--------------------
Age        : {i['age']} years
Gender     : {'Male' if i['gender'] == 1 else 'Female'}
Height     : {i['height']} cm
Weight     : {i['weight']} kg
Systolic BP: {i['ap_hi']} mmHg
Diastolic BP: {i['ap_lo']} mmHg
Cholesterol: {chol_label}
Glucose    : {gluc_label}
Smoker     : {'Yes' if i['smoke'] else 'No'}
Alcohol Use: {'Yes' if i['alco'] else 'No'}
Physically Active: {'Yes' if i['active'] else 'No'}

AI PREDICTION:
--------------
Model Used      : {res['used_label']}
Model Version   : {res['version']['version']} (dataset {res['version']['manifest_sha']})
Risk Probability: {res['final_prob']:.2%}
Risk Band       : {res['band_label']}{' [EXTRAPOLATED]' if res['extrapolated'] else ''}
Recommendation  : {res['band_action']}
Peer Comparison : {peer}

{warn}OPERATING POINT (age-stratified):
---------------------------------
Age band           : {res['age_band']}
Decision threshold : {res['threshold']:.3f}
Sensitivity        : {src.get('sensitivity', 0):.1%}
Specificity        : {src.get('specificity', 0):.1%}
PPV / NPV          : {src.get('ppv', 0):.1%} / {src.get('npv', 0):.1%}

MODEL RELIABILITY FOR THIS PATIENT GROUP:
-----------------------------------------
Discrimination     : AUC {sr.get('auc', 0):.3f}{ci}
Calibration gap    : {sr.get('calibration_gap', 0):+.3f}
Measured on        : {sr.get('n', 0):,} held-out patients

The threshold is stratified by age because baseline cardiovascular risk rises
steeply with age; a single cut-point would under-screen younger patients and
over-flag older ones.

This threshold is tuned for SCREENING sensitivity, not diagnostic accuracy.
It deliberately flags more patients for follow-up in order to reduce missed
cases. A positive result indicates the need for further testing, not disease.

Notes: {res['notes'] or 'None'}

DISCLAIMER: This report is AI-generated for clinical support only.
Final diagnosis must be confirmed by a licensed medical professional.
=================================================="""


def _ci_overlap(results, model_names):
    """
    One measured sentence about whether the AUC ranking is real.

    §7.5 asks for the bootstrap CIs to be rendered; rendering them without saying what
    they mean would leave the reader doing the comparison by eye, and by eye a 0.0001
    gap looks like a result. So this computes the actual overlap and reports it.

    Deliberately not a fixed disclaimer. If a retrain ever DOES separate two models,
    this sentence changes to say so — a caveat that is true regardless of the data is a
    caveat readers learn to skip.
    """
    spans = []
    for m in model_names:
        lo, hi = results[m].get("auc_ci_low"), results[m].get("auc_ci_high")
        if lo is not None and hi is not None:
            spans.append((results[m]["auc"], lo, hi, m))
    if len(spans) < 2:
        return "confidence intervals are unavailable for this run."
    spans.sort(reverse=True)
    (_, best_lo, best_hi, best_m) = spans[0]
    # Which models' intervals overlap the leader's? Overlapping intervals are not proof
    # of equivalence, but non-overlap is the weakest evidence of a real difference worth
    # quoting, and it is what a reader is implicitly assuming when they read the rank.
    overlapping = [m for (_a, lo, hi, m) in spans[1:] if lo <= best_hi and hi >= best_lo]
    if not overlapping:
        return (f"{best_m}'s interval {fmt.interval(best_lo, best_hi, fmt.auc)} does "
                f"not overlap any other model's, so its lead is measurable.")
    if len(overlapping) == len(spans) - 1:
        return (f"every model's interval overlaps {best_m}'s "
                f"{fmt.interval(best_lo, best_hi, fmt.auc)}, so the ranking is not "
                f"evidence that any one of them is better than another.")
    return (f"{len(overlapping)} of {len(spans) - 1} other models overlap {best_m}'s "
            f"interval {fmt.interval(best_lo, best_hi, fmt.auc)}; the ranking "
            f"separates only the rest.")


def _band_edges(model_label):
    """The three band cut-points for the rail, from thresholds.json."""
    rb = (load_thresholds().get("models", {}).get(model_label, {})
          .get("risk_bands", {}))
    return (rb.get("low_max", 0.25), rb.get("borderline_max", 0.35),
            rb.get("intermediate_max", 0.65))


def _band_key(band_label):
    lab = (band_label or "").lower()
    for key in ("borderline", "intermediate", "high", "low"):
        if key in lab:
            return key
    return "low"


def _target_sensitivity():
    return load_thresholds().get("policy", {}).get("target_sensitivity", 0.85)


def _overall_auc(model_label):
    return (load_results(include_virtual=True).get(model_label, {}) or {}).get("auc")


# ══════════════════════════════════════════════════════════════════
# PREDICTION HISTORY PAGE
# ══════════════════════════════════════════════════════════════════
def page_history(user):
    """
    §7.6's CRUD pattern: page_header → filter bar → data_table.

    Row-level scoping is unchanged: a Doctor sees only their own assessments, everyone
    else sees all. That is enforced by the `user_id` argument, not by a UI filter, and
    the filter bar below can only narrow what the query already returned.

    "Confidence" was the wrong word for the probability column and is now "Risk
    estimate". A calibrated probability is not the model's confidence in itself — 0.62
    means roughly 62 in 100 such patients have the outcome, not that the model is 62%
    sure. The old label invited exactly the misreading §3.10 forbids.
    """
    uic.page_header("Prediction history",
                    "Every recorded assessment, with the model and operating point "
                    "that produced it.")

    uid = user['id'] if user['role'] == 'Doctor' else None
    data = auth_db.get_predictions(user_id=uid)

    if not data:
        uic.empty_state(
            "No assessments recorded",
            "Open Heart Disease Prediction and run one. Saved assessments appear here "
            "with their model version, threshold and risk band."
            if user['role'] == 'Doctor' else
            "No assessment has been saved by any user yet.")
        return

    df = pd.DataFrame(data)
    df['Band'] = df.apply(
        lambda r: r.get('risk_band') or ("Flagged" if r['predicted_class'] == 1
                                         else "Below threshold"), axis=1)
    df['Estimate'] = df['probability'].apply(fmt.pct)
    # BUG-23's flag is persisted per row; surfacing it here is the whole point of
    # having stored it. A historical score taken outside the training envelope must
    # stay marked as one for as long as the record exists.
    if 'extrapolated' in df.columns:
        df['Applicability'] = df['extrapolated'].apply(
            lambda x: "Extrapolated" if x else "In envelope")

    with uic.panel("Filter"):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            search = st.text_input("Search patient or model", "",
                                   key="hist_search", label_visibility="collapsed",
                                   placeholder="Search patient or model")
        with c2:
            verdict_f = st.selectbox("Verdict", ["All", "Flagged", "Below threshold"],
                                     key="hist_verdict")
        with c3:
            model_f = st.selectbox(
                "Model", ["All"] + sorted(df['model_used'].dropna().unique().tolist()),
                key="hist_model")

    fdf = df.copy()
    if search:
        needle = search.lower()
        fdf = fdf[fdf.apply(
            lambda r: needle in str(r.get('patient_name', '')).lower()
            or needle in str(r['model_used']).lower(), axis=1)]
    if verdict_f == "Flagged":
        fdf = fdf[fdf['predicted_class'] == 1]
    elif verdict_f == "Below threshold":
        fdf = fdf[fdf['predicted_class'] == 0]
    if model_f != "All":
        fdf = fdf[fdf['model_used'] == model_f]

    cols = ['timestamp', 'patient_name', 'age', 'gender', 'Band', 'Estimate',
            'model_used']
    if 'Applicability' in fdf.columns:
        cols.append('Applicability')
    if user['role'] != 'Doctor' and 'doctor_name' in fdf.columns:
        cols.insert(2, 'doctor_name')

    st.caption(f"{fmt.count(len(fdf))} of {fmt.count(len(df))} assessments")
    if fdf.empty:
        uic.empty_state("Nothing matches these filters",
                        "Clear the search box or set the verdict and model back to All.")
        return

    uic.data_table(fdf[cols].rename(columns={
        'timestamp': 'Date', 'patient_name': 'Patient', 'age': 'Age',
        'gender': 'Gender', 'model_used': 'Model', 'doctor_name': 'Doctor'}))

    st.download_button("Export filtered rows (.csv)", fdf.to_csv(index=False).encode(),
                       f"predictions_{datetime.now().strftime('%Y%m%d')}.csv",
                       "text/csv", key="hist_csv")


# ══════════════════════════════════════════════════════════════════
# PROFILE PAGE
# ══════════════════════════════════════════════════════════════════
def page_profile(user):
    """
    §7.2's inline-validation pattern, reused: errors beneath the field they concern.

    Identity is shown read-only above the form. Username and role are not editable
    here by design — self-service role change is BUG-09, and it is worth stating on the
    page why the field a user might look for is absent.
    """
    uic.page_header("Profile", "Your account details and password.")

    left, right = st.columns([3, 2], gap="large")

    with left:
        err = st.session_state.get("profile_err", {})
        ok = st.session_state.pop("profile_ok", False)
        with uic.panel("Account"):
            if ok:
                uic.alert("success", "Profile updated",
                          "Your changes have been saved.")
            with st.form("profile_form"):
                new_full = st.text_input("Full name", value=user['fullname'])
                ui_login.inline_error(err.get("fullname"))
                new_email = st.text_input("Email", value=user['email'])
                ui_login.inline_error(err.get("email"))
                new_spec = st.text_input("Specialisation",
                                         value=user.get('specialisation', ''))
                new_pw = st.text_input("New password", type="password",
                                       placeholder="Leave blank to keep the current one")
                ui_login.inline_error(err.get("password"))
                saved = st.form_submit_button("Save changes", type="primary",
                                             width="stretch")
                if saved:
                    e = {}
                    if not new_full:
                        e["fullname"] = "Enter your full name."
                    if not new_email:
                        e["email"] = "Enter an email address."
                    # Matches the registration rule. A profile form that accepts a
                    # 3-character password silently undoes the minimum enforced at
                    # sign-up.
                    if new_pw and len(new_pw) < 6:
                        e["password"] = "Use at least 6 characters, or leave it blank."
                    if not e:
                        auth_db.update_user_profile(
                            user['id'], new_full, new_email, new_spec,
                            new_pw if new_pw else None)
                        st.session_state.user['fullname'] = new_full
                        st.session_state.user['email'] = new_email
                        st.session_state.user['specialisation'] = new_spec
                        st.session_state.profile_ok = True
                    st.session_state.profile_err = e
                    st.rerun()

    with right:
        with uic.panel("Identity"):
            st.markdown(
                '<div class="hg-result-id">'
                + uic.identifier(user['username'], "Username")
                + uic.identifier(user['role'], "Role")
                + '</div>', unsafe_allow_html=True)
            st.caption(
                "Username and role are not editable here. Role changes are made by a "
                "SuperAdmin through Role & Permission Management — self-service "
                "elevation was a real vulnerability in an earlier version.")


# ══════════════════════════════════════════════════════════════════
# HELP PAGE
# ══════════════════════════════════════════════════════════════════
def page_help():
    section_header("i", "Clinical Reference Guide", "Medical terminology used in this system")
    st.markdown("""
    <div class="panel">
    <h4 style="color:#60a5fa;">Feature Descriptions</h4>

    | Feature | Description | Normal Range |
    |---------|-------------|-------------|
    | **Age** | Patient's age in years | - |
    | **Systolic BP (ap_hi)** | Maximum blood pressure during heartbeat | < 120 mmHg |
    | **Diastolic BP (ap_lo)** | Minimum blood pressure between beats | < 80 mmHg |
    | **Cholesterol** | Blood cholesterol level | Normal / Above / Well Above |
    | **Glucose** | Blood glucose level | Normal / Above / Well Above |
    | **Smoke** | Whether patient is a smoker | - |
    | **Alcohol** | Regular alcohol consumption | - |
    | **Active** | Physically active lifestyle | - |

    </div>

    <div class="panel">
    <h4 style="color:#60a5fa;">AI Models Explained</h4>

    - **Logistic Regression** - Linear probabilistic classifier; fast and interpretable.
    - **SVM** - Finds optimal decision boundary; strong for complex patterns.
    - **Decision Tree** - Rule-based tree structure; highly interpretable.
    - **Random Forest** - Ensemble of 150 trees; robust against overfitting.
    - **XGBoost** - Gradient-boosted trees; top-performing ensemble method.
    - **Ensemble Voting** - Averages probabilities from ALL active models for maximum accuracy.
    </div>

    <div class="panel">
    <h4 style="color:#f87171;">Risk Interpretation</h4>

    - **Low Risk (< 50%)** - No significant cardiovascular risk patterns detected.
    - **Borderline (40-59%)** - Monitor patient; lifestyle advice recommended.
    - **High Risk (>= 60%)** - Immediate clinical review and advanced testing advised.
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# ADMIN — USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_admin_users(user):
    section_header("", "User Management", "View, manage, ban or delete system users")

    users = auth_db.get_all_users()
    df = pd.DataFrame(users)

    doctors = sum(1 for u in users if u['role'] == 'Doctor')
    admins = sum(1 for u in users if u['role'] == 'Admin')
    banned = sum(1 for u in users if u['is_banned'])

    st.markdown('<div class="hg-stat-grid" style="--hg-stat-cols:3;">' +
                kpi(len(users), "Total Users", "#60a5fa", "linear-gradient(135deg,#1e3a5f,#0f2544)", "#1e40af") +
                kpi(doctors, "Doctors", "#10b981", "linear-gradient(135deg,#0d2e1e,#071a10)", "#10b981") +
                kpi(admins, "Admins", "#a78bfa", "linear-gradient(135deg,#2d1f40,#180d2e)", "#a855f7") +
                kpi(banned, "Banned", "#f87171", "linear-gradient(135deg,#3b1f1f,#1e0d0d)", "#ef4444") +
                '</div>', unsafe_allow_html=True)

    show_df = df[['id', 'username', 'role', 'fullname', 'email', 'specialisation', 'is_banned', 'created_at']].copy()
    show_df['Status'] = show_df['is_banned'].apply(lambda x: "Banned" if x else "Active")
    st.dataframe(show_df.drop(columns=['is_banned']), hide_index=True, width="stretch")

    st.markdown("---")
    st.markdown("#### Manage User Account")

    others = [u for u in users if u['id'] != user['id']]
    if not others:
        st.info("No other users to manage.")
        return

    sel = st.selectbox("Select User",
                       [f"[{u['role']}] {u['fullname']} (@{u['username']}) - ID:{u['id']}" for u in others])
    t_uid = int(sel.split("ID:")[1])
    t_user = next(u for u in others if u['id'] == t_uid)

    can_manage = not (user['role'] == 'Admin' and t_user['role'] in ['Admin', 'SuperAdmin'])

    if not can_manage:
        st.markdown('<div class="alert-warning">Admins cannot manage Admin or SuperAdmin accounts.</div>',
                    unsafe_allow_html=True)
        return

    col1, col2 = st.columns(2)
    with col1:
        # Reversible, so no typed gate — but banning ends the target's session on their
        # next interaction (BUG-25), which is worth saying before it happens.
        if t_user['is_banned']:
            if st.button("Restore access", width="stretch",
                         key="admin_unban"):
                auth_db.unban_user(t_uid, user['username'])
                st.success(f"{t_user['username']} can sign in again.")
                st.rerun()
        else:
            if st.button("Suspend account", width="stretch",
                         key="admin_ban"):
                auth_db.ban_user(t_uid, user['username'])
                st.success(f"{t_user['username']} suspended and signed out.")
                st.rerun()
    with col2:
        new_role = st.selectbox("Role", ["Doctor", "Admin", "SuperAdmin"],
                                index=["Doctor", "Admin", "SuperAdmin"].index(t_user['role']),
                                key="admin_role")
        if st.button("Update role", width="stretch", key="admin_role_go"):
            auth_db.update_user_role(t_uid, new_role, user['username'])
            st.success(f"Role updated to {new_role}.")
            st.rerun()

    # §7.6: irreversible actions get a hairline danger panel and typed confirmation.
    # This used to be a bare `st.button("Delete Account")` in a third column, the same
    # size and weight as "Update Role" beside it.
    with uic.danger_zone(
            "Irreversible",
            f"Deleting {t_user['username']} removes the account and cascades to every "
            f"prediction it owns. There is no undo and no backup taken automatically."):
        if uic.destructive("Delete this account", t_user['username'], "admin_del"):
            auth_db.delete_user(t_uid, user['username'])
            st.success(f"Account {t_user['username']} deleted.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# ADMIN — ANALYTICS DASHBOARD
# ══════════════════════════════════════════════════════════════════
def page_admin_analytics(user):
    section_header("", "System Analytics",
                   "Platform-wide statistics, model performance and prediction trends")

    all_preds = auth_db.get_predictions()
    all_users = auth_db.get_all_users()
    results = load_results()

    risk_c = sum(1 for p in all_preds if p['predicted_class'] == 1)
    safe_c = len(all_preds) - risk_c

    st.markdown('<div class="hg-stat-grid" style="--hg-stat-cols:3;">' +
                kpi(len(all_preds), "Total Predictions", "#60a5fa", "linear-gradient(135deg,#1e3a5f,#0f2544)", "#1e40af") +
                kpi(risk_c, "High Risk Cases", "#ef4444", "linear-gradient(135deg,#3b1f1f,#1e0d0d)", "#ef4444") +
                kpi(safe_c, "Low Risk Cases", "#10b981", "linear-gradient(135deg,#0d2e1e,#071a10)", "#10b981") +
                kpi(len(all_users), "Total Users", "#a855f7", "linear-gradient(135deg,#2d1f40,#180d2e)", "#a855f7") +
                '</div>', unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs(["Prediction Trends", "Model Performance",
                               "User Overview", "Activity Logs"])

    with t1:
        if all_preds:
            pdf = pd.DataFrame(all_preds)
            pdf['date'] = pd.to_datetime(pdf['timestamp']).dt.date

            fig, axes = plt.subplots(1, 2, figsize=(12, 4), facecolor='none')
            ax = axes[0]
            ax.set_facecolor('none')
            vals = [risk_c, safe_c]
            clrs = [ucharts.color('risk_high'), ucharts.color('risk_low')]
            wedges, _, autotexts = ax.pie(vals, colors=clrs, autopct='%1.1f%%',
                                          startangle=90, pctdistance=0.75,
                                          wedgeprops=dict(width=0.5))
            for at in autotexts:
                at.set_color('white')
                at.set_fontsize(9)
            ax.set_title('Risk Distribution', color=ucharts.color('fg'), pad=12)
            patches = [mpatches.Patch(color=ucharts.color('risk_high'), label='High Risk'),
                       mpatches.Patch(color=ucharts.color('risk_low'), label='Low Risk')]
            ax.legend(handles=patches, loc='lower center', facecolor=ucharts.color('surface'),
                      labelcolor=ucharts.color('fg'), framealpha=0.5, fontsize=8)

            ax2 = axes[1]
            ax2.set_facecolor('none')
            mu = pdf['model_used'].value_counts()
            bars = ax2.barh(mu.index, mu.values, color=ucharts.color('primary'), height=0.5)
            ax2.set_title('Model Usage', color=ucharts.color('fg'), pad=12)
            ax2.tick_params(colors=ucharts.color('axis'), labelsize=8)
            for sp in ax2.spines.values():
                sp.set_color(ucharts.color('spine'))
            for bar in bars:
                ax2.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                         str(int(bar.get_width())), va='center', color=ucharts.color('fg'), fontsize=8)
            plt.tight_layout()
            st.pyplot(fig, transparent=True)
            plt.close()
        else:
            st.info("No prediction data yet.")

    with t2:
        if results:
            rows = []
            for name, d in results.items():
                rows.append({"Model": name,
                             "Accuracy": f"{d['accuracy']:.2%}",
                             "AUC": f"{d['auc']:.3f}",
                             "F1 Score": f"{d.get('f1', 0):.3f}",
                             "Precision": f"{d.get('precision', 0):.3f}",
                             "Recall": f"{d.get('recall', 0):.3f}"})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

            fig2, ax3 = plt.subplots(figsize=(9, 3.5), facecolor='none')
            ax3.set_facecolor('none')
            names = [r['Model'] for r in rows]
            accs = [float(r['Accuracy'].strip('%')) / 100 for r in rows]
            bars = ax3.bar(names, accs,
                           color=[ucharts.series_color(n) for n in names], width=0.45)
            ax3.set_ylim(0, 1.05)
            ax3.set_title("Model Accuracy Comparison", color=ucharts.color('fg'), pad=10)
            ax3.tick_params(colors=ucharts.color('axis'), labelsize=7)
            for sp in ax3.spines.values():
                sp.set_color(ucharts.color('spine'))
            ax3.spines['top'].set_visible(False)
            ax3.spines['right'].set_visible(False)
            for bar in bars:
                ax3.annotate(f"{bar.get_height():.1%}",
                             xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                             xytext=(0, 4), textcoords="offset points",
                             ha='center', color=ucharts.color('fg'), fontsize=8)
            plt.tight_layout()
            st.pyplot(fig2, transparent=True)
            plt.close()
        else:
            st.info("No model results found. Ask SuperAdmin to train models.")

    with t3:
        udf = pd.DataFrame(all_users)
        if not udf.empty:
            udf['Status'] = udf['is_banned'].apply(lambda x: "Banned" if x else "Active")
            st.dataframe(udf[['id', 'username', 'role', 'fullname', 'email', 'Status', 'created_at']],
                         hide_index=True, width="stretch")

    with t4:
        logs = auth_db.get_system_logs(100)
        if logs:
            st.dataframe(pd.DataFrame(logs)[['timestamp', 'username', 'action', 'details']],
                         hide_index=True, width="stretch")


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — MODEL TRAINING
# ══════════════════════════════════════════════════════════════════
def page_training(user):
    section_header("", "ML Model Management", "Train, compare and configure AI classification models")

    ta, tb, tc, td = st.tabs(["Train Models", "Enable/Disable Models",
                               "Performance Leaderboard", "Training History"])

    with ta:
        st.markdown("#### Dataset Configuration")
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        current_data = DATA_PATH
        st.markdown(f"**Active Dataset:** `{os.path.basename(current_data)}`"
                    f" ({'Found' if os.path.exists(current_data) else 'Missing'})")

        uploaded = st.file_uploader("Upload Custom Dataset (CSV)", type="csv")
        if uploaded:
            try:
                udf = pd.read_csv(uploaded)
                st.success(f"Preview: {udf.shape[0]} rows x {udf.shape[1]} columns")
                st.dataframe(udf.head(5), width="stretch")
                custom_path = os.path.join(BASE_DIR, "custom_dataset.csv")
                if st.button("Use This Dataset for Training"):
                    udf.to_csv(custom_path, index=False)
                    st.success("Custom dataset saved. Will be used in next training run.")
            except Exception as e:
                st.error(f"Error reading file: {e}")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown("#### Trigger Model Training")
        custom_path = os.path.join(BASE_DIR, "custom_dataset.csv")
        if os.path.exists(custom_path):
            st.markdown('<div class="alert-info">Custom dataset detected - training will use it.</div>',
                        unsafe_allow_html=True)

        if st.button("Start Full Training Pipeline", width="stretch"):
            with st.spinner("Training all 5 models... this may take a few minutes."):
                t0 = time.time()
                script = os.path.join(BASE_DIR, "train_models.py")
                try:
                    # FIXED (BUG-16): use the interpreter actually running Streamlit.
                    # Bare "python" resolved from PATH, so launching the app outside an
                    # activated venv silently trained with a different interpreter —
                    # degrading XGBoost to GradientBoosting or failing outright.
                    res = subprocess.run([sys.executable, script], capture_output=True,
                                         text=True, cwd=BASE_DIR, timeout=600)
                    dur = round(time.time() - t0, 1)
                    if res.returncode == 0:
                        results = load_results()
                        auth_db.log_training_run(user['id'], "success", dur, json.dumps(results))
                        auth_db.log_activity(user['id'], user['username'],
                                             "Model Training", f"Training completed in {dur}s.")
                        st.cache_resource.clear()
                        st.success(f"Training complete in {dur}s! All models updated.")
                        st.code(res.stdout[-3000:] if len(res.stdout) > 3000 else res.stdout)
                    else:
                        st.error(f"Training failed (exit {res.returncode})")
                        st.code(res.stderr[-2000:])
                except subprocess.TimeoutExpired:
                    st.error("Training timed out after 10 minutes.")
                except Exception as e:
                    st.error(f"Error: {e}")

    with tb:
        st.markdown("#### Active Model Configuration")
        cfg = load_config()
        updated = {}
        for mname in ["Logistic Regression", "Support Vector Machine (SVM)",
                       "Decision Tree", "Random Forest", "XGBoost"]:
            col_a, col_b = st.columns([3, 1])
            with col_a:
                enabled = st.checkbox(f"Enable **{mname}**", value=cfg.get(mname, True), key=f"chk_{mname}")
            with col_b:
                results = load_results()
                if mname in results:
                    st.markdown(f"<small style='color:#64748b;'>Acc: {results[mname]['accuracy']:.1%}</small>",
                                unsafe_allow_html=True)
            updated[mname] = enabled
        if st.button("Save Configuration", width="stretch"):
            save_config(updated)
            auth_db.log_activity(user['id'], user['username'],
                                 "Config Update", "Model enable/disable config saved.")
            st.success("Configuration saved!")
            time.sleep(0.5)
            st.rerun()

    with tc:
        results = load_results()
        if results:
            rows = sorted([{"Model": n,
                            "Accuracy": d['accuracy'],
                            "AUC": d['auc'],
                            "F1": d.get('f1', 0),
                            "Precision": d.get('precision', 0),
                            "Recall": d.get('recall', 0),
                            "Status": "Active" if load_config().get(n, True) else "Disabled"}
                           for n, d in results.items()],
                          key=lambda x: x['Accuracy'], reverse=True)
            display = pd.DataFrame(rows)
            display['Accuracy'] = display['Accuracy'].apply(lambda x: f"{x:.2%}")
            display['AUC'] = display['AUC'].apply(lambda x: f"{x:.4f}")
            display['F1'] = display['F1'].apply(lambda x: f"{x:.4f}")
            display['Precision'] = display['Precision'].apply(lambda x: f"{x:.4f}")
            display['Recall'] = display['Recall'].apply(lambda x: f"{x:.4f}")
            st.dataframe(display, hide_index=True, width="stretch")

            fig, ax = plt.subplots(figsize=(11, 4), facecolor='none')
            ax.set_facecolor('none')
            x = np.arange(len(rows))
            w = 0.18
            _mc = ucharts.categorical(5)
            metrics = list(zip(['Accuracy', 'AUC', 'F1', 'Precision', 'Recall'], _mc))
            for i, (met, col) in enumerate(metrics):
                vals = [results[r['Model']][met.lower()] for r in rows]
                ax.bar(x + i * w, vals, w, label=met, color=col, alpha=0.9)
            ax.set_xticks(x + w * 2)
            ax.set_xticklabels([r['Model'].replace("(", "\n(") for r in rows],
                               color=ucharts.color('fg'), fontsize=7)
            ax.set_ylim(0, 1.1)
            ax.tick_params(colors=ucharts.color('axis'))
            ax.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=8, loc='lower right')
            ax.set_title("Model Metric Comparison", color=ucharts.color('fg'), pad=10)
            for sp in ax.spines.values():
                sp.set_color(ucharts.color('spine'))
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            plt.tight_layout()
            st.pyplot(fig, transparent=True)
            plt.close()
        else:
            st.info("No results found. Train models first.")

    with td:
        runs = auth_db.get_training_runs()
        if runs:
            st.dataframe(pd.DataFrame(runs)[['timestamp', 'status', 'duration_s']].rename(
                columns={'timestamp': 'Date/Time', 'status': 'Status', 'duration_s': 'Duration (s)'}),
                         hide_index=True, width="stretch")
        else:
            st.info("No training runs recorded yet.")


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — SYSTEM AUDITS
# ══════════════════════════════════════════════════════════════════
def page_audits(user):
    section_header("", "Activity Logs", "Full audit trail, logs, and database management tools")

    ta, tb = st.tabs(["Activity Audit Log", "Data Management"])

    with ta:
        logs = auth_db.get_system_logs(200)
        if logs:
            ldf = pd.DataFrame(logs)
            actions = ["All"] + sorted(ldf['action'].unique().tolist())
            af = st.selectbox("Filter by Action", actions)
            sf = st.text_input("Search by Username", "")

            fdf = ldf.copy()
            if af != "All":
                fdf = fdf[fdf['action'] == af]
            if sf:
                fdf = fdf[fdf['username'].str.lower().str.contains(sf.lower(), na=False)]

            st.dataframe(fdf[['timestamp', 'username', 'action', 'details']],
                         hide_index=True, width="stretch")
            csv = fdf.to_csv(index=False).encode()
            st.download_button("Export Logs", csv,
                               f"audit_log_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
        else:
            st.info("No audit records found.")

    with tb:
        # These two were bare, adjacent, unguarded buttons — and the Phase 4 deep test
        # destroyed the entire fixture database by clicking them in sequence. If an
        # automated sweep can wipe the system by accident, so can a person.
        #
        # Both now require the exact phrase typed, and the counts are stated first: a
        # confirmation that does not say HOW MUCH is about to go is not informed consent.
        _n_preds = len(auth_db.get_predictions())
        _n_logs = len(auth_db.get_system_logs(limit=100000))
        uic.section("Data management")
        with uic.danger_zone(
                "Irreversible — no automatic backup",
                "Take a backup from Backup & Restore first if there is any doubt. "
                "Neither operation can be undone from inside the application."):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    f'<p class="hg-note"><b>Delete every assessment.</b> '
                    f'{fmt.count(_n_preds)} records, including their model versions, '
                    f'thresholds and applicability flags. Patient rows remain.</p>',
                    unsafe_allow_html=True)
                if uic.destructive("Delete all assessments", "DELETE ASSESSMENTS",
                                   "danger_preds"):
                    auth_db.clear_all_predictions(user['username'])
                    st.success(f"{fmt.count(_n_preds)} assessments deleted.")
                    st.rerun()
            with col2:
                st.markdown(
                    f'<p class="hg-note"><b>Purge the audit trail.</b> '
                    f'{fmt.count(_n_logs)} entries. This is the record of who did what, '
                    f'including the purge itself.</p>',
                    unsafe_allow_html=True)
                if uic.destructive("Purge audit log", "PURGE AUDIT LOG",
                                   "danger_logs"):
                    auth_db.clear_system_logs(user['username'])
                    st.success(f"{fmt.count(_n_logs)} log entries purged.")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════
# ALL ROLES — MODEL PERFORMANCE & EVALUATION
# ══════════════════════════════════════════════════════════════════
def page_model_performance(user):
    section_header("", "Model Performance",
                   "Detailed evaluation metrics, confusion matrices and model comparisons")
    results = load_results()
    if not results:
        st.markdown('<div class="alert-warning">No model results found. Ask SuperAdmin to train models first.</div>',
                    unsafe_allow_html=True)
        return

    model_names = list(results.keys())
    # FIXED (BUG-19): short names and colours keyed by model name, not list position.
    # Previously these were zipped positionally against results.json's keys, so a
    # partial training run silently labelled every chart with the wrong model's name.
    short_names = [MODEL_SHORT_NAMES.get(m, m[:3].upper()) for m in model_names]
    colors_bar  = [ucharts.series_color(m) for m in model_names]
    accs  = [results[m]['accuracy']  for m in model_names]
    aucs  = [results[m]['auc']       for m in model_names]
    f1s   = [results[m]['f1']        for m in model_names]
    precs = [results[m]['precision'] for m in model_names]
    recs  = [results[m]['recall']    for m in model_names]
    best_idx  = aucs.index(max(aucs))
    best_name = model_names[best_idx]

    # The trophy banner is gone. A gold-medal emoji beside a leader whose confidence
    # interval overlaps every other model's is a celebration of noise, and §3.10 puts
    # AUC with its interval in the headline slot rather than an award.
    _best_lo = results[best_name].get("auc_ci_low")
    _best_hi = results[best_name].get("auc_ci_high")
    uic.stat_grid([
        {"label": "Leading model", "value": MODEL_SHORT_NAMES.get(best_name, best_name),
         "hint": best_name},
        {"label": "Discrimination", "value": fmt.auc(aucs[best_idx]),
         "hint": (fmt.interval(_best_lo, _best_hi, fmt.auc)
                  if _best_lo is not None else "no interval for this run")},
        {"label": "Sensitivity at operating point", "value": fmt.metric3(max(recs)),
         "hint": "the metric a screening tool is chosen on"},
        {"label": "Models compared", "value": fmt.count(len(model_names))},
    ])
    # Accuracy is deliberately NOT in the strip. §3.10 forbids it as a headline: at this
    # dataset's near-balanced prevalence a 0.70 accuracy tells a reader almost nothing,
    # and it was the largest number on the page. It remains in the table below.
    # ── §7.5: eleven horizontal tabs become four groups ──────────────
    # Eleven items is a navigation failure: no tab bar survives it, labels truncate and
    # nobody discovers anything past tab six. The grouping below is verbatim from §7.5.
    #
    # It is also a large performance win. st.tabs renders EVERY body on every run, so
    # all eleven used to execute on each page load — measured at 24.5s. Only the active
    # group's bodies run now, which is why each is behind `if label in _slot` rather
    # than merely being handed a different container.
    _GROUPS = {
        "Performance": ["Metric Comparison", "Confusion Matrices",
                        "Detailed Report", "ROC & PR Curves"],
        "Validation": ["K-Fold CV", "Subgroup Performance & Fairness"],
        "Clinical": ["Threshold & Clinical Utility",
                     "Clinical Benchmark & Feature Value"],
        "Explainability": ["Feature Importance", "Explainable AI (SHAP)",
                           "Model Info"],
    }
    with st.container(key="perf-groups"):
        _group = st.segmented_control(
            "Section", list(_GROUPS), default="Performance",
            key="perf_group", label_visibility="collapsed") or "Performance"
    _labels = _GROUPS[_group]
    _slot = dict(zip(_labels, st.tabs(_labels)))

    if 'Metric Comparison' in _slot:
        with _slot['Metric Comparison']:
        # ── Collect timing data (graceful fallback if not in results) ──
            train_times = [results[m].get("training_time_s", 0.0) for m in model_names]
            pred_times  = [results[m].get("pred_time_ms",    0.0) for m in model_names]
            has_timing  = any(t > 0 for t in train_times)

            # ── Build full comparison table ────────────────────────────────
            best_acc_idx  = accs.index(max(accs))
            best_auc_idx  = aucs.index(max(aucs))
            best_f1_idx   = f1s.index(max(f1s))
            best_prec_idx = precs.index(max(precs))
            best_rec_idx  = recs.index(max(recs))
            fast_train    = train_times.index(min(train_times)) if has_timing else -1
            fast_pred     = pred_times.index(min(pred_times))   if has_timing else -1

            def _tag(i, best_i, fmt_val):
                return f"{fmt_val} ★" if i == best_i else fmt_val

            table_rows = []
            for i, mn in enumerate(model_names):
                row = {
                    "Model":            mn,
                    "Accuracy":         _tag(i, best_acc_idx,  f"{accs[i]:.4f} ({accs[i]:.1%})"),
                    "Precision":        _tag(i, best_prec_idx, f"{precs[i]:.4f}"),
                    "Recall":           _tag(i, best_rec_idx,  f"{recs[i]:.4f}"),
                    "F1 Score":         _tag(i, best_f1_idx,   f"{f1s[i]:.4f}"),
                    "ROC AUC":          _tag(i, best_auc_idx,  f"{aucs[i]:.4f}"),
                }
                # §7.5: render the bootstrap CIs. They have been computed and stored
                # since Run 4 and shown nowhere — so the table invited reading a
                # 0.0001 gap between two models as a real difference. The intervals
                # overlap almost completely, which is the actual finding.
                _lo = results[mn].get("auc_ci_low")
                _hi = results[mn].get("auc_ci_high")
                row["AUC 95% CI"] = (fmt.interval(_lo, _hi, fmt.auc)
                                     if _lo is not None and _hi is not None else "—")
                if has_timing:
                    row["Train Time (s)"]  = _tag(i, fast_train, f"{train_times[i]:.2f}s")
                    row["Pred Time (ms)"]  = _tag(i, fast_pred,  f"{pred_times[i]:.1f} ms/1k")
                row["Rank (AUC)"] = aucs.index(aucs[i]) + 1 if False else \
                                     sorted(range(len(aucs)), key=lambda x: aucs[x],
                                            reverse=True).index(i) + 1
                table_rows.append(row)

            uic.section("Complete model comparison")
            # The ★ tells you which value is largest. The CI column tells you whether
            # that means anything — and here it usually does not. Stating the overlap
            # explicitly is the difference between a ranking and a finding.
            _overlap = _ci_overlap(results, model_names)
            uic.alert(
                "info", "How to read this table",
                "★ marks the largest value in a column. Read the AUC interval before "
                "the rank: " + _overlap + " Train time is seconds to fit; prediction "
                "time is milliseconds per 1,000 samples.")
            uic.data_table(pd.DataFrame(table_rows))

            # Export button
            export_df = pd.DataFrame([{
                "Model": mn,
                "Accuracy": accs[i], "Precision": precs[i], "Recall": recs[i],
                "F1 Score": f1s[i],  "ROC AUC":  aucs[i],
                "AUC CI low": results[mn].get("auc_ci_low"),
                "AUC CI high": results[mn].get("auc_ci_high"),
                "Train Time (s)": train_times[i] if has_timing else "N/A",
                "Pred Time (ms)": pred_times[i]  if has_timing else "N/A",
            } for i, mn in enumerate(model_names)])
            st.download_button(
                "Export comparison table (.csv)",
                export_df.to_csv(index=False).encode(),
                f"model_comparison_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv", key="perf_cmp_csv")

            # ── CHART 1: Grouped bar — Accuracy/AUC/F1/Precision/Recall ──
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("**Accuracy / AUC / F1 per Model**")
                fig, ax = plt.subplots(figsize=(6, 4), facecolor='none')
                ax.set_facecolor('none')
                x = range(len(model_names))
                w = 0.18
                # Categorical, not clinical: these are five metrics, and 3.10 reserves
                # the risk hues for clinical meaning.
                _mg = ucharts.categorical(5)
                metrics_grp = list(zip([accs, aucs, f1s, precs, recs], _mg,
                                       ['Accuracy', 'AUC', 'F1', 'Precision', 'Recall']))
                offsets = [-2*w, -w, 0, w, 2*w]
                for (vals, col, lbl), off in zip(metrics_grp, offsets):
                    bars = ax.bar([i + off for i in x], vals,
                                  width=w, label=lbl, color=col, alpha=0.88)
                    for bar in bars:
                        ax.annotate(f"{bar.get_height():.2f}",
                                    xy=(bar.get_x()+bar.get_width()/2, bar.get_height()),
                                    xytext=(0, 2), textcoords="offset points",
                                    ha='center', color=ucharts.color('fg'), fontsize=5.5, fontweight='600')
                ax.set_xticks(list(x))
                ax.set_xticklabels(short_names, color=ucharts.color('fg'), fontsize=9)
                ax.set_ylim(0, 1.14)
                ax.tick_params(colors=ucharts.color('fg'), labelsize=8)
                ax.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=7,
                          loc='upper right', ncol=2)
                for sp in ['top', 'right']:   ax.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax.spines[sp].set_color(ucharts.color('spine'))
                ax.grid(True, axis='y', color=ucharts.color('surface'), linestyle='--',
                        linewidth=0.5, alpha=0.6)
                plt.tight_layout()
                st.pyplot(fig, transparent=True)
                plt.close()

            with col_r:
                st.markdown("**AUC Ranking**")
                si = sorted(range(len(aucs)), key=lambda i: aucs[i], reverse=True)
                fig2, ax2 = plt.subplots(figsize=(6, 4), facecolor='none')
                ax2.set_facecolor('none')
                bar_h = ax2.barh([model_names[i] for i in si], [aucs[i] for i in si],
                                 color=[colors_bar[i] for i in si], height=0.5)
                ax2.set_xlim(0, 1.05)
                ax2.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top', 'right']:   ax2.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax2.spines[sp].set_color(ucharts.color('spine'))
                for bar in bar_h:
                    ax2.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                             f"{bar.get_width():.4f}", va='center',
                             color=ucharts.color('fg'), fontsize=8, fontweight='600')
                plt.tight_layout()
                st.pyplot(fig2, transparent=True)
                plt.close()

            st.markdown("---")

            # ── CHART 2: Radar / Spider chart ─────────────────────────────
            st.markdown("**Radar Chart — All Metrics per Model**")
            radar_metrics = ['Accuracy', 'Precision', 'Recall', 'F1', 'AUC']
            radar_vals_all = [[accs[i], precs[i], recs[i], f1s[i], aucs[i]]
                              for i in range(len(model_names))]
            angles = np.linspace(0, 2 * np.pi, len(radar_metrics),
                                 endpoint=False).tolist()
            angles += angles[:1]   # close the polygon

            fig_r, ax_r = plt.subplots(figsize=(6, 5),
                                       subplot_kw=dict(polar=True),
                                       facecolor='none')
            ax_r.set_facecolor('none')
            for i, (mn, rv) in enumerate(zip(model_names, radar_vals_all)):
                vals = rv + rv[:1]
                ax_r.plot(angles, vals, color=colors_bar[i],
                          linewidth=2, label=short_names[i])
                ax_r.fill(angles, vals, color=colors_bar[i], alpha=0.10)

            ax_r.set_thetagrids(np.degrees(angles[:-1]), radar_metrics,
                                color=ucharts.color('fg'), fontsize=9)
            ax_r.set_ylim(0, 1)
            ax_r.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
            ax_r.set_yticklabels(['0.2','0.4','0.6','0.8','1.0'],
                                  color=ucharts.color('fg_subtle'), fontsize=7)
            ax_r.grid(color=ucharts.color('grid'), linestyle='--', linewidth=0.6)
            ax_r.spines['polar'].set_color(ucharts.color('spine'))
            ax_r.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'),
                        fontsize=9, loc='upper right', bbox_to_anchor=(1.35, 1.1))
            plt.tight_layout()
            st.pyplot(fig_r, transparent=True)
            plt.close()

            st.markdown("---")

            # ── CHART 3: Training & Prediction Time ───────────────────────
            if has_timing:
                st.markdown("**Training Time vs Prediction Time**")
                fig_t, (ax_t1, ax_t2) = plt.subplots(1, 2, figsize=(10, 3.5),
                                                       facecolor='none')
                for ax_t in [ax_t1, ax_t2]:
                    ax_t.set_facecolor('none')

                # Training time bar
                bt = ax_t1.bar(short_names, train_times,
                               color=colors_bar[:len(model_names)], alpha=0.88)
                ax_t1.set_title("Train Time (seconds)", color=ucharts.color('fg'),
                                fontsize=9, fontweight='700')
                ax_t1.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top','right']:   ax_t1.spines[sp].set_visible(False)
                for sp in ['left','bottom']: ax_t1.spines[sp].set_color(ucharts.color('spine'))
                ax_t1.grid(True, axis='y', color=ucharts.color('surface'), linestyle='--',
                           linewidth=0.5, alpha=0.6)
                for bar in bt:
                    ax_t1.annotate(f"{bar.get_height():.2f}s",
                                   xy=(bar.get_x()+bar.get_width()/2, bar.get_height()),
                                   xytext=(0, 3), textcoords="offset points",
                                   ha='center', color=ucharts.color('fg'), fontsize=7.5)

                # Prediction time bar
                bp2 = ax_t2.bar(short_names, pred_times,
                                color=colors_bar[:len(model_names)], alpha=0.88)
                ax_t2.set_title("Pred Time (ms / 1,000 samples)", color=ucharts.color('fg'),
                                fontsize=9, fontweight='700')
                ax_t2.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top','right']:   ax_t2.spines[sp].set_visible(False)
                for sp in ['left','bottom']: ax_t2.spines[sp].set_color(ucharts.color('spine'))
                ax_t2.grid(True, axis='y', color=ucharts.color('surface'), linestyle='--',
                           linewidth=0.5, alpha=0.6)
                for bar in bp2:
                    ax_t2.annotate(f"{bar.get_height():.1f}ms",
                                   xy=(bar.get_x()+bar.get_width()/2, bar.get_height()),
                                   xytext=(0, 3), textcoords="offset points",
                                   ha='center', color=ucharts.color('fg'), fontsize=7.5)
                plt.tight_layout()
                st.pyplot(fig_t, transparent=True)
                plt.close()
            else:
                st.markdown(
                    '<div class="alert-warning">Training/Prediction time data not available. '
                'Re-train models to capture timing metrics.</div>',
                    unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("**Precision vs Recall**")
            fig3, ax3 = plt.subplots(figsize=(7, 4), facecolor='none')
            ax3.set_facecolor('none')
            for i, m in enumerate(model_names):
                ax3.scatter(recs[i], precs[i], color=colors_bar[i], s=120, zorder=5,
                            edgecolors=ucharts.color('surface'), linewidths=0.5)
                ax3.annotate(short_names[i], (recs[i]+0.003, precs[i]+0.003),
                             color=colors_bar[i], fontsize=9, fontweight='700')
            ax3.set_xlabel("Recall", color=ucharts.color('fg'), fontsize=9)
            ax3.set_ylabel("Precision", color=ucharts.color('fg'), fontsize=9)
            ax3.tick_params(colors=ucharts.color('fg'), labelsize=8)
            for sp in ['top', 'right']:   ax3.spines[sp].set_visible(False)
            for sp in ['left', 'bottom']: ax3.spines[sp].set_color(ucharts.color('spine'))
            ax3.set_xlim(0.3, 1.05)
            ax3.set_ylim(0.3, 1.05)
            ax3.grid(True, color=ucharts.color('surface'), linestyle='--', linewidth=0.5, alpha=0.6)
            plt.tight_layout()
            st.pyplot(fig3, transparent=True)
            plt.close()


    if 'Confusion Matrices' in _slot:
        with _slot['Confusion Matrices']:
            st.markdown("#### Confusion Matrices — All Models")
            st.markdown('<div class="alert-info">0 = Low Risk (No Disease), 1 = High Risk (Disease)</div>',
                        unsafe_allow_html=True)
            cols_cm = st.columns(len(model_names))
            sens_list, spec_list = [], []
            for idx, (mn, col) in enumerate(zip(model_names, cols_cm)):
                cm = results[mn]['conf_matrix']
                tn, fp = cm[0][0], cm[0][1]
                fn, tp = cm[1][0], cm[1][1]
                sens = tp / (tp + fn) if (tp + fn) else 0
                spec = tn / (tn + fp) if (tn + fp) else 0
                sens_list.append(sens)
                spec_list.append(spec)
                with col:
                    st.markdown(f"**{short_names[idx]}**")
                    fig_cm, ax_cm = plt.subplots(figsize=(2.6, 2.2), facecolor='none')
                    ax_cm.set_facecolor('none')
                    cm_arr = [[tn, fp], [fn, tp]]
                    _im_cm = ax_cm.imshow(cm_arr, cmap=ucharts.cmap('sequential', reverse=True),
                                          aspect='auto', vmin=0)
                    for r in range(2):
                        for c_ in range(2):
                            ax_cm.text(c_, r, str(cm_arr[r][c_]),
                                       ha='center', va='center',
                                       color=ucharts.on_color(_im_cm.cmap(_im_cm.norm(cm_arr[r][c_]))),
                                       fontsize=10, fontweight='700')
                    ax_cm.set_xticks([0, 1])
                    ax_cm.set_yticks([0, 1])
                    ax_cm.set_xticklabels(['P0', 'P1'], color=ucharts.color('fg'), fontsize=7)
                    ax_cm.set_yticklabels(['A0', 'A1'], color=ucharts.color('fg'), fontsize=7)
                    ax_cm.tick_params(length=0)
                    plt.tight_layout(pad=0.3)
                    st.pyplot(fig_cm, transparent=True)
                    plt.close()
                    st.markdown(f"""<div style="font-size:.72em;color:#6b7280;line-height:1.6;">
                TP={tp} TN={tn} FP={fp} FN={fn}<br>
                Sens:<b style="color:#10b981"> {sens:.1%}</b>
                Spec:<b style="color:#3b82f6"> {spec:.1%}</b></div>""", unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("#### Sensitivity vs Specificity")
            fig_ss, ax_ss = plt.subplots(figsize=(8, 3.5), facecolor='none')
            ax_ss.set_facecolor('none')
            xr = range(len(model_names))
            w = 0.35
            bs = ax_ss.bar([i - w/2 for i in xr], sens_list, width=w, label='Sensitivity', color=ucharts.color('risk_high'), alpha=0.85)
            bp = ax_ss.bar([i + w/2 for i in xr], spec_list, width=w, label='Specificity',  color=ucharts.color('primary'), alpha=0.85)
            ax_ss.set_xticks(list(xr))
            ax_ss.set_xticklabels(short_names, color=ucharts.color('fg'), fontsize=9)
            ax_ss.set_ylim(0, 1.15)
            ax_ss.tick_params(colors=ucharts.color('fg'), labelsize=8)
            ax_ss.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=9)
            for sp in ['top', 'right']:   ax_ss.spines[sp].set_visible(False)
            for sp in ['left', 'bottom']: ax_ss.spines[sp].set_color(ucharts.color('spine'))
            for bar in list(bs) + list(bp):
                ax_ss.annotate(f"{bar.get_height():.2f}",
                               xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                               xytext=(0, 3), textcoords="offset points",
                               ha='center', color=ucharts.color('fg'), fontsize=7.5, fontweight='600')
            plt.tight_layout()
            st.pyplot(fig_ss, transparent=True)
            plt.close()

    if 'Detailed Report' in _slot:
        with _slot['Detailed Report']:
            st.markdown("#### Per-Class Classification Report")
            sel_m = st.selectbox("Select Model", model_names)
            rep   = results[sel_m].get('report', {})
            rows  = []
            for cls_key, cls_label in [("0", "Low Risk (Class 0)"), ("1", "High Risk (Class 1)"),
                                        ("macro avg", "Macro Average"), ("weighted avg", "Weighted Average")]:
                if cls_key in rep:
                    d = rep[cls_key]
                    rows.append({"Class": cls_label,
                                 "Precision": f"{d.get('precision',0):.4f}",
                                 "Recall":    f"{d.get('recall',0):.4f}",
                                 "F1-Score":  f"{d.get('f1-score',0):.4f}",
                                 "Support":   str(int(d.get('support',0)))})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.markdown("---")
            st.markdown("#### Full Summary — All Models")
            all_rows = []
            for mn in model_names:
                r = results[mn]
                c2 = r['conf_matrix']
                tn2, fp2, fn2, tp2 = c2[0][0], c2[0][1], c2[1][0], c2[1][1]
                all_rows.append({"Model": mn,
                                 "Accuracy": f"{r['accuracy']:.4f}", "AUC": f"{r['auc']:.4f}",
                                 "F1": f"{r['f1']:.4f}", "Precision": f"{r['precision']:.4f}",
                                 "Recall": f"{r['recall']:.4f}",
                                 "TP": tp2, "TN": tn2, "FP": fp2, "FN": fn2})
            st.dataframe(pd.DataFrame(all_rows), hide_index=True, width="stretch")
            st.download_button("Export as CSV", pd.DataFrame(all_rows).to_csv(index=False).encode(),
                               "model_metrics.csv", "text/csv", width="stretch")

    if 'Model Info' in _slot:
        with _slot['Model Info']:
            model_info = [
                ("Logistic Regression", "LR", "Linear probabilistic classifier. Fast and interpretable.", "High recall"),
                ("Support Vector Machine (SVM)", "SVM", "Finds optimal hyperplane. Uses LinearSVC + calibration.", "Highest recall"),
                ("Decision Tree", "DT", "Rule-based tree classifier. Highly interpretable.", "Balanced metrics"),
                ("Random Forest", "RF", "Ensemble of 200 decision trees. Robust against overfitting.", "Best overall balance"),
                ("XGBoost", "XGB", "Gradient-boosted trees — gold standard for tabular data.", "High accuracy"),
            ]
            for i, (name, short, desc, strength) in enumerate(model_info):
                bc = colors_bar[i]
                r  = results.get(name, {})
                tag = "*** BEST *** " if name == best_name else ""
                st.markdown(f"""
            <div class="panel" style="border-left:4px solid {bc};margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <span style="font-size:1.05em;font-weight:700;color:#1f2937;">{tag}{name}</span>
                  <span style="background:{bc};color:white;font-size:.7em;font-weight:700;
                               padding:2px 9px;border-radius:20px;margin-left:8px;">{short}</span>
                </div>
                <div style="text-align:right;font-size:.85em;color:#6b7280;">
                  Acc: <b>{r.get('accuracy',0):.2%}</b> &nbsp; AUC: <b>{r.get('auc',0):.4f}</b>
                </div>
              </div>
              <div style="color:#6b7280;font-size:.85em;margin-top:6px;">{desc}</div>
              <div style="color:#10b981;font-size:.8em;margin-top:4px;font-weight:600;">Strength: {strength}</div>
            </div>""", unsafe_allow_html=True)
            st.markdown("""
        <div class="panel"><h4 style="color:#3b82f6;">Dataset &amp; Preprocessing</h4>

        | Step | Detail |
        |------|--------|
        | Dataset | heart.csv — Cardiovascular Disease dataset |
        | Rows | ~70,000 patient records |
        | Split | 80% Train / 20% Test (stratified) |
        | Features | 11 raw + 4 engineered (BMI, Pulse Pressure, Age Group, Risk Flag) |
        | Scaling | StandardScaler |
        | Imbalance | class_weight='balanced' |

        </div>""", unsafe_allow_html=True)

    # ────────────────────────────────────────────────────────────
    # TAB 5 — Feature Importance
    # ────────────────────────────────────────────────────────────
    if 'Feature Importance' in _slot:
        with _slot['Feature Importance']:
            st.markdown("#### Feature Importance — Per Model")
            st.markdown(
                '<div class="alert-info">Shows which clinical features most influence each model\'s predictions. '
            'For LR/SVM the absolute coefficient values are used as a proxy for importance.</div>',
                unsafe_allow_html=True)

            # Load feature names
            feat_path = os.path.join(MODELS_DIR, "features.json")
            if os.path.exists(feat_path):
                with open(feat_path) as _f:
                    feature_names = json.load(_f)
            else:
                feature_names = ["age","gender","height","weight","ap_hi","ap_lo",
                                 "cholesterol","gluc","smoke","alco","active",
                                 "bmi","pulse_pressure","age_group","high_risk_flag"]

            # Friendly display names
            feat_labels = {
                "age": "Age", "gender": "Gender", "height": "Height", "weight": "Weight",
                "ap_hi": "Systolic BP", "ap_lo": "Diastolic BP",
                "cholesterol": "Cholesterol", "gluc": "Glucose",
                "smoke": "Smoker", "alco": "Alcohol", "active": "Physically Active",
                "bmi": "BMI", "pulse_pressure": "Pulse Pressure",
                "age_group": "Age Group", "high_risk_flag": "High Risk Flag"
            }
            display_names = [feat_labels.get(f, f) for f in feature_names]

            # Models that support feature importance
            fi_model_files = {
                "Random Forest":               "random_forest.pkl",
                "XGBoost":                     "xgboost.pkl",
                "Decision Tree":               "decision_tree.pkl",
                "Logistic Regression":         "logistic_regression.pkl",
                "Support Vector Machine (SVM)": "svm.pkl",
            }

            fi_sel = st.selectbox(
                "Select Model for Feature Importance",
                [m for m in model_names if m in fi_model_files]
            )

            model_file = os.path.join(MODELS_DIR, fi_model_files[fi_sel])
            fi_values = None
            fi_note   = ""

            if os.path.exists(model_file):
                try:
                    with open(model_file, "rb") as _mf:
                        _model = pickle.load(_mf)

                    if hasattr(_model, "feature_importances_"):
                        fi_values = _model.feature_importances_
                        fi_note   = "Gini impurity-based importance (higher = more influential)"
                    elif hasattr(_model, "coef_"):
                        fi_values = np.abs(_model.coef_[0])
                        fi_note   = "Absolute value of model coefficients used as importance proxy"
                    elif hasattr(_model, "calibrated_classifiers_"):
                        # CalibratedClassifierCV wrapping LinearSVC
                        base = _model.calibrated_classifiers_[0].estimator
                        if hasattr(base, "coef_"):
                            fi_values = np.abs(base.coef_[0])
                            fi_note   = "Absolute SVM coefficients (LinearSVC) used as importance proxy"
                except Exception as _e:
                    st.error(f"Could not load model: {_e}")
            else:
                st.warning(f"Model file not found: {fi_model_files[fi_sel]}")

            if fi_values is not None and len(fi_values) == len(feature_names):
                # Normalize
                fi_norm = fi_values / (fi_values.sum() + 1e-9)
                sorted_ii = np.argsort(fi_norm)[::-1]
                sorted_labels = [display_names[i] for i in sorted_ii]
                sorted_vals   = fi_norm[sorted_ii]

                # Colour gradient from red (most important) to blue (least)
                # FIXED (BUG-01): matplotlib-safe hex, not CSS rgba() strings.
                bar_colors = [gradient_hex(j, len(sorted_ii)) for j in range(len(sorted_ii))]

                fig_fi, ax_fi = plt.subplots(figsize=(9, max(5, len(feature_names)*0.45)),
                                             facecolor='none')
                ax_fi.set_facecolor('none')
                bars_fi = ax_fi.barh(sorted_labels[::-1], sorted_vals[::-1],
                                      color=bar_colors[::-1], height=0.65)
                ax_fi.set_xlabel("Normalised Importance", color=ucharts.color('fg'), fontsize=9)
                ax_fi.set_title(f"Feature Importance — {fi_sel}", color=ucharts.color('fg'),
                                 fontsize=10, fontweight='700', pad=10)
                ax_fi.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top', 'right']:   ax_fi.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_fi.spines[sp].set_color(ucharts.color('spine'))
                for bar in bars_fi:
                    ax_fi.text(bar.get_width() + 0.002,
                               bar.get_y() + bar.get_height()/2,
                               f"{bar.get_width():.3f}",
                               va='center', color=ucharts.color('fg'), fontsize=7.5, fontweight='600')
                plt.tight_layout()
                st.pyplot(fig_fi, transparent=True)
                plt.close()

                if fi_note:
                    st.markdown(f'<div class="alert-info" style="font-size:.82em;">{fi_note}</div>',
                                unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("#### Top Features Ranked Table")
                fi_df = pd.DataFrame({
                    "Rank":      list(range(1, len(sorted_ii)+1)),
                    "Feature":   sorted_labels,
                    "Importance (normalised)": [f"{v:.4f}" for v in sorted_vals],
                    "Importance (%)": [f"{v*100:.2f}%" for v in sorted_vals],
                })
                st.dataframe(fi_df, hide_index=True, width="stretch")

                # ── Cumulative Importance Curve ───────────────────────────
                st.markdown("---")
                st.markdown("#### Cumulative Feature Importance Curve")
                st.markdown(
                    '<div class="alert-info">Shows how many top features are needed to explain '
                'a given percentage of the total model importance. '
                'Steeper = fewer features dominate the model.</div>',
                    unsafe_allow_html=True)
                cumul = np.cumsum(sorted_vals)
                fig_cum, ax_cum = plt.subplots(figsize=(8, 3.5), facecolor='none')
                ax_cum.set_facecolor('none')
                ax_cum.plot(range(1, len(cumul)+1), cumul * 100,
                            color=ucharts.color('series_random_forest'), linewidth=2.5, marker='o', markersize=4)
                ax_cum.fill_between(range(1, len(cumul)+1), cumul * 100,
                                    alpha=0.15, color=ucharts.color('series_random_forest'))
                # Mark 80%, 90%, 95% thresholds
                for thresh, col, lbl in [(0.80, ucharts.color('risk_borderline'), '80%'),
                                          (0.90, ucharts.color('risk_high'), '90%'),
                                          (0.95, ucharts.color('risk_low'), '95%')]:
                    idx_t = next((i for i, v in enumerate(cumul) if v >= thresh), len(cumul)-1)
                    ax_cum.axhline(thresh*100, color=col, linestyle='--', linewidth=1.2, alpha=0.7)
                    ax_cum.axvline(idx_t+1, color=col, linestyle='--', linewidth=1.2, alpha=0.7)
                    ax_cum.annotate(f'{lbl} @ top-{idx_t+1}',
                                    xy=(idx_t+1, thresh*100),
                                    xytext=(idx_t+1.3, thresh*100-4),
                                    color=col, fontsize=7.5, fontweight='700')
                ax_cum.set_xlabel("Number of Top Features", color=ucharts.color('fg'), fontsize=9)
                ax_cum.set_ylabel("Cumulative Importance (%)", color=ucharts.color('fg'), fontsize=9)
                ax_cum.set_xlim(1, len(cumul))
                ax_cum.set_ylim(0, 105)
                ax_cum.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top', 'right']:   ax_cum.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_cum.spines[sp].set_color(ucharts.color('spine'))
                ax_cum.grid(True, color=ucharts.color('surface'), linestyle='--', linewidth=0.5, alpha=0.6)
                plt.tight_layout()
                st.pyplot(fig_cum, transparent=True)
                plt.close()

                st.markdown("---")
                st.markdown("#### Top-5 Features Comparison Across Tree Models")
                st.markdown('<div class="alert-info">Compares top-5 features for Random Forest, XGBoost, and Decision Tree.</div>',
                            unsafe_allow_html=True)

                tree_models = {
                    "RF":  ("random_forest.pkl",  ucharts.color('risk_low')),
                    "XGB": ("xgboost.pkl",         ucharts.color('series_random_forest')),
                    "DT":  ("decision_tree.pkl",    ucharts.color('risk_borderline')),
                }
                top5_data = {}
                for short_lbl, (fname, _col) in tree_models.items():
                    fpath = os.path.join(MODELS_DIR, fname)
                    if os.path.exists(fpath):
                        try:
                            with open(fpath, "rb") as _ff:
                                _tm = pickle.load(_ff)
                            if hasattr(_tm, "feature_importances_"):
                                _fi = _tm.feature_importances_
                                _fi_norm = _fi / (_fi.sum() + 1e-9)
                                _top5_idx = np.argsort(_fi_norm)[::-1][:5]
                                top5_data[short_lbl] = {
                                    display_names[i]: _fi_norm[i] for i in _top5_idx
                                }
                        except Exception:
                            pass

                if top5_data:
                    all_top_feats = list(dict.fromkeys(
                        feat for d in top5_data.values() for feat in d
                    ))
                    fig_cmp, ax_cmp = plt.subplots(figsize=(9, 4), facecolor='none')
                    ax_cmp.set_facecolor('none')
                    x_cmp = np.arange(len(all_top_feats))
                    w_cmp = 0.25
                    clr_list = ucharts.categorical(3)
                    for idx_m, (short_lbl, d) in enumerate(top5_data.items()):
                        vals_cmp = [d.get(f, 0) for f in all_top_feats]
                        offset = (idx_m - 1) * w_cmp
                        ax_cmp.bar(x_cmp + offset, vals_cmp,
                                   width=w_cmp, label=short_lbl,
                                   color=clr_list[idx_m], alpha=0.85)
                    ax_cmp.set_xticks(x_cmp)
                    ax_cmp.set_xticklabels(all_top_feats, rotation=25, ha='right',
                                            color=ucharts.color('fg'), fontsize=8)
                    ax_cmp.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    ax_cmp.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=9)
                    for sp in ['top', 'right']:   ax_cmp.spines[sp].set_visible(False)
                    for sp in ['left', 'bottom']: ax_cmp.spines[sp].set_color(ucharts.color('spine'))
                    ax_cmp.set_ylabel("Importance", color=ucharts.color('fg'), fontsize=9)
                    plt.tight_layout()
                    st.pyplot(fig_cmp, transparent=True)
                    plt.close()

                # ── All-Models Feature Importance Heatmap ────────────────
                st.markdown("---")
                st.markdown("#### Feature Importance Heatmap — All Tree Models")
                st.markdown(
                    '<div class="alert-info">Heatmap of normalised feature importances across '
                'Random Forest, XGBoost and Decision Tree. Darker red = higher importance.</div>',
                    unsafe_allow_html=True)
                all_tree_files = {
                    "Random Forest": "random_forest.pkl",
                    "XGBoost":       "xgboost.pkl",
                    "Decision Tree": "decision_tree.pkl",
                }
                hm_data = {}   # model_name -> np array of normalised importances
                for _mn, _fn in all_tree_files.items():
                    _fp = os.path.join(MODELS_DIR, _fn)
                    if os.path.exists(_fp):
                        try:
                            with open(_fp, "rb") as _ff2:
                                _tm2 = pickle.load(_ff2)
                            if hasattr(_tm2, "feature_importances_"):
                                _fiv = _tm2.feature_importances_
                                hm_data[_mn] = _fiv / (_fiv.sum() + 1e-9)
                        except Exception:
                            pass
                if len(hm_data) >= 2:
                    hm_matrix = np.array([hm_data[k] for k in hm_data])
                    hm_labels  = list(hm_data.keys())
                    fig_hm, ax_hm = plt.subplots(
                        figsize=(11, max(3, len(feature_names)*0.38)),
                        facecolor='none')
                    ax_hm.set_facecolor('none')
                    im = ax_hm.imshow(hm_matrix, cmap=ucharts.cmap('sequential'), aspect='auto')
                    ax_hm.set_xticks(range(len(feature_names)))
                    ax_hm.set_xticklabels(display_names, rotation=40, ha='right',
                                           color=ucharts.color('fg'), fontsize=7.5)
                    ax_hm.set_yticks(range(len(hm_labels)))
                    ax_hm.set_yticklabels(hm_labels, color=ucharts.color('fg'), fontsize=8)
                    for r in range(len(hm_labels)):
                        for c in range(len(feature_names)):
                            val = hm_matrix[r, c]
                            txt_col = ucharts.on_color(im.cmap(im.norm(val)))
                            ax_hm.text(c, r, f"{val:.3f}",
                                       ha='center', va='center',
                                       color=txt_col, fontsize=6.5, fontweight='600')
                    cb = plt.colorbar(im, ax=ax_hm, fraction=0.025, pad=0.02)
                    cb.ax.tick_params(colors=ucharts.color('fg'), labelsize=7)
                    cb.set_label('Normalised Importance', color=ucharts.color('fg'), fontsize=8)
                    plt.tight_layout()
                    st.pyplot(fig_hm, transparent=True)
                    plt.close()
            else:
                st.warning("Feature importance could not be extracted for this model.")

    # ══════════════════════════════════════════════════════════════════
    # TAB 6 — ROC Curve, Precision-Recall Curve, Confusion Matrix
    # ══════════════════════════════════════════════════════════════════
    if 'ROC & PR Curves' in _slot:
        with _slot['ROC & PR Curves']:
            st.markdown("#### ROC Curve · Precision-Recall Curve · Confusion Matrix")

            # Check if new-style curve data exists (requires re-training)
            has_curves = any("roc_curve" in results[m] for m in model_names)
            if not has_curves:
                st.markdown(
                    '<div class="alert-warning">Curve data not found in results.json. '
                'Please ask SuperAdmin to <b>re-run model training</b> so ROC/PR curves are saved.</div>',
                    unsafe_allow_html=True)
            else:
                # ── 1. ROC CURVE ──────────────────────────────────────────────
                st.markdown("### ROC Curve — All Models")
                st.markdown(
                    '<div class="alert-info">ROC Curve shows the trade-off between True Positive Rate '
                '(Sensitivity) and False Positive Rate at different thresholds. '
                'Higher AUC = better discrimination ability.</div>',
                    unsafe_allow_html=True)

                fig_roc, ax_roc = plt.subplots(figsize=(8, 5.5), facecolor='none')
                ax_roc.set_facecolor('none')

                for i, mn in enumerate(model_names):
                    rcd = results[mn].get("roc_curve", {})
                    if rcd:
                        fpr_v = rcd["fpr"]
                        tpr_v = rcd["tpr"]
                        auc_v = results[mn]["auc"]
                        ax_roc.plot(fpr_v, tpr_v,
                                    color=colors_bar[i], linewidth=2.2,
                                    label=f"{short_names[i]} — AUC = {auc_v:.4f}")

                # Diagonal chance line
                ax_roc.plot([0, 1], [0, 1], color=ucharts.color('fg_subtle'), linestyle='--',
                            linewidth=1.2, label='Random Chance (AUC=0.5)')
                ax_roc.fill_between([0, 1], [0, 1], alpha=0.04, color=ucharts.color('fg_subtle'))

                ax_roc.set_xlabel("False Positive Rate (1 - Specificity)",
                                  color=ucharts.color('fg'), fontsize=10)
                ax_roc.set_ylabel("True Positive Rate (Sensitivity)",
                                   color=ucharts.color('fg'), fontsize=10)
                ax_roc.set_title("ROC Curve — All Models",
                                 color=ucharts.color('fg'), fontsize=12, fontweight='700', pad=12)
                ax_roc.set_xlim(0, 1); ax_roc.set_ylim(0, 1.02)
                ax_roc.tick_params(colors=ucharts.color('fg'), labelsize=9)
                ax_roc.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'),
                              fontsize=9, loc='lower right',
                              framealpha=0.8, edgecolor=ucharts.color('grid'))
                for sp in ['top', 'right']:   ax_roc.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_roc.spines[sp].set_color(ucharts.color('spine'))
                ax_roc.grid(True, color=ucharts.color('surface'), linestyle='--', linewidth=0.5, alpha=0.7)
                plt.tight_layout()
                st.pyplot(fig_roc, transparent=True)
                plt.close()

                st.markdown("---")

                # ── 2. PRECISION-RECALL CURVE ────────────────────────────────
                st.markdown("### Precision-Recall Curve — All Models")
                st.markdown(
                    '<div class="alert-info">PR Curve is especially useful for imbalanced datasets. '
                'Average Precision (AP) summarises the area under the PR curve — higher is better. '
                'The baseline is the positive class prevalence in the test set.</div>',
                    unsafe_allow_html=True)

                # Compute baseline (prevalence of class 1)
                total_pos = 0; total_all = 0
                for mn in model_names:
                    cm_d = results[mn].get("conf_matrix", [[0,0],[0,0]])
                    total_pos += cm_d[1][0] + cm_d[1][1]
                    total_all += cm_d[0][0] + cm_d[0][1] + cm_d[1][0] + cm_d[1][1]
                baseline_prev = total_pos / max(total_all, 1)

                fig_pr, ax_pr = plt.subplots(figsize=(8, 5.5), facecolor='none')
                ax_pr.set_facecolor('none')

                for i, mn in enumerate(model_names):
                    prd = results[mn].get("pr_curve", {})
                    if prd:
                        pr_prec = prd["precision"]
                        pr_rec  = prd["recall"]
                        ap      = prd.get("avg_precision", results[mn].get("auc", 0))
                        ax_pr.plot(pr_rec, pr_prec,
                                   color=colors_bar[i], linewidth=2.2,
                                   label=f"{short_names[i]} — AP = {ap:.4f}")

                # Baseline (random)
                ax_pr.axhline(baseline_prev, color=ucharts.color('fg_subtle'), linestyle='--',
                              linewidth=1.2, label=f'Baseline (prevalence = {baseline_prev:.2f})')

                ax_pr.set_xlabel("Recall (True Positive Rate)",
                                 color=ucharts.color('fg'), fontsize=10)
                ax_pr.set_ylabel("Precision", color=ucharts.color('fg'), fontsize=10)
                ax_pr.set_title("Precision-Recall Curve — All Models",
                                color=ucharts.color('fg'), fontsize=12, fontweight='700', pad=12)
                ax_pr.set_xlim(0, 1); ax_pr.set_ylim(0, 1.02)
                ax_pr.tick_params(colors=ucharts.color('fg'), labelsize=9)
                ax_pr.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'),
                             fontsize=9, loc='upper right',
                             framealpha=0.8, edgecolor=ucharts.color('grid'))
                for sp in ['top', 'right']:   ax_pr.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_pr.spines[sp].set_color(ucharts.color('spine'))
                ax_pr.grid(True, color=ucharts.color('surface'), linestyle='--', linewidth=0.5, alpha=0.7)
                plt.tight_layout()
                st.pyplot(fig_pr, transparent=True)
                plt.close()

                st.markdown("---")

                # ── 3. CONFUSION MATRIX (full heatmaps) ──────────────────────
                st.markdown("### Confusion Matrix — Per Model")
                st.markdown(
                    '<div class="alert-info">Rows = Actual labels, Columns = Predicted labels. '
                '0 = Low Risk (No Disease) &nbsp;|&nbsp; 1 = High Risk (Disease). '
                'Darker green = more correct predictions.</div>',
                    unsafe_allow_html=True)

                # Two rows of confusion matrices
                cm_cols = st.columns(len(model_names))
                for idx, (mn, col_cm) in enumerate(zip(model_names, cm_cols)):
                    cm_d = results[mn].get("conf_matrix", [[0,0],[0,0]])
                    tn_v = cm_d[0][0]; fp_v = cm_d[0][1]
                    fn_v = cm_d[1][0]; tp_v = cm_d[1][1]
                    total_v = tn_v + fp_v + fn_v + tp_v
                    sens_v  = tp_v / max(tp_v + fn_v, 1)
                    spec_v  = tn_v / max(tn_v + fp_v, 1)
                    acc_v   = (tp_v + tn_v) / max(total_v, 1)

                    with col_cm:
                        fig_cm2, ax_cm2 = plt.subplots(figsize=(3.2, 3.0), facecolor='none')
                        ax_cm2.set_facecolor('none')

                        cm_arr2  = np.array([[tn_v, fp_v], [fn_v, tp_v]], dtype=float)
                        cm_norm  = cm_arr2 / max(cm_arr2.max(), 1)

                        im = ax_cm2.imshow(cm_norm, cmap=ucharts.cmap('sequential', reverse=True),
                                           aspect='auto', vmin=0, vmax=1)
                        plt.colorbar(im, ax=ax_cm2, fraction=0.046, pad=0.04)

                        labels_mat = [[f"TN\n{tn_v}", f"FP\n{fp_v}"],
                                      [f"FN\n{fn_v}", f"TP\n{tp_v}"]]
                        clr_txt = [[ucharts.on_color(im.cmap(im.norm(cm_norm[r][c])))
                                    for c in range(2)] for r in range(2)]
                        for r in range(2):
                            for c_ in range(2):
                                ax_cm2.text(c_, r, labels_mat[r][c_],
                                            ha='center', va='center',
                                            color=clr_txt[r][c_],
                                            fontsize=9, fontweight='800')

                        ax_cm2.set_xticks([0, 1])
                        ax_cm2.set_yticks([0, 1])
                        ax_cm2.set_xticklabels(['Pred: 0\n(Low Risk)', 'Pred: 1\n(High Risk)'],
                                               color=ucharts.color('fg'), fontsize=7)
                        ax_cm2.set_yticklabels(['Act: 0\n(Low Risk)', 'Act: 1\n(High Risk)'],
                                               color=ucharts.color('fg'), fontsize=7)
                        ax_cm2.set_title(f"{short_names[idx]}\nAcc={acc_v:.1%}",
                                         color=ucharts.color('fg'), fontsize=9, fontweight='700', pad=8)
                        ax_cm2.tick_params(length=0)
                        plt.tight_layout(pad=0.5)
                        st.pyplot(fig_cm2, transparent=True)
                        plt.close()

                        st.markdown(
                            f'<div style="font-size:.74em;color:#94a3b8;line-height:1.8;text-align:center;">'
                        f'Sensitivity: <b style="color:#10b981">{sens_v:.1%}</b><br>'
                        f'Specificity: <b style="color:#3b82f6">{spec_v:.1%}</b>'
                        f'</div>', unsafe_allow_html=True)

                # Summary table below all CMs
                st.markdown("---")
                st.markdown("#### Confusion Matrix Summary Table")
                cm_rows = []
                for mn in model_names:
                    cm_d = results[mn].get("conf_matrix", [[0,0],[0,0]])
                    tn_v, fp_v = cm_d[0][0], cm_d[0][1]
                    fn_v, tp_v = cm_d[1][0], cm_d[1][1]
                    total_v    = tn_v + fp_v + fn_v + tp_v
                    cm_rows.append({
                        "Model":        mn,
                        "TP":           tp_v, "TN": tn_v,
                        "FP":           fp_v, "FN": fn_v,
                        "Accuracy":     f"{(tp_v+tn_v)/max(total_v,1):.2%}",
                        "Sensitivity":  f"{tp_v/max(tp_v+fn_v,1):.2%}",
                        "Specificity":  f"{tn_v/max(tn_v+fp_v,1):.2%}",
                        "FPR":          f"{fp_v/max(fp_v+tn_v,1):.2%}",
                        "FNR":          f"{fn_v/max(fn_v+tp_v,1):.2%}",
                    })
                st.dataframe(pd.DataFrame(cm_rows), hide_index=True, width="stretch")

    # ══════════════════════════════════════════════════════════════════
    # TAB 7 — K-Fold Cross Validation
    # ══════════════════════════════════════════════════════════════════
    if 'K-Fold CV' in _slot:
        with _slot['K-Fold CV']:
            section_header("K", "K-Fold Cross Validation",
                           f"Stratified {results[model_names[0]].get('kfold_cv', {}).get('k', 5) if results[model_names[0]].get('kfold_cv') else 5}-Fold CV — measures model generalisation and stability")

            has_cv = any(
                results[m].get("kfold_cv") is not None
                for m in model_names
            )

            if not has_cv:
                st.markdown(
                    '<div class="alert-warning">K-Fold CV data not found. '
                'Please ask SuperAdmin to <b>re-train models</b> so CV results are saved.</div>',
                    unsafe_allow_html=True)
            else:
                cv_colors  = [ucharts.color('risk_high'),ucharts.color('primary'),ucharts.color('risk_borderline'),ucharts.color('risk_low'),ucharts.color('series_random_forest')]
                cv_metrics = ["accuracy","auc","f1","precision","recall"]
                cv_labels  = ["Accuracy","AUC","F1 Score","Precision","Recall"]

                # ── SUMMARY CARD: best CV model ───────────────────────────
                best_cv_name, best_cv_auc = None, -1
                for mn in model_names:
                    cv = results[mn].get("kfold_cv")
                    if cv and cv["mean"]["auc"] > best_cv_auc:
                        best_cv_auc  = cv["mean"]["auc"]
                        best_cv_name = mn

                best_cv = results[best_cv_name]["kfold_cv"]
                st.markdown(f"""
            <div style="background:linear-gradient(135deg,#1e0d2e,#2d1f40);border:2px solid #a855f7;
                        border-radius:14px;padding:16px 22px;margin-bottom:20px;
                        display:flex;align-items:center;gap:16px;">
              <div style="font-size:2.2em;">&#128200;</div>
              <div>
                <div style="color:#e9d5ff;font-size:1em;font-weight:700;">Best CV Model</div>
                <div style="color:#a855f7;font-size:1.4em;font-weight:800;">{best_cv_name}</div>
                <div style="color:#c4b5fd;font-size:.85em;">
                  CV AUC: <b>{best_cv_auc:.4f}</b> &nbsp;|&nbsp;
                  CV Acc: <b>{best_cv['mean']['accuracy']:.4f}</b> &nbsp;|&nbsp;
                  Std(AUC): <b>&plusmn;{best_cv['std']['auc']:.4f}</b>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

                # ── PLOT 1: Fold-by-fold line chart per metric ────────────
                st.markdown("### Fold-by-Fold Performance — All Models")
                st.markdown('<div class="alert-info">Each line = one model. X-axis = fold number. '
                        'Stable horizontal lines indicate a robust model.</div>',
                            unsafe_allow_html=True)

                kfold_n = best_cv["k"]
                fold_labels = [f"Fold {i+1}" for i in range(kfold_n)]

                fig_folds, axes_folds = plt.subplots(
                    1, len(cv_metrics), figsize=(3.8 * len(cv_metrics), 4),
                    facecolor='none')
                for ax_f, met, lbl in zip(axes_folds, cv_metrics, cv_labels):
                    ax_f.set_facecolor('none')
                    for i, mn in enumerate(model_names):
                        cv = results[mn].get("kfold_cv")
                        if cv:
                            vals = cv["folds"][met]
                            ax_f.plot(range(1, kfold_n+1), vals,
                                      marker='o', markersize=5,
                                      color=cv_colors[i], linewidth=1.8,
                                      label=short_names[i])
                            ax_f.axhline(cv["mean"][met], color=cv_colors[i],
                                         linestyle='--', linewidth=0.7, alpha=0.5)
                    ax_f.set_title(lbl, color=ucharts.color('fg'), fontsize=9, fontweight='700')
                    ax_f.set_xticks(range(1, kfold_n+1))
                    ax_f.set_xticklabels([str(i) for i in range(1, kfold_n+1)],
                                          color=ucharts.color('fg'), fontsize=7)
                    ax_f.set_ylim(0.4, 1.02)
                    ax_f.tick_params(colors=ucharts.color('fg'), labelsize=7)
                    for sp in ['top','right']:   ax_f.spines[sp].set_visible(False)
                    for sp in ['left','bottom']: ax_f.spines[sp].set_color(ucharts.color('spine'))
                    ax_f.grid(True, color=ucharts.color('surface'), linestyle='--',
                              linewidth=0.5, alpha=0.6)

                # shared legend below charts
                handles = [plt.Line2D([0],[0], color=cv_colors[i], lw=2, label=short_names[i])
                           for i in range(len(model_names))]
                fig_folds.legend(handles=handles, loc='lower center',
                                 ncol=len(model_names), facecolor=ucharts.color('surface'),
                                 labelcolor=ucharts.color('fg'), fontsize=8,
                                 bbox_to_anchor=(0.5, -0.08), framealpha=0.8)
                plt.tight_layout()
                st.pyplot(fig_folds, transparent=True)
                plt.close()

                st.markdown("---")

                # ── PLOT 2: Box plots — one per metric ────────────────────
                st.markdown("### Score Distribution per Model (Box Plot)")
                st.markdown('<div class="alert-info">Box width = interquartile range (IQR). '
                        'Whiskers = min/max per model. Narrow box = more stable model.</div>',
                            unsafe_allow_html=True)

                fig_box, axes_box = plt.subplots(
                    1, len(cv_metrics), figsize=(3.8 * len(cv_metrics), 4.5),
                    facecolor='none')
                for ax_b, met, lbl in zip(axes_box, cv_metrics, cv_labels):
                    ax_b.set_facecolor('none')
                    box_data   = []
                    box_colors = []
                    box_labels = []
                    for i, mn in enumerate(model_names):
                        cv = results[mn].get("kfold_cv")
                        if cv:
                            box_data.append(cv["folds"][met])
                            box_colors.append(cv_colors[i])
                            box_labels.append(short_names[i])

                    bp = ax_b.boxplot(box_data, patch_artist=True,
                                      widths=0.5, notch=False,
                                      medianprops=dict(color=ucharts.color('surface'), linewidth=2))
                    for patch, col in zip(bp['boxes'], box_colors):
                        patch.set_facecolor(col)
                        patch.set_alpha(0.75)
                    for whisker in bp['whiskers']:
                        whisker.set_color(ucharts.color('fg_subtle'))
                    for cap in bp['caps']:
                        cap.set_color(ucharts.color('fg_subtle'))
                    for flier in bp['fliers']:
                        flier.set(marker='o', color=ucharts.color('fg_muted'),
                                  markersize=4, alpha=0.6)

                    ax_b.set_xticklabels(box_labels, color=ucharts.color('fg'), fontsize=8)
                    ax_b.set_title(lbl, color=ucharts.color('fg'), fontsize=9, fontweight='700')
                    ax_b.set_ylim(0.35, 1.05)
                    ax_b.tick_params(colors=ucharts.color('fg'), labelsize=7)
                    for sp in ['top','right']:   ax_b.spines[sp].set_visible(False)
                    for sp in ['left','bottom']: ax_b.spines[sp].set_color(ucharts.color('spine'))
                    ax_b.grid(True, axis='y', color=ucharts.color('surface'),
                              linestyle='--', linewidth=0.5, alpha=0.6)

                plt.tight_layout()
                st.pyplot(fig_box, transparent=True)
                plt.close()

                st.markdown("---")

                # ── PLOT 3: Stability Heatmap (Std per model/metric) ──────
                st.markdown("### Stability Heatmap — Standard Deviation")
                st.markdown('<div class="alert-info">Lower std = more stable (darker blue = better). '
                        'High std means the model is sensitive to which data it trains on.</div>',
                            unsafe_allow_html=True)

                std_matrix = np.array([
                    [results[mn]["kfold_cv"]["std"][m]
                     if results[mn].get("kfold_cv") else 0
                     for m in cv_metrics]
                    for mn in model_names
                ])

                fig_hm, ax_hm = plt.subplots(figsize=(8, 3.5), facecolor='none')
                ax_hm.set_facecolor('none')
                im_h = ax_hm.imshow(std_matrix, cmap=ucharts.cmap('sequential', reverse=True),
                                     aspect='auto', vmin=0, vmax=0.05)
                plt.colorbar(im_h, ax=ax_hm, fraction=0.03, pad=0.02)
                ax_hm.set_xticks(range(len(cv_labels)))
                ax_hm.set_yticks(range(len(model_names)))
                ax_hm.set_xticklabels(cv_labels, color=ucharts.color('fg'), fontsize=9)
                ax_hm.set_yticklabels(short_names, color=ucharts.color('fg'), fontsize=9)
                ax_hm.set_title("Std Deviation per Model & Metric (lower = more stable)",
                                color=ucharts.color('fg'), fontsize=10, fontweight='700', pad=10)
                for r in range(len(model_names)):
                    for c_ in range(len(cv_metrics)):
                        ax_hm.text(c_, r, f"{std_matrix[r,c_]:.4f}",
                                   ha='center', va='center',
                                   color=ucharts.on_color(im_h.cmap(im_h.norm(std_matrix[r, c_]))),
                                   fontsize=8, fontweight='700')
                ax_hm.tick_params(length=0)
                plt.tight_layout()
                st.pyplot(fig_hm, transparent=True)
                plt.close()

                st.markdown("---")

                # ── TABLE: Mean ± Std summary ─────────────────────────────
                st.markdown("### Mean \u00b1 Std Summary Table")
                cv_summary_rows = []
                for mn in model_names:
                    cv = results[mn].get("kfold_cv")
                    if cv:
                        row = {"Model": mn}
                        for met, lbl in zip(cv_metrics, cv_labels):
                            mu  = cv["mean"][met]
                            sig = cv["std"][met]
                            row[lbl] = f"{mu:.4f} \u00b1 {sig:.4f}"
                        cv_summary_rows.append(row)
                if cv_summary_rows:
                    cv_df = pd.DataFrame(cv_summary_rows)
                    st.dataframe(cv_df, hide_index=True, width="stretch")

                # ── TABLE: Per-fold detail ────────────────────────────────
                with st.expander("Show per-fold detail for each model"):
                    for mn in model_names:
                        cv = results[mn].get("kfold_cv")
                        if not cv:
                            continue
                        st.markdown(f"**{mn}**")
                        fold_rows = []
                        for fid in range(cv["k"]):
                            fold_rows.append({
                                # FIXED (BUG-21): str, not int. Mixing ints with the "Mean"
                                # and "Std" labels below gave an object-dtype column that
                                # pyarrow could not serialise, throwing on every render.
                                "Fold":      str(fid + 1),
                                "Accuracy":  f"{cv['folds']['accuracy'][fid]:.4f}",
                                "AUC":       f"{cv['folds']['auc'][fid]:.4f}",
                                "F1":        f"{cv['folds']['f1'][fid]:.4f}",
                                "Precision": f"{cv['folds']['precision'][fid]:.4f}",
                                "Recall":    f"{cv['folds']['recall'][fid]:.4f}",
                            })
                        # Add mean/std row
                        fold_rows.append({
                            "Fold":      "Mean",
                            "Accuracy":  f"{cv['mean']['accuracy']:.4f}",
                            "AUC":       f"{cv['mean']['auc']:.4f}",
                            "F1":        f"{cv['mean']['f1']:.4f}",
                            "Precision": f"{cv['mean']['precision']:.4f}",
                            "Recall":    f"{cv['mean']['recall']:.4f}",
                        })
                        fold_rows.append({
                            "Fold":      "Std",
                            "Accuracy":  f"{cv['std']['accuracy']:.4f}",
                            "AUC":       f"{cv['std']['auc']:.4f}",
                            "F1":        f"{cv['std']['f1']:.4f}",
                            "Precision": f"{cv['std']['precision']:.4f}",
                            "Recall":    f"{cv['std']['recall']:.4f}",
                        })
                        st.dataframe(pd.DataFrame(fold_rows),
                                     hide_index=True, width="stretch")
                        st.markdown("")

    # ══════════════════════════════════════════════════════════════════
    # TAB 8 — Explainable AI (SHAP)
    # ══════════════════════════════════════════════════════════════════
    if 'Explainable AI (SHAP)' in _slot:
        with _slot['Explainable AI (SHAP)']:
            section_header("S", "Explainable AI — SHAP Analysis",
                           "SHapley Additive exPlanations: understand why each model makes its predictions")

            st.markdown("""
        <div class="panel" style="border-left:4px solid #a855f7;">
        <h4 style="color:#a855f7;margin-bottom:8px;">What is SHAP?</h4>
        <p style="color:#4b5563;font-size:.9em;line-height:1.7;">
        SHAP (SHapley Additive exPlanations) is a game-theory-based method that explains
        <b>why</b> a model made a specific prediction. Each feature gets a SHAP value indicating
        how much it pushed the output <b style="color:#ef4444;">toward High Risk</b> or
        <b style="color:#10b981;">toward Low Risk</b> for a given patient.
        </p>
        <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:10px;">
          <div style="background:#1e0d0d;border:1px solid #ef4444;border-radius:8px;padding:10px 14px;font-size:.82em;color:#fca5a5;">
            <b>Positive SHAP</b><br>Feature increases cardiovascular risk prediction
          </div>
          <div style="background:#0d1e0d;border:1px solid #10b981;border-radius:8px;padding:10px 14px;font-size:.82em;color:#6ee7b7;">
            <b>Negative SHAP</b><br>Feature decreases cardiovascular risk prediction
          </div>
          <div style="background:#1e1e2e;border:1px solid #a855f7;border-radius:8px;padding:10px 14px;font-size:.82em;color:#c4b5fd;">
            <b>Mean |SHAP|</b><br>Average importance of a feature across all patients
          </div>
        </div>
        </div>
        """, unsafe_allow_html=True)

            try:
                import shap
                shap_available = True
            except ImportError:
                shap_available = False
                st.error("SHAP library not installed. Run: `pip install shap` and restart the app.")

            if shap_available:
                # Feature name setup (reuse from tab t5)
                shap_feat_path = os.path.join(MODELS_DIR, "features.json")
                shap_feat_labels = {
                    "age": "Age", "gender": "Gender", "height": "Height", "weight": "Weight",
                    "ap_hi": "Systolic BP", "ap_lo": "Diastolic BP",
                    "cholesterol": "Cholesterol", "gluc": "Glucose",
                    "smoke": "Smoker", "alco": "Alcohol", "active": "Physically Active",
                    "bmi": "BMI", "pulse_pressure": "Pulse Pressure",
                    "age_group": "Age Group", "high_risk_flag": "High Risk Flag"
                }
                shap_fi_model_files = {
                    "Random Forest":               "random_forest.pkl",
                    "XGBoost":                     "xgboost.pkl",
                    "Decision Tree":               "decision_tree.pkl",
                    "Logistic Regression":         "logistic_regression.pkl",
                    "Support Vector Machine (SVM)": "svm.pkl",
                }

                shap_model_opts = [m for m in model_names if m in shap_fi_model_files]
                shap_sel = st.selectbox(
                    "Select Model for SHAP Analysis",
                    shap_model_opts,
                    key="shap_tab_model_sel",
                    help="Tree models (RF, XGB, DT) compute SHAP fastest. SVM uses KernelExplainer (slower)."
                )

                @st.cache_data(show_spinner=False)
                def compute_shap_values(model_name_key, feat_path_key, data_path_key, _model_file_key):
                    """Compute SHAP values — cached so it only reruns when inputs change."""
                    import shap as _shap
                    import pickle as _pickle, json as _json
                    import numpy as _np, pandas as _pd

                    if os.path.exists(feat_path_key):
                        with open(feat_path_key) as _fj:
                            _feat_names = _json.load(_fj)
                    else:
                        _feat_names = ["age","gender","height","weight","ap_hi","ap_lo",
                                       "cholesterol","gluc","smoke","alco","active",
                                       "bmi","pulse_pressure","age_group","high_risk_flag"]

                    with open(_model_file_key, "rb") as _fm:
                        _mdl = _pickle.load(_fm)

                    try:
                        _df_bg = _pd.read_csv(data_path_key, sep=None, engine="python")
                        for _tc in ["cardio", "target", "id", "Unnamed: 0"]:
                            if _tc in _df_bg.columns:
                                _df_bg.drop(columns=[_tc], inplace=True)
                        _df_bg, _ = fe.convert_age_to_years(_df_bg)

                        # FIXED (M2): apply the same physiological domain filter the models
                        # were trained under. The background was previously drawn from raw
                        # heart.csv, so SHAP explained a distribution containing rows the
                        # models had never seen.
                        _bg_mask = _pd.Series(True, index=_df_bg.index)
                        if "ap_hi" in _df_bg.columns:
                            _bg_mask &= _df_bg["ap_hi"].between(60, 250)
                        if "ap_lo" in _df_bg.columns:
                            _bg_mask &= _df_bg["ap_lo"].between(40, 200)
                        if {"ap_hi", "ap_lo"} <= set(_df_bg.columns):
                            _bg_mask &= _df_bg["ap_hi"] > _df_bg["ap_lo"]
                        if "height" in _df_bg.columns:
                            _bg_mask &= _df_bg["height"].between(100, 250)
                        if "weight" in _df_bg.columns:
                            _bg_mask &= _df_bg["weight"].between(20, 300)
                        for _oc in ["cholesterol", "gluc"]:
                            if _oc in _df_bg.columns:
                                _bg_mask &= _df_bg[_oc].isin(fe.ORDINAL_VALID_VALUES)
                        _df_bg = _df_bg[_bg_mask].reset_index(drop=True)

                        # FIXED (BUG-05): derived features from the shared module — this was
                        # the third divergent copy of the feature-engineering logic.
                        _df_bg = fe.engineer_features(_df_bg)
                        _avail = [c for c in _feat_names if c in _df_bg.columns]
                        _df_bg = _df_bg[_avail].dropna()
                        _scaler_path = os.path.join(os.path.dirname(_model_file_key), "scaler.pkl")
                        with open(_scaler_path, "rb") as _sf:
                            _sc = _pickle.load(_sf)
                        _bg_sample = _df_bg.sample(min(300, len(_df_bg)), random_state=42)
                        _bg_scaled = _sc.transform(_bg_sample)
                        _bg_df = _pd.DataFrame(_bg_scaled, columns=_avail)
                    except Exception as _de:
                        return None, None, str(_de)

                    try:
                        if hasattr(_mdl, "feature_importances_"):
                            _explainer = _shap.TreeExplainer(_mdl)
                            _sv = _explainer.shap_values(_bg_df)
                            if isinstance(_sv, list) and len(_sv) == 2:
                                _sv = _sv[1]
                        elif hasattr(_mdl, "coef_"):
                            _explainer = _shap.LinearExplainer(_mdl, _bg_df)
                            _sv = _explainer.shap_values(_bg_df)
                            if isinstance(_sv, list):
                                _sv = _sv[0]
                        elif hasattr(_mdl, "calibrated_classifiers_"):
                            _bg_small = _shap.sample(_bg_df, 80)
                            _explainer = _shap.KernelExplainer(_mdl.predict_proba, _bg_small)
                            _sv_s = _explainer.shap_values(_bg_small, nsamples=60)
                            _sv  = _sv_s[1] if isinstance(_sv_s, list) and len(_sv_s)==2 else _sv_s
                            _bg_df = _bg_small.reset_index(drop=True)
                        else:
                            _bg_small = _shap.sample(_bg_df, 80)
                            _explainer = _shap.KernelExplainer(_mdl.predict_proba, _bg_small)
                            _sv_s = _explainer.shap_values(_bg_small, nsamples=60)
                            _sv  = _sv_s[1] if isinstance(_sv_s, list) else _sv_s
                            _bg_df = _bg_small.reset_index(drop=True)
                        return _np.array(_sv), _bg_df, None
                    except Exception as _ee:
                        return None, None, str(_ee)

                shap_model_file = os.path.join(MODELS_DIR, shap_fi_model_files[shap_sel])
                with st.spinner(f"Computing SHAP values for {shap_sel}... (may take ~10–30 sec)"):
                    shap_vals, bg_data, shap_err = compute_shap_values(
                        shap_sel, shap_feat_path, DATA_PATH, shap_model_file
                    )

                if shap_err:
                    st.error(f"SHAP computation error: {shap_err}")
                elif shap_vals is not None and bg_data is not None:
                    shap_feat_names = list(bg_data.columns)
                    shap_display    = [shap_feat_labels.get(f, f) for f in shap_feat_names]
                    mean_abs_shap   = np.abs(shap_vals).mean(axis=0)
                    sorted_idx      = np.argsort(mean_abs_shap)[::-1]
                    s_labels        = [shap_display[i] for i in sorted_idx]
                    s_vals          = mean_abs_shap[sorted_idx]

                    # ── Row 1: Mean |SHAP| bar  +  Beeswarm ──────────────────
                    col_shap1, col_shap2 = st.columns(2)

                    with col_shap1:
                        st.markdown("**Mean |SHAP| — Global Feature Impact Ranking**")
                        # FIXED (BUG-02): matplotlib-safe hex, not CSS rgba() strings.
                        bar_clrs_shap = [
                            gradient_hex(j, len(sorted_idx), end=(60, 158, 238))
                            for j in range(len(sorted_idx))
                        ]
                        fig_sb, ax_sb = plt.subplots(
                            figsize=(6, max(4.5, len(shap_feat_names)*0.44)),
                            facecolor='none')
                        ax_sb.set_facecolor('none')
                        hbars = ax_sb.barh(s_labels[::-1], s_vals[::-1],
                                           color=bar_clrs_shap[::-1], height=0.65)
                        ax_sb.set_xlabel("Mean |SHAP value|", color=ucharts.color('fg'), fontsize=9)
                        ax_sb.set_title(f"Global SHAP Impact — {shap_sel}",
                                        color=ucharts.color('fg'), fontsize=10, fontweight='700', pad=10)
                        ax_sb.tick_params(colors=ucharts.color('fg'), labelsize=8)
                        for sp in ['top','right']:   ax_sb.spines[sp].set_visible(False)
                        for sp in ['left','bottom']: ax_sb.spines[sp].set_color(ucharts.color('spine'))
                        ax_sb.grid(True, axis='x', color=ucharts.color('surface'), linestyle='--',
                                   linewidth=0.5, alpha=0.6)
                        for hbar in hbars:
                            ax_sb.text(hbar.get_width() + max(s_vals)*0.01,
                                       hbar.get_y() + hbar.get_height()/2,
                                       f"{hbar.get_width():.4f}",
                                       va='center', color=ucharts.color('fg'), fontsize=7.5, fontweight='600')
                        plt.tight_layout()
                        st.pyplot(fig_sb, transparent=True)
                        plt.close()

                    with col_shap2:
                        st.markdown("**Beeswarm Plot — SHAP Distribution per Feature**")
                        st.markdown(
                            '<div style="font-size:.78em;color:#94a3b8;margin-bottom:6px;">'
                        'Each dot = 1 patient. Red = high feature value, Blue = low. '
                        'Right of 0 = increases risk.</div>',
                            unsafe_allow_html=True)
                        fig_bsw, ax_bsw = plt.subplots(
                            figsize=(6, max(4.5, len(shap_feat_names)*0.44)),
                            facecolor='none')
                        ax_bsw.set_facecolor('none')
                        bg_arr = bg_data.values
                        np.random.seed(42)
                        for fi_rank, real_idx in enumerate(sorted_idx):
                            feat_col_vals = bg_arr[:, real_idx]
                            shap_col_vals = shap_vals[:, real_idx]
                            ptp = feat_col_vals.max() - feat_col_vals.min()
                            feat_norm = (feat_col_vals - feat_col_vals.min()) / (ptp + 1e-9)
                            y_pos  = len(sorted_idx) - 1 - fi_rank
                            jitter = np.random.uniform(-0.35, 0.35, len(shap_col_vals))
                            ax_bsw.scatter(shap_col_vals, y_pos + jitter,
                                           c=feat_norm, cmap=ucharts.cmap('diverging'),
                                           alpha=0.50, s=9, linewidths=0)
                        ax_bsw.axvline(0, color=ucharts.color('fg_muted'), linestyle='--', linewidth=1.0)
                        ax_bsw.set_yticks(range(len(shap_feat_names)))
                        ax_bsw.set_yticklabels(s_labels, color=ucharts.color('fg'), fontsize=7.5)
                        ax_bsw.set_xlabel("SHAP value", color=ucharts.color('fg'), fontsize=9)
                        ax_bsw.set_title("Beeswarm — All Patients",
                                         color=ucharts.color('fg'), fontsize=10, fontweight='700', pad=10)
                        ax_bsw.tick_params(colors=ucharts.color('fg'), labelsize=8)
                        for sp in ['top','right']:   ax_bsw.spines[sp].set_visible(False)
                        for sp in ['left','bottom']: ax_bsw.spines[sp].set_color(ucharts.color('spine'))
                        # Colorbar legend
                        sm = plt.cm.ScalarMappable(cmap=ucharts.cmap('diverging'),
                                                   norm=plt.Normalize(vmin=0, vmax=1))
                        sm.set_array([])
                        cb2 = plt.colorbar(sm, ax=ax_bsw, fraction=0.03, pad=0.02)
                        cb2.set_label('Feature Value (normalised)', color=ucharts.color('fg'), fontsize=7)
                        cb2.ax.tick_params(colors=ucharts.color('fg'), labelsize=6)
                        plt.tight_layout()
                        st.pyplot(fig_bsw, transparent=True)
                        plt.close()

                    # ── Row 2: Waterfall for a single patient ─────────────────
                    st.markdown("---")
                    st.markdown("#### Waterfall Chart — Single Patient Explanation")
                    st.markdown(
                        '<div class="alert-info">Select a patient sample to see exactly which features '
                    'pushed the prediction <b style="color:#ef4444;">toward High Risk</b> '
                    'or <b style="color:#10b981;">toward Low Risk</b> for that individual.</div>',
                        unsafe_allow_html=True)

                    sample_idx = st.slider(
                        "Patient Sample Index",
                        0, len(shap_vals)-1, 0,
                        key="shap_waterfall_idx"
                    )
                    sv_single  = shap_vals[sample_idx]
                    expected_v = float(np.mean(shap_vals.sum(axis=1))) if np.mean(shap_vals.sum(axis=1)) > 0 else 0.5

                    # Build waterfall data: sort by absolute SHAP desc, show top-12
                    wf_pairs = sorted(zip(shap_display, sv_single),
                                      key=lambda x: abs(x[1]), reverse=True)[:12]
                    wf_labels_raw, wf_shap_vals = zip(*wf_pairs)
                    wf_labels = list(wf_labels_raw)
                    wf_shap   = np.array(wf_shap_vals)
                    # cumulative baseline bars
                    base     = expected_v
                    wf_starts, wf_ends = [], []
                    cur = base
                    for sv_w in wf_shap[::-1]:   # bottom-to-top in plot
                        wf_starts.append(cur)
                        cur += sv_w
                        wf_ends.append(cur)

                    fig_wf, ax_wf = plt.subplots(
                        figsize=(9, max(5, len(wf_labels)*0.52)),
                        facecolor='none')
                    ax_wf.set_facecolor('none')
                    wf_labels_rev = wf_labels[::-1]
                    wf_shap_rev   = wf_shap[::-1]
                    wf_c = [ucharts.color('risk_high') if v >= 0 else ucharts.color('risk_low') for v in wf_shap_rev]
                    y_pos_wf = range(len(wf_labels_rev))
                    for iy, (start, sv_w, col) in enumerate(
                            zip(wf_starts, wf_shap_rev, wf_c)):
                        ax_wf.barh(iy, sv_w, left=start, color=col,
                                   height=0.6, alpha=0.88)
                        ax_wf.text(
                            start + sv_w + (0.003 if sv_w >= 0 else -0.003),
                            iy,
                            f"{'+' if sv_w>=0 else ''}{sv_w:.4f}",
                            va='center',
                            ha='left' if sv_w >= 0 else 'right',
                            color=ucharts.color('fg'), fontsize=8, fontweight='700')
                    ax_wf.axvline(base, color=ucharts.color('fg_muted'), linestyle=':', linewidth=1.5,
                                  label=f"Base value={base:.3f}")
                    ax_wf.set_yticks(list(y_pos_wf))
                    ax_wf.set_yticklabels(wf_labels_rev, color=ucharts.color('fg'), fontsize=8.5)
                    ax_wf.set_xlabel("Model Output (probability)", color=ucharts.color('fg'), fontsize=9)
                    ax_wf.set_title(
                        f"Waterfall — Patient #{sample_idx}  "
                    f"| Pred prob: {float(np.clip(base + np.sum(wf_shap), 0, 1)):.3f}",
                        color=ucharts.color('fg'), fontsize=10, fontweight='700', pad=10)
                    ax_wf.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    ax_wf.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=8)
                    for sp in ['top','right']:   ax_wf.spines[sp].set_visible(False)
                    for sp in ['left','bottom']: ax_wf.spines[sp].set_color(ucharts.color('spine'))
                    ax_wf.grid(True, axis='x', color=ucharts.color('surface'), linestyle='--',
                               linewidth=0.5, alpha=0.6)
                    # Legend for colours
                    red_patch   = mpatches.Patch(color=ucharts.color('risk_high'), alpha=0.88,
                                                 label='Increases Risk (+SHAP)')
                    green_patch = mpatches.Patch(color=ucharts.color('risk_low'), alpha=0.88,
                                                 label='Decreases Risk (−SHAP)')
                    ax_wf.legend(handles=[red_patch, green_patch],
                                 facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'),
                                 fontsize=8, loc='lower right')
                    plt.tight_layout()
                    st.pyplot(fig_wf, transparent=True)
                    plt.close()

                    # ── Row 3: SHAP vs Feature Value Scatter ──────────────────
                    st.markdown("---")
                    st.markdown("#### SHAP Value vs Feature Value — Dependence Plots")
                    st.markdown(
                        '<div class="alert-info">Shows how the SHAP value of a feature changes as its '
                    'value increases. Helps understand non-linear relationships captured by the model.</div>',
                        unsafe_allow_html=True)

                    dep_sel = st.selectbox(
                        "Select Feature for Dependence Plot",
                        s_labels,  # already sorted most→least important
                        key="shap_dep_feat"
                    )
                    dep_idx_in_sorted = s_labels.index(dep_sel)
                    dep_real_idx = sorted_idx[dep_idx_in_sorted]
                    dep_feat_vals = bg_data.values[:, dep_real_idx]
                    dep_shap_vals = shap_vals[:, dep_real_idx]

                    # Colour by most correlated other feature
                    dep_col_idx = sorted_idx[min(dep_idx_in_sorted+1, len(sorted_idx)-1)]
                    dep_col_vals = bg_data.values[:, dep_col_idx]
                    col_label = shap_display[dep_col_idx]
                    ptp_c = dep_col_vals.max() - dep_col_vals.min()
                    dep_col_norm = (dep_col_vals - dep_col_vals.min()) / (ptp_c + 1e-9)

                    fig_dep, ax_dep = plt.subplots(figsize=(9, 4.5), facecolor='none')
                    ax_dep.set_facecolor('none')
                    sc = ax_dep.scatter(dep_feat_vals, dep_shap_vals,
                                        c=dep_col_norm, cmap=ucharts.cmap('sequential', reverse=True),
                                        alpha=0.55, s=18, linewidths=0)
                    ax_dep.axhline(0, color=ucharts.color('fg_muted'), linestyle='--', linewidth=1)
                    ax_dep.set_xlabel(f"{dep_sel} (scaled)", color=ucharts.color('fg'), fontsize=9)
                    ax_dep.set_ylabel(f"SHAP value of {dep_sel}", color=ucharts.color('fg'), fontsize=9)
                    ax_dep.set_title(
                        f"Dependence Plot: {dep_sel}  (colour = {col_label})",
                        color=ucharts.color('fg'), fontsize=10, fontweight='700', pad=10)
                    ax_dep.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    for sp in ['top','right']:   ax_dep.spines[sp].set_visible(False)
                    for sp in ['left','bottom']: ax_dep.spines[sp].set_color(ucharts.color('spine'))
                    cb_dep = plt.colorbar(sc, ax=ax_dep, fraction=0.025, pad=0.02)
                    cb_dep.set_label(col_label, color=ucharts.color('fg'), fontsize=8)
                    cb_dep.ax.tick_params(colors=ucharts.color('fg'), labelsize=7)
                    plt.tight_layout()
                    st.pyplot(fig_dep, transparent=True)
                    plt.close()

                    # ── SHAP Summary Table ─────────────────────────────────────
                    st.markdown("---")
                    st.markdown("#### SHAP Feature Impact Table — Global Summary")
                    shap_df = pd.DataFrame({
                        "Rank":          list(range(1, len(sorted_idx)+1)),
                        "Feature":       s_labels,
                        "Mean |SHAP|": [f"{v:.5f}" for v in s_vals],
                        "% of Impact":   [f"{v/s_vals.sum()*100:.2f}%" for v in s_vals],
                        "Avg Direction": [
                            "Increases Risk" if shap_vals[:, i].mean() > 0
                            else "Decreases Risk"
                            for i in sorted_idx
                        ],
                    })
                    st.dataframe(shap_df, hide_index=True, width="stretch")
                    st.download_button(
                        "Export SHAP Table (CSV)",
                        shap_df.to_csv(index=False).encode(),
                        f"shap_impact_{shap_sel.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.csv",
                        "text/csv", width="stretch")

                    st.markdown(
                        '<div class="alert-info" style="font-size:.82em;">'
                    '<b>SHAP Interpretation Guide:</b><br>'
                    '• <b>Mean |SHAP|</b> = average magnitude of this feature across all patients.<br>'
                    '• <b>Beeswarm</b>: Red dots = high feature value, Blue = low, '
                    'right of centre = pushes toward High Risk.<br>'
                    '• <b>Waterfall</b>: Shows exact contribution of top features for ONE patient.<br>'
                    '• <b>Dependence Plot</b>: Reveals non-linear effects — how SHAP changes as feature increases.</div>',
                        unsafe_allow_html=True)
                else:
                    st.warning("Could not compute SHAP values. Please try a different model.")

    # ══════════════════════════════════════════════════════════════════
    # TAB 9 — Threshold & Clinical Utility   (Run 4)
    # ══════════════════════════════════════════════════════════════════
    if 'Threshold & Clinical Utility' in _slot:
        with _slot['Threshold & Clinical Utility']:
            section_header("T", "Threshold & Clinical Utility",
                           "How the decision threshold was chosen, and what it costs")

            thr_cfg = load_thresholds()
            # Tab 9 is the one place the virtual Ensemble entry belongs — it is the app's
            # default prediction path, so its operating point matters most here.
            thr_results = load_results(include_virtual=True)
            thr_models = [m for m in thr_results if thr_results[m].get("threshold_profile")]

            if not thr_models:
                st.markdown('<div class="alert-warning">No threshold analysis found. '
                        'Retrain the models to generate it.</div>', unsafe_allow_html=True)
            else:
                pol = thr_cfg.get("policy", {})
                st.markdown(f"""
            <div class="panel">
            <h4 style="color:#f59e0b;margin-bottom:8px;">Why not 0.50?</h4>
            <p style="color:#94a3b8;font-size:.87em;line-height:1.7;margin:0;">
            0.50 is the default for a <b>balanced-accuracy</b> objective. This is a
            <b>screening</b> tool — it triages patients into further testing rather than
            diagnosing them, so a missed case costs far more than a false alarm.
            Thresholds are therefore chosen from the holdout ROC as the highest value
            still achieving <b>&ge; {pol.get('target_sensitivity', 0.85):.0%} sensitivity</b>,
            rather than inherited from convention.
            </p></div>""", unsafe_allow_html=True)

                thr_sel = st.selectbox("Model", thr_models,
                                       index=thr_models.index("Ensemble Voting")
                                       if "Ensemble Voting" in thr_models else 0,
                                       key="thr_tab_model")
                prof = thr_results[thr_sel]["threshold_profile"]
                ops  = prof["operating_points"]

                # ── Operating point comparison ─────────────────────────────
                st.markdown("#### Candidate Operating Points")
                op_rows = []
                for key, label in [("rule_out", "Rule-out (≥95% sens)"),
                                   ("recommended", "★ Recommended (≥85% sens)"),
                                   ("rule_in", "Rule-in (≥90% spec)"),
                                   ("youden_j", "Youden's J"),
                                   ("f2_optimal", "F2-optimal"),
                                   ("legacy_half", "Legacy 0.50")]:
                    o = ops[key]
                    op_rows.append({
                        "Operating Point": label,
                        "Threshold": f"{o['threshold']:.3f}",
                        "Sensitivity": f"{o['sensitivity']:.1%}",
                        "Specificity": f"{o['specificity']:.1%}",
                        "PPV": f"{o['ppv']:.1%}",
                        "NPV": f"{o['npv']:.1%}",
                        "Missed / 1,000": f"{o['missed_per_1000']:.0f}",
                    })
                st.dataframe(pd.DataFrame(op_rows), hide_index=True, width="stretch")

                rec, leg = ops["recommended"], ops["legacy_half"]
                saved = leg["missed_per_1000"] - rec["missed_per_1000"]
                st.markdown(
                    f'<div class="alert-info">Moving from <b>0.500</b> to '
                f'<b>{rec["threshold"]:.3f}</b> recovers <b>{saved:.0f} missed cases '
                f'per 1,000 patients</b> (sensitivity {leg["sensitivity"]:.1%} → '
                    f'{rec["sensitivity"]:.1%}), at a specificity cost of '
                    f'{leg["specificity"] - rec["specificity"]:.1%}.</div>',
                    unsafe_allow_html=True)

                # ── Sweep chart ────────────────────────────────────────────
                st.markdown("---")
                st.markdown("#### Sensitivity / Specificity Trade-off")
                sweep = prof["sweep"]
                sx = [s["threshold"] for s in sweep]
                fig_sw, ax_sw = plt.subplots(figsize=(9, 3.8), facecolor='none')
                ax_sw.set_facecolor('none')
                # Four operating characteristics. None of them is a risk band, so they take
                # the categorical ramp — risk hues here would imply a clinical reading the
                # curves do not carry.
                for key, col, lbl in zip(
                        ["sensitivity", "specificity", "ppv", "npv"],
                        ucharts.categorical(4),
                        ["Sensitivity (recall)", "Specificity", "PPV (precision)", "NPV"]):
                    ax_sw.plot(sx, [s[key] for s in sweep], color=col, lw=2, label=lbl)
                ax_sw.axvline(rec["threshold"], color=ucharts.color('risk_borderline'), ls='--', lw=1.8,
                              label=f"Operating point ({rec['threshold']:.3f})")
                ax_sw.axvline(0.50, color=ucharts.color('reference'), ls=':', lw=1.5, label="Legacy 0.50")
                ax_sw.axhline(pol.get("target_sensitivity", 0.85), color=ucharts.color('risk_high'),
                              ls=':', lw=1, alpha=0.5)
                ax_sw.set_xlabel("Decision threshold", color=ucharts.color('fg'), fontsize=9)
                ax_sw.set_ylabel("Metric value", color=ucharts.color('fg'), fontsize=9)
                ax_sw.set_ylim(0, 1.02)
                ax_sw.tick_params(colors=ucharts.color('fg'), labelsize=8)
                ax_sw.grid(True, color=ucharts.color('surface'), ls='--', lw=0.5, alpha=0.6)
                for sp in ['top', 'right']:   ax_sw.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_sw.spines[sp].set_color(ucharts.color('spine'))
                ax_sw.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=7.5,
                             loc='center right')
                plt.tight_layout()
                st.pyplot(fig_sw, transparent=True)
                plt.close()

                # ── Decision curve ─────────────────────────────────────────
                st.markdown("---")
                st.markdown("#### Decision Curve Analysis (Net Benefit)")
                st.markdown(
                    '<div class="alert-info" style="font-size:.82em;">'
                'Net benefit weighs true positives against false positives using the '
                'threshold probability as the exchange rate. A model is clinically '
                'useful wherever its curve sits <b>above both</b> "treat all" and '
                '"treat none". <i>(Vickers &amp; Elkin, 2006)</i></div>',
                    unsafe_allow_html=True)
                nb = prof["net_benefit"]
                nx = [p["pt"] for p in nb]
                fig_nb, ax_nb = plt.subplots(figsize=(9, 3.6), facecolor='none')
                ax_nb.set_facecolor('none')
                ax_nb.plot(nx, [p["model"] for p in nb], color=ucharts.color('risk_low'), lw=2.2,
                           label=f"{thr_sel}")
                ax_nb.plot(nx, [p["treat_all"] for p in nb], color=ucharts.color('reference'), lw=1.5,
                           ls='--', label="Treat all")
                ax_nb.axhline(0, color=ucharts.color('fg_subtle'), lw=1.5, ls=':', label="Treat none")
                ax_nb.axvline(rec["threshold"], color=ucharts.color('risk_borderline'), ls='--', lw=1.6,
                              label=f"Operating point")
                ax_nb.set_xlabel("Threshold probability", color=ucharts.color('fg'), fontsize=9)
                ax_nb.set_ylabel("Net benefit", color=ucharts.color('fg'), fontsize=9)
                ax_nb.tick_params(colors=ucharts.color('fg'), labelsize=8)
                ax_nb.grid(True, color=ucharts.color('surface'), ls='--', lw=0.5, alpha=0.6)
                for sp in ['top', 'right']:   ax_nb.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_nb.spines[sp].set_color(ucharts.color('spine'))
                ax_nb.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=8)
                plt.tight_layout()
                st.pyplot(fig_nb, transparent=True)
                plt.close()

                # ── Risk bands ─────────────────────────────────────────────
                st.markdown("---")
                st.markdown("#### Risk Bands in Use")
                rb = prof["risk_bands"]
                st.dataframe(pd.DataFrame([
                    {"Band": "Low", "Probability": f"< {rb['low_max']:.3f}",
                     "Action": "Confidently excluded — routine review"},
                    {"Band": "Borderline", "Probability": f"{rb['low_max']:.3f} – {rb['borderline_max']:.3f}",
                     "Action": "Below action threshold — lifestyle advice, re-assess"},
                    {"Band": "Intermediate", "Probability": f"{rb['borderline_max']:.3f} – {rb['intermediate_max']:.3f}",
                     "Action": "Above action threshold — further testing indicated"},
                    {"Band": "High", "Probability": f"≥ {rb['intermediate_max']:.3f}",
                     "Action": "Escalate directly to clinical review"},
                ]), hide_index=True, width="stretch")

                st.download_button(
                    "Export Threshold Sweep (CSV)",
                    pd.DataFrame(sweep).to_csv(index=False).encode(),
                    f"threshold_sweep_{thr_sel.replace(' ', '_')}.csv",
                    "text/csv", width="stretch")

    # ══════════════════════════════════════════════════════════════════
    # TAB 10 — Subgroup Performance & Fairness   (Run 5)
    # ══════════════════════════════════════════════════════════════════
    if 'Subgroup Performance & Fairness' in _slot:
        with _slot['Subgroup Performance & Fairness']:
            section_header("F", "Subgroup Performance & Fairness",
                           "Where the model is strong, where it is weak, and why")

            subs = get_subgroup_performance("Ensemble Voting")
            thr_cfg2 = load_thresholds()

            if not subs:
                st.markdown('<div class="alert-warning">No subgroup analysis found. '
                        'Retrain the models to generate it.</div>', unsafe_allow_html=True)
            else:
                st.markdown("""
            <div class="panel">
            <h4 style="color:#60a5fa;margin-bottom:8px;">How to read this</h4>
            <p style="color:#94a3b8;font-size:.86em;line-height:1.75;margin:0;">
            Aggregate AUC hides variation across clinical strata. Two findings matter:
            <br><br>
            <b style="color:#10b981;">1. Calibration holds everywhere.</b> Predicted
            probabilities match observed rates in every subgroup (gaps under 0.02), so
            the risk numbers mean what they say regardless of patient type. This is the
            property that matters most for a risk score.
            <br><br>
            <b style="color:#f59e0b;">2. Within-stratum AUC is lower — and that is
            expected.</b> Stratifying on a strong predictor removes its variance from
            inside the stratum, so ranking within a homogeneous group is inherently
            harder. This was tested directly: models trained <i>only</i> on each weak
            stratum performed <b>worse</b> than the global model (55–59: −0.013;
            cholesterol "well above": −0.033). The ceiling is the data, not the
            algorithm — so specialist models are the wrong response.
            <br><br>
            <b style="color:#ef4444;">The real defect, now fixed:</b> one global
            threshold applied to strata whose baseline risk ranges 28%→65% gave 64%
            sensitivity under 45 while flagging 95% of over-60s. Thresholds are now
            age-stratified, equalising sensitivity at ~85% across every band.
            </p></div>""", unsafe_allow_html=True)

                # ── Stratified thresholds in force ─────────────────────────
                strat_ens = (thr_cfg2.get("stratified", {}) or {}).get("Ensemble Voting", {})
                if strat_ens:
                    st.markdown("#### Age-Stratified Operating Points in Force")
                    band_lookup = {lv["level"]: lv for lv in subs.get("Age band", [])}
                    srows = []
                    for label, info in sorted(strat_ens.items(),
                                              key=lambda kv: kv[1]["band_index"]):
                        lv = band_lookup.get(label, {})
                        srows.append({
                            "Age Band": label,
                            "Threshold": f"{info['threshold']:.3f}",
                            "n (holdout)": f"{lv.get('n', 0):,}",
                            "Prevalence": f"{lv.get('prevalence', 0):.1%}",
                            "Sensitivity": f"{lv.get('sensitivity', 0):.1%}",
                            "Specificity": f"{lv.get('specificity', 0):.1%}",
                            "PPV": f"{lv.get('ppv', 0):.1%}",
                            "Flagged": f"{lv.get('flagged_rate', 0):.1%}",
                        })
                    st.dataframe(pd.DataFrame(srows), hide_index=True,
                                 width="stretch")
                    st.markdown(
                        '<div class="alert-info">Sensitivity is now equalised across age '
                    'bands — the <b>equal opportunity</b> fairness criterion. Under a '
                    'single global threshold it ranged from 64% to 98%.</div>',
                        unsafe_allow_html=True)

                # ── Per-dimension detail ───────────────────────────────────
                st.markdown("---")
                dim_sel = st.selectbox("Subgroup dimension", list(subs.keys()),
                                       key="fair_dim_sel")
                levels = subs[dim_sel]

                st.dataframe(pd.DataFrame([{
                    "Level": lv["level"],
                    "n": f"{lv['n']:,}",
                    "Prevalence": f"{lv['prevalence']:.1%}",
                    "AUC": f"{lv['auc']:.4f}",
                    "95% CI": (f"{lv['auc_ci_low']:.3f} – {lv['auc_ci_high']:.3f}"
                               if lv["auc_ci_low"] is not None else "—"),
                    "Brier": f"{lv['brier']:.4f}",
                    "Calib. gap": f"{lv['calibration_gap']:+.3f}",
                    "Sensitivity": f"{lv['sensitivity']:.1%}",
                    "Specificity": f"{lv['specificity']:.1%}",
                } for lv in levels]), hide_index=True, width="stretch")

                # ── AUC with CI, and calibration gap ───────────────────────
                lbls = [lv["level"] for lv in levels]
                aucs_s = [lv["auc"] for lv in levels]
                errs = [[lv["auc"] - (lv["auc_ci_low"] or lv["auc"]) for lv in levels],
                        [(lv["auc_ci_high"] or lv["auc"]) - lv["auc"] for lv in levels]]

                cfa, cfb = st.columns(2)
                with cfa:
                    st.markdown("**Discrimination (AUC ± 95% CI)**")
                    fig_f, ax_f = plt.subplots(figsize=(5.4, 3.4), facecolor='none')
                    ax_f.set_facecolor('none')
                    bars_f = ax_f.barh(lbls[::-1], aucs_s[::-1],
                                       xerr=[errs[0][::-1], errs[1][::-1]],
                                       color=[ucharts.color('risk_low') if a >= 0.80 else ucharts.color('risk_borderline')
                                              if a >= 0.75 else ucharts.color('risk_high')
                                              for a in aucs_s][::-1],
                                       height=0.6, ecolor=ucharts.color('reference'), capsize=3)
                    overall = results.get("Random Forest", {}).get("auc", 0.80)
                    ax_f.axvline(overall, color=ucharts.color('primary'), ls='--', lw=1.5,
                                 label=f"Overall ({overall:.3f})")
                    ax_f.set_xlim(0.5, 0.95)
                    ax_f.set_xlabel("AUC", color=ucharts.color('fg'), fontsize=8.5)
                    ax_f.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    for sp in ['top', 'right']:   ax_f.spines[sp].set_visible(False)
                    for sp in ['left', 'bottom']: ax_f.spines[sp].set_color(ucharts.color('spine'))
                    ax_f.legend(facecolor=ucharts.color('surface'), labelcolor=ucharts.color('fg'), fontsize=7.5)
                    plt.tight_layout()
                    st.pyplot(fig_f, transparent=True)
                    plt.close()

                with cfb:
                    st.markdown("**Calibration gap (predicted − observed)**")
                    gaps = [lv["calibration_gap"] for lv in levels]
                    fig_g, ax_g = plt.subplots(figsize=(5.4, 3.4), facecolor='none')
                    ax_g.set_facecolor('none')
                    ax_g.barh(lbls[::-1], gaps[::-1],
                              color=[ucharts.color('risk_low') if abs(g) < 0.02 else ucharts.color('risk_borderline')
                                     if abs(g) < 0.05 else ucharts.color('risk_high')
                                     for g in gaps][::-1], height=0.6)
                    ax_g.axvline(0, color=ucharts.color('fg_muted'), lw=1.2)
                    ax_g.axvspan(-0.02, 0.02, color=ucharts.color('risk_low'), alpha=0.10)
                    ax_g.set_xlabel("Gap (0 = perfectly calibrated)",
                                    color=ucharts.color('fg'), fontsize=8.5)
                    ax_g.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    for sp in ['top', 'right']:   ax_g.spines[sp].set_visible(False)
                    for sp in ['left', 'bottom']: ax_g.spines[sp].set_color(ucharts.color('spine'))
                    plt.tight_layout()
                    st.pyplot(fig_g, transparent=True)
                    plt.close()

                st.markdown(
                    '<div class="alert-info" style="font-size:.82em;">Green band marks '
                '±0.02 calibration gap — the zone where predicted probabilities can be '
                'read as literal risk estimates. Every subgroup falls inside or very '
                'near it, including those with lower AUC.</div>',
                    unsafe_allow_html=True)

                flat = [{"Dimension": d, **lv} for d, lvs in subs.items() for lv in lvs]
                st.download_button(
                    "Export Full Subgroup Report (CSV)",
                    pd.DataFrame(flat).to_csv(index=False).encode(),
                    "subgroup_fairness_report.csv", "text/csv",
                    width="stretch")

    # ══════════════════════════════════════════════════════════════════
    # TAB 11 — Clinical Benchmark & Feature Value   (Run 6)
    # ══════════════════════════════════════════════════════════════════
    if 'Clinical Benchmark & Feature Value' in _slot:
        with _slot['Clinical Benchmark & Feature Value']:
            section_header("B", "Clinical Benchmark & Feature Value",
                           "Is it better than existing practice, and what would improve it?")

            bm = load_benchmarks()
            if not bm:
                st.markdown('<div class="alert-warning">No benchmark analysis found. '
                        'Retrain the models to generate it.</div>',
                            unsafe_allow_html=True)
            else:
                interp = bm.get("interpretation", {})
                cbm = bm.get("clinical_benchmark", {})
                mlm = cbm.get("ml_model", {})

                st.markdown(f"""
            <div class="panel">
            <h4 style="color:#10b981;margin-bottom:8px;">Headline</h4>
            <p style="color:#cbd5e1;font-size:.9em;line-height:1.75;margin:0;">
            {esc(interp.get('headline', ''))}</p>
            <h4 style="color:#f59e0b;margin:14px 0 8px;">The ceiling</h4>
            <p style="color:#94a3b8;font-size:.86em;line-height:1.75;margin:0;">
            {esc(interp.get('ceiling', ''))}</p>
            </div>""", unsafe_allow_html=True)

                # ── Benchmark table ────────────────────────────────────────
                st.markdown("#### Versus Established Clinical Practice")
                brows = [{
                    "Model": mlm.get("name", "ML ensemble"),
                    "AUC": f"{mlm.get('auc', 0):.4f}",
                    "95% CI": (f"{mlm.get('auc_ci_low'):.3f} – {mlm.get('auc_ci_high'):.3f}"
                               if mlm.get("auc_ci_low") is not None else "—"),
                    "ML advantage": "—", "95% CI (diff)": "—", "Significant": "—",
                }]
                for name, d in cbm.get("baselines", {}).items():
                    a = d.get("ml_advantage", {})
                    brows.append({
                        "Model": name,
                        "AUC": f"{d.get('auc', 0):.4f}",
                        "95% CI": (f"{d.get('auc_ci_low'):.3f} – {d.get('auc_ci_high'):.3f}"
                                   if d.get("auc_ci_low") is not None else "—"),
                        "ML advantage": f"{a.get('difference', 0):+.4f}",
                        "95% CI (diff)": (f"{a.get('ci_low'):+.4f} – {a.get('ci_high'):+.4f}"
                                          if a.get("ci_low") is not None else "—"),
                        "Significant": "Yes" if a.get("significant") else "No",
                    })
                st.dataframe(pd.DataFrame(brows), hide_index=True, width="stretch")

                fair = cbm.get("baselines", {}).get("Clinical logistic regression", {})
                if fair:
                    fa = fair.get("ml_advantage", {})
                    st.markdown(
                        f'<div class="alert-info"><b>The comparison that matters.</b> '
                    f'Against conventional logistic regression on the same seven risk '
                    f'factors — identical inputs, identical missing lipids — the ML '
                    f'ensemble gains <b>{fa.get("difference", 0):+.4f} AUC</b> '
                    f'(95% CI {fa.get("ci_low", 0):+.4f} to {fa.get("ci_high", 0):+.4f}). '
                    f'Statistically significant at this sample size, but clinically '
                    f'marginal — which is itself the finding.</div>',
                        unsafe_allow_html=True)

                with st.expander("Comparator definitions and caveats"):
                    for name, d in cbm.get("baselines", {}).items():
                        st.markdown(f"**{name}** — {d.get('note', '')}")
                    for c in interp.get("caveats", []):
                        st.markdown(f"- {c}")

                # ── Benchmark bar chart ────────────────────────────────────
                names = [r["Model"] for r in brows]
                vals = [float(r["AUC"]) for r in brows]
                fig_b, ax_b = plt.subplots(figsize=(9, 3.2), facecolor='none')
                ax_b.set_facecolor('none')
                bars_b = ax_b.barh(
                    [n.replace(" (", "\n(") for n in names][::-1], vals[::-1],
                    color=([ucharts.color('risk_low')] + [ucharts.color('reference')] * (len(vals) - 1))[::-1], height=0.6)
                ax_b.set_xlim(0.5, 0.88)
                ax_b.set_xlabel("AUC", color=ucharts.color('fg'), fontsize=9)
                ax_b.tick_params(colors=ucharts.color('fg'), labelsize=8)
                for sp in ['top', 'right']:   ax_b.spines[sp].set_visible(False)
                for sp in ['left', 'bottom']: ax_b.spines[sp].set_color(ucharts.color('spine'))
                for bar in bars_b:
                    ax_b.text(bar.get_width() + 0.004,
                              bar.get_y() + bar.get_height() / 2,
                              f"{bar.get_width():.4f}", va='center',
                              color=ucharts.color('fg'), fontsize=8, fontweight='600')
                plt.tight_layout()
                st.pyplot(fig_b, transparent=True)
                plt.close()

                # ── Incremental feature value ──────────────────────────────
                st.markdown("---")
                st.markdown("#### Incremental Value of Each Clinical Measurement")
                st.markdown(
                    '<div class="alert-info" style="font-size:.82em;">Feature groups added '
                'in the order a clinician acquires them — demographics are free, a BP '
                'cuff is nearly free, height/weight need a scale, cholesterol and '
                'glucose need a blood draw. Each delta answers <b>"is the next test '
                'worth ordering?"</b></div>', unsafe_allow_html=True)

                ladder = bm.get("incremental_value", [])
                if ladder:
                    st.dataframe(pd.DataFrame([{
                        "Acquisition Step": r["step"],
                        "Features": r["n_features"],
                        "AUC": f"{r['auc']:.4f}",
                        "95% CI": (f"{r['auc_ci_low']:.3f} – {r['auc_ci_high']:.3f}"
                                   if r.get("auc_ci_low") is not None else "—"),
                        "Marginal gain": ("—" if r.get("delta_auc") is None
                                          else f"{r['delta_auc']:+.4f}"),
                    } for r in ladder]), hide_index=True, width="stretch")

                    lx = [r["step"].replace("+ ", "+\n") for r in ladder]
                    ly = [r["auc"] for r in ladder]
                    fig_l, ax_l = plt.subplots(figsize=(9, 3.4), facecolor='none')
                    ax_l.set_facecolor('none')
                    ax_l.plot(range(len(ly)), ly, marker='o', color=ucharts.color('risk_low'), lw=2.2,
                              markersize=7)
                    for i, r in enumerate(ladder):
                        if r.get("delta_auc") is not None:
                            big = r["delta_auc"] >= 0.01
                            ax_l.annotate(f"{r['delta_auc']:+.4f}", (i, ly[i]),
                                          textcoords="offset points", xytext=(0, 11),
                                          ha='center', fontsize=8.5, fontweight='700',
                                          color=ucharts.color('risk_high') if big else ucharts.color('reference'))
                    ax_l.set_xticks(range(len(lx)))
                    ax_l.set_xticklabels(lx, color=ucharts.color('fg'), fontsize=7.5)
                    ax_l.set_ylabel("AUC", color=ucharts.color('fg'), fontsize=9)
                    ax_l.set_ylim(min(ly) - 0.03, max(ly) + 0.035)
                    ax_l.tick_params(colors=ucharts.color('fg'), labelsize=8)
                    ax_l.grid(True, axis='y', color=ucharts.color('surface'), ls='--', lw=0.5, alpha=0.6)
                    for sp in ['top', 'right']:   ax_l.spines[sp].set_visible(False)
                    for sp in ['left', 'bottom']: ax_l.spines[sp].set_color(ucharts.color('spine'))
                    plt.tight_layout()
                    st.pyplot(fig_l, transparent=True)
                    plt.close()

                # ── Ceiling evidence ───────────────────────────────────────
                st.markdown("---")
                st.markdown("#### Ceiling Evidence — Why More Modelling Will Not Help")
                cc1, cc2 = st.columns(2)
                with cc1:
                    st.markdown("**Hyperparameter search**")
                    hp = bm.get("hyperparameter_search", {})
                    if hp.get("gain") is not None:
                        st.dataframe(pd.DataFrame([
                            {"Metric": "Shipped hyperparameters", "AUC": f"{hp['baseline_auc']:.4f}"},
                            {"Metric": f"Best of {hp['n_trials']} random trials", "AUC": f"{hp['tuned_auc']:.4f}"},
                            {"Metric": "Gain", "AUC": f"{hp['gain']:+.4f}"},
                            {"Metric": "Search time", "AUC": f"{hp['search_seconds']:.0f}s"},
                        ]), hide_index=True, width="stretch")
                        st.caption(hp.get("conclusion", ""))
                    else:
                        st.info("Search not yet run — `python -c \"import train_models as t; t.tune()\"`")
                with cc2:
                    st.markdown("**Interaction terms**")
                    it = bm.get("interaction_test", {})
                    if it:
                        st.dataframe(pd.DataFrame([
                            {"Model family": fam.capitalize(),
                             "Base": f"{it[fam]['base']:.4f}",
                             "+ Interactions": f"{it[fam]['with_interactions']:.4f}",
                             "Delta": f"{it[fam]['delta']:+.4f}"}
                            for fam in ("tree", "linear") if fam in it
                        ]), hide_index=True, width="stretch")
                        st.caption("Trees already represent interactions implicitly, so the "
                               "null result there indicates the functional form is "
                               "saturated. The linear gain merely confirms the terms are "
                               "real; it does not raise the ceiling.")

                # ── Data roadmap ───────────────────────────────────────────
                st.markdown("---")
                st.markdown("#### What Would Actually Improve Performance")
                wh = interp.get("what_would_help", [])
                if wh:
                    st.markdown(
                        '<div class="alert-warning" style="font-size:.85em;">'
                    'Performance is bounded by <b>available features</b>, not by the '
                    'algorithm. In descending expected value:</div>',
                        unsafe_allow_html=True)
                    for i, item in enumerate(wh, 1):
                        st.markdown(f"**{i}.** {item}")

                st.download_button(
                    "Export Benchmark Report (JSON)",
                    json.dumps(bm, indent=2).encode(),
                    "clinical_benchmark_report.json", "application/json",
                    width="stretch")


# ══════════════════════════════════════════════════════════════════
# MAIN APP ROUTER
# ══════════════════════════════════════════════════════════════════
if st.session_state.user is None:
    page_login()
else:
    # ── BUG-25: revalidate the session against the database on every rerun ──
    # st.session_state.user is a plain dict captured at login. Nothing re-checked it,
    # so an account that was DELETED, BANNED or re-roled afterwards kept working with
    # its original privileges until the person chose to sign out. Banning a user did
    # not actually revoke their access — the single most important thing the ban
    # button is supposed to do.
    _live = auth_db.get_user_by_id(st.session_state.user['id'])
    if _live is None:
        st.session_state.user = None
        st.markdown('<div class="alert-warning">Your account no longer exists. '
                    'You have been signed out.</div>', unsafe_allow_html=True)
        st.stop()
    if _live.get('is_banned'):
        auth_db.log_activity(_live['id'], _live['username'], "Session Revoked",
                             "Banned account signed out mid-session.")
        st.session_state.user = None
        st.markdown('<div class="alert-warning">Your account has been suspended. '
                    'Contact the administrator.</div>', unsafe_allow_html=True)
        st.stop()
    # Refresh privileges in place so a role change takes effect immediately rather
    # than at next login — a demotion must not leave elevated pages reachable.
    if _live.get('role') != st.session_state.user.get('role'):
        auth_db.log_activity(_live['id'], _live['username'], "Role Refreshed",
                             f"Session role updated to {_live['role']}.")
    st.session_state.user = _live

    user = st.session_state.user
    role = user['role']

    if role == "Doctor":
        pages = [
            "Dashboard",
            "Heart Disease Prediction",
            "Patient Management",
            "Prediction History",
            "Model Performance",
            "Reports",
            "Profile",
        ]
    elif role == "Admin":
        pages = [
            "Dashboard",
            "Doctor Management",
            "Patient Management",
            "Prediction Management",
            "Model Performance",
            "Reports",
            "Dataset Management",
            "Analytics",
            "Profile",
        ]
    else:  # SuperAdmin
        pages = [
            "Dashboard",
            "Admin Management",
            "Doctor Management",
            "Model Performance",
            "Role & Permission Management",
            "System Settings",
            "ML Model Management",
            "Activity Logs",
            "Backup & Restore",
            "Analytics",
            "Profile",
        ]

    choice = render_sidebar(user, pages)

    # Doctor routes
    if choice == "Dashboard":
        px.page_dashboard(user)
    elif choice == "Heart Disease Prediction":
        page_diagnosis(user)
    elif choice == "Patient Management":
        px.page_patient_management(user)
    elif choice == "Prediction History":
        page_history(user)
    elif choice == "Reports":
        px.page_reports(user)
    elif choice == "Profile":
        page_profile(user)
    elif choice == "Model Performance":
        page_model_performance(user)

    # Admin routes
    elif choice == "Doctor Management":
        px.page_doctor_management(user)
    elif choice == "Prediction Management":
        px.page_prediction_management(user)
    elif choice == "Dataset Management":
        px.page_dataset_management(user)
    elif choice == "Analytics":
        page_admin_analytics(user)

    # SuperAdmin routes
    elif choice == "Admin Management":
        px.page_admin_management(user)
    elif choice == "Role & Permission Management":
        px.page_role_permissions(user)
    elif choice == "System Settings":
        px.page_system_settings(user)
    elif choice == "ML Model Management":
        page_training(user)
    elif choice == "Activity Logs":
        page_audits(user)
    elif choice == "Backup & Restore":
        px.page_backup_restore(user)
