"""
HeartGuard AI - Extended Page Functions
All new pages for Doctor / Admin / SuperAdmin expanded navigation.
"""
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import json, os, zipfile, io, hashlib
from datetime import datetime, date
import auth_db
import feature_engineering as fe

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")


# ── shared helpers ─────────────────────────────────────────────────
def _kpi(val, label, color, bg, border):
    return f"""<div class="kpi-card" style="background:{bg};border-color:{border};">
    <div class="kpi-val" style="color:{color};">{val}</div>
    <div class="kpi-lbl">{label}</div>
    </div>"""


def _load_results(include_virtual=False):
    """Trained-model results; the virtual Ensemble entry is excluded by default (Run 4)."""
    _rp = os.path.join(MODELS_DIR, "results.json")
    if os.path.exists(_rp):
        try:
            with open(_rp) as _f:
                _d = json.load(_f)
            return _d if include_virtual else {
                k: v for k, v in _d.items() if not v.get("is_virtual")}
        except Exception:
            return {}
    return {}


def _load_config():
    cfg_path = os.path.join(MODELS_DIR, "config.json")
    defaults = {k: True for k in ["Logistic Regression", "Support Vector Machine (SVM)",
                                   "Decision Tree", "Random Forest", "XGBoost"]}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            return json.load(f)
    return defaults


def _section_header(title, subtitle=""):
    sub = f'<p class="hg-subtitle">{subtitle}</p>' if subtitle else ""
    st.markdown(f'<p class="hg-title">{title}</p>{sub}', unsafe_allow_html=True)
    st.markdown('<hr class="hg-divider">', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# SHARED — DASHBOARD (role-aware)
# ══════════════════════════════════════════════════════════════════
def page_dashboard(user):
    role = user['role']
    _section_header("Dashboard", f"Welcome back, {user['fullname']}")

    all_users = auth_db.get_all_users()
    all_preds = auth_db.get_predictions(
        user_id=user['id'] if role == 'Doctor' else None)
    results = _load_results()
    cfg = _load_config()

    risk_c = sum(1 for p in all_preds if p['predicted_class'] == 1)
    safe_c = len(all_preds) - risk_c
    doctors = sum(1 for u in all_users if u['role'] == 'Doctor')

    if role == 'Doctor':
        my_total = len(all_preds)
        st.markdown('<div class="kpi-wrap">' +
                    _kpi(my_total, "My Total Scans", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                    _kpi(risk_c, "High Risk", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                    _kpi(safe_c, "Low Risk", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                    _kpi(sum(cfg.values()), "Active AI Models", "#7c3aed", "linear-gradient(135deg,#f5f3ff,#ede9fe)", "#c4b5fd") +
                    '</div>', unsafe_allow_html=True)
    else:
        admins = sum(1 for u in all_users if u['role'] == 'Admin')
        st.markdown('<div class="kpi-wrap">' +
                    _kpi(len(all_preds), "Total Predictions", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                    _kpi(risk_c, "High Risk Cases", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                    _kpi(safe_c, "Low Risk Cases", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                    _kpi(len(all_users), "Total Users", "#2563eb", "linear-gradient(135deg,#eff6ff,#dbeafe)", "#93c5fd") +
                    _kpi(doctors, "Doctors", "#0891b2", "linear-gradient(135deg,#ecfeff,#cffafe)", "#67e8f9") +
                    _kpi(sum(cfg.values()), "Active Models", "#7c3aed", "linear-gradient(135deg,#f5f3ff,#ede9fe)", "#c4b5fd") +
                    '</div>', unsafe_allow_html=True)

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Recent Predictions")
        if all_preds:
            pdf = pd.DataFrame(all_preds[:10])
            pdf['Risk'] = pdf['predicted_class'].apply(lambda x: "High" if x == 1 else "Low")
            pdf['Prob'] = pdf['probability'].apply(lambda x: f"{x:.1%}")
            cols = ['timestamp', 'age', 'Risk', 'Prob', 'model_used']
            if role != 'Doctor' and 'doctor_name' in pdf.columns:
                cols.insert(1, 'doctor_name')
            st.dataframe(pdf[cols].rename(columns={
                'timestamp': 'Time', 'age': 'Age', 'model_used': 'Model', 'doctor_name': 'Doctor'
            }), hide_index=True, use_container_width=True)
        else:
            st.markdown('<div class="alert-info">No predictions yet.</div>', unsafe_allow_html=True)

    with col2:
        st.markdown("#### Model Performance")
        if results:
            fig, ax = plt.subplots(figsize=(5, 3.2), facecolor='none')
            ax.set_facecolor('none')
            names = [n.replace("(", "\n(") for n in results]
            accs = [d['accuracy'] for d in results.values()]
            colors = ['#ef4444', '#3b82f6', '#f59e0b', '#10b981', '#a855f7']
            bars = ax.bar(names, accs, color=colors[:len(names)], width=0.5)
            ax.set_ylim(0, 1.05)
            ax.tick_params(colors='#374151', labelsize=7)
            for sp in ['top', 'right']:
                ax.spines[sp].set_visible(False)
            for sp in ['left', 'bottom']:
                ax.spines[sp].set_color('#fca5a5')
            for bar in bars:
                ax.annotate(f"{bar.get_height():.1%}",
                            xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points",
                            ha='center', color='#374151', fontsize=7, fontweight='600')
            plt.tight_layout()
            st.pyplot(fig, transparent=True)
            plt.close()
        else:
            st.markdown('<div class="alert-info">No model results yet. Train models first.</div>',
                        unsafe_allow_html=True)

    if role != 'Doctor':
        st.markdown("---")
        st.markdown("#### Recent System Activity")
        logs = auth_db.get_system_logs(8)
        if logs:
            ldf = pd.DataFrame(logs)[['timestamp', 'username', 'action', 'details']]
            st.dataframe(ldf, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# DOCTOR — PATIENT MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_patient_management(user):
    _section_header("Patient Management",
                    "View and manage patient prediction records linked to your account")

    preds = auth_db.get_predictions(user_id=user['id'] if user['role'] == 'Doctor' else None)

    if not preds:
        st.markdown('<div class="alert-info">No patient records found.</div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame(preds)
    df['Risk'] = df['predicted_class'].apply(lambda x: "High Risk" if x == 1 else "Low Risk")
    df['Confidence'] = df['probability'].apply(lambda x: f"{x:.1%}")

    total = len(df)
    high = int(df['predicted_class'].sum())
    low = total - high

    st.markdown('<div class="kpi-wrap">' +
                _kpi(total, "Total Patients Scanned", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                _kpi(high, "High Risk", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                _kpi(low, "Low Risk", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                '</div>', unsafe_allow_html=True)

    st.markdown("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        search = st.text_input("Search by Patient Name or Age", "")
    with c2:
        risk_f = st.selectbox("Filter Risk", ["All", "High Risk", "Low Risk"])

    fdf = df.copy()
    if search:
        fdf = fdf[fdf['patient_name'].astype(str).str.lower().str.contains(search.lower()) |
                  fdf['age'].astype(str).str.contains(search)]
    if risk_f != "All":
        fdf = fdf[fdf['Risk'] == risk_f]

    cols = ['timestamp', 'patient_name', 'age', 'gender', 'Risk', 'Confidence',
            'ap_hi', 'ap_lo', 'cholesterol', 'model_used', 'notes']
    st.dataframe(fdf[[c for c in cols if c in fdf.columns]].rename(columns={
        'timestamp': 'Date', 'patient_name': 'Patient Name', 'age': 'Age',
        'gender': 'Gender', 'ap_hi': 'Systolic BP', 'ap_lo': 'Diastolic BP',
        'cholesterol': 'Cholesterol', 'model_used': 'Model', 'notes': 'Notes'
    }), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Delete a Patient Record")
    if not fdf.empty:
        rec_opts = [f"ID:{r['id']} | {r.get('patient_name', 'N/A')} | {r['timestamp']}"
                    for _, r in fdf.iterrows()]
        sel_rec = st.selectbox("Select record to delete", rec_opts)
        sel_id = int(sel_rec.split("ID:")[1].split("|")[0])
        if st.button("Delete Selected Record", use_container_width=True):
            auth_db.delete_prediction(sel_id, user['username'])
            st.success("Record deleted.")
            st.rerun()

    csv = fdf.to_csv(index=False).encode()
    st.download_button("Export Patient Records (CSV)", csv,
                       f"patients_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv",
                       use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# DOCTOR — REPORTS
# ══════════════════════════════════════════════════════════════════
def page_reports(user):
    _section_header("Reports", "Generate and export clinical summary reports")

    preds = auth_db.get_predictions(user_id=user['id'] if user['role'] == 'Doctor' else None)
    df = pd.DataFrame(preds) if preds else pd.DataFrame()

    st.markdown("#### Summary Report Generator")
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From Date", value=date(2024, 1, 1))
    with col2:
        date_to = st.date_input("To Date", value=date.today())

    if not df.empty:
        df['date'] = pd.to_datetime(df['timestamp']).dt.date
        mask = (df['date'] >= date_from) & (df['date'] <= date_to)
        rdf = df[mask]
    else:
        rdf = df

    total = len(rdf)
    high = int(rdf['predicted_class'].sum()) if not rdf.empty else 0
    low = total - high
    avg_p = rdf['probability'].mean() if not rdf.empty else 0

    st.markdown('<div class="kpi-wrap">' +
                _kpi(total, "Scans in Period", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                _kpi(high, "High Risk", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                _kpi(low, "Low Risk", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                _kpi(f"{avg_p:.1%}", "Avg Risk Score", "#7c3aed", "linear-gradient(135deg,#f5f3ff,#ede9fe)", "#c4b5fd") +
                '</div>', unsafe_allow_html=True)

    if not rdf.empty:
        st.markdown("---")
        st.markdown("#### Risk Trend")
        daily = rdf.groupby('date')['predicted_class'].agg(['sum', 'count']).reset_index()
        daily.columns = ['date', 'high', 'total']

        fig, ax = plt.subplots(figsize=(10, 3.5), facecolor='none')
        ax.set_facecolor('none')
        ax.fill_between(range(len(daily)), daily['total'], alpha=0.12, color='#3b82f6')
        ax.fill_between(range(len(daily)), daily['high'], alpha=0.22, color='#ef4444')
        ax.plot(range(len(daily)), daily['total'], color='#3b82f6', lw=2, label='Total Scans')
        ax.plot(range(len(daily)), daily['high'], color='#ef4444', lw=2, label='High Risk')
        ax.set_xticks(range(len(daily)))
        ax.set_xticklabels([str(d) for d in daily['date']], rotation=30, ha='right',
                           fontsize=7, color='#374151')
        ax.tick_params(colors='#374151')
        for sp in ['top', 'right']:
            ax.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax.spines[sp].set_color('#fca5a5')
        ax.legend(facecolor='white', fontsize=8)
        plt.tight_layout()
        st.pyplot(fig, transparent=True)
        plt.close()

    st.markdown("---")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_txt = f"""============================================================
HEARTGUARD AI - CLINICAL SUMMARY REPORT
============================================================
Generated    : {ts}
Prepared By  : {user['fullname']} ({user['role']})
Period       : {date_from} to {date_to}

SUMMARY STATISTICS:
-------------------
Total Scans        : {total}
High Risk Cases    : {high}
Low Risk Cases     : {low}
Average Risk Score : {avg_p:.2%}
High Risk Rate     : {(high / total * 100) if total else 0:.1f}%

MODEL USAGE BREAKDOWN:
----------------------
"""
    if not rdf.empty:
        for model, cnt in rdf['model_used'].value_counts().items():
            report_txt += f"{model}: {cnt} scans\n"

    report_txt += "\nDISCLAIMER: This report is generated by HeartGuard AI for clinical support only.\n"
    report_txt += "Final diagnosis must be confirmed by a licensed medical professional.\n"
    report_txt += "=" * 60

    st.download_button("Download Summary Report (.txt)", report_txt,
                       f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt",
                       "text/plain", use_container_width=True)

    if not rdf.empty:
        csv = rdf.to_csv(index=False).encode()
        st.download_button("Export Raw Data (.csv)", csv,
                           f"raw_{datetime.now().strftime('%Y%m%d')}.csv",
                           "text/csv", use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# ADMIN — DOCTOR MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_doctor_management(user):
    _section_header("Doctor Management", "Manage doctor accounts")

    all_users = auth_db.get_all_users()
    doctors = [u for u in all_users if u['role'] == 'Doctor']

    if not doctors:
        st.markdown('<div class="alert-info">No doctors registered yet.</div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="kpi-wrap">' +
                _kpi(len(doctors), "Total Doctors", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                _kpi(sum(1 for d in doctors if not d['is_banned']), "Active", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                _kpi(sum(1 for d in doctors if d['is_banned']), "Banned", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                '</div>', unsafe_allow_html=True)

    ddf = pd.DataFrame(doctors)
    ddf['Status'] = ddf['is_banned'].apply(lambda x: "Banned" if x else "Active")
    st.dataframe(ddf[['id', 'username', 'fullname', 'email', 'specialisation', 'Status', 'created_at']]
                 .rename(columns={'id': 'ID', 'username': 'Username', 'fullname': 'Full Name',
                                  'email': 'Email', 'specialisation': 'Specialisation',
                                  'created_at': 'Created'}),
                 hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Manage Doctor")

    sel_opts = [f"{d['fullname']} (@{d['username']}) - ID:{d['id']}" for d in doctors]
    sel = st.selectbox("Select Doctor", sel_opts)
    sel_id = int(sel.split("ID:")[1])
    sel_doc = next(d for d in doctors if d['id'] == sel_id)

    can_manage = not (user['role'] == 'Admin' and sel_doc['role'] in ['Admin', 'SuperAdmin'])

    if can_manage:
        c1, c2, c3 = st.columns(3)
        with c1:
            lbl = "Unban Doctor" if sel_doc['is_banned'] else "Ban Doctor"
            if st.button(lbl, use_container_width=True):
                if sel_doc['is_banned']:
                    auth_db.unban_user(sel_id, user['username'])
                    st.success("Doctor unbanned.")
                else:
                    auth_db.ban_user(sel_id, user['username'])
                    st.success("Doctor banned.")
                st.rerun()
        with c2:
            new_spec = st.text_input("Update Specialisation", value=sel_doc.get('specialisation', ''))
            if st.button("Save Specialisation", use_container_width=True):
                auth_db.update_user_profile(sel_id, sel_doc['fullname'], sel_doc['email'], new_spec)
                st.success("Specialisation updated.")
                st.rerun()
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Delete Doctor Account", use_container_width=True):
                auth_db.delete_user(sel_id, user['username'])
                st.success("Doctor account deleted.")
                st.rerun()

    st.markdown("---")
    st.markdown(f"#### Prediction Stats for {sel_doc['fullname']}")
    d_preds = auth_db.get_predictions(user_id=sel_id)
    if d_preds:
        dp = pd.DataFrame(d_preds)
        d_high = int(dp['predicted_class'].sum())
        d_low = len(dp) - d_high
        st.markdown('<div class="kpi-wrap">' +
                    _kpi(len(dp), "Total Scans", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                    _kpi(d_high, "High Risk", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                    _kpi(d_low, "Low Risk", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                    '</div>', unsafe_allow_html=True)
    else:
        st.info("No predictions recorded for this doctor.")


# ══════════════════════════════════════════════════════════════════
# ADMIN — PREDICTION MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_prediction_management(user):
    _section_header("Prediction Management", "View, filter, delete and export all prediction records")

    all_preds = auth_db.get_predictions()
    if not all_preds:
        st.markdown('<div class="alert-info">No predictions in the system.</div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame(all_preds)
    df['Risk'] = df['predicted_class'].apply(lambda x: "High" if x == 1 else "Low")
    df['Prob'] = df['probability'].apply(lambda x: f"{x:.1%}")

    risk_c = int(df['predicted_class'].sum())
    safe_c = len(df) - risk_c

    st.markdown('<div class="kpi-wrap">' +
                _kpi(len(df), "Total Records", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                _kpi(risk_c, "High Risk", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                _kpi(safe_c, "Low Risk", "#16a34a", "linear-gradient(135deg,#f0fdf4,#dcfce7)", "#86efac") +
                '</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        search = st.text_input("Patient/Doctor", "")
    with c2:
        risk_f = st.selectbox("Verdict", ["All", "High Risk", "Low Risk"])
    with c3:
        model_opts = ["All"] + sorted(df['model_used'].unique().tolist())
        model_f = st.selectbox("Model", model_opts)
    with c4:
        doc_opts = ["All"]
        if 'doctor_name' in df.columns:
            doc_opts += sorted(df['doctor_name'].dropna().unique().tolist())
        doc_f = st.selectbox("Doctor", doc_opts)

    fdf = df.copy()
    if search:
        mask = fdf['patient_name'].astype(str).str.lower().str.contains(search.lower())
        if 'doctor_name' in fdf.columns:
            mask = mask | fdf['doctor_name'].astype(str).str.lower().str.contains(search.lower())
        fdf = fdf[mask]
    if risk_f == "High Risk":
        fdf = fdf[fdf['predicted_class'] == 1]
    elif risk_f == "Low Risk":
        fdf = fdf[fdf['predicted_class'] == 0]
    if model_f != "All":
        fdf = fdf[fdf['model_used'] == model_f]
    if doc_f != "All" and 'doctor_name' in fdf.columns:
        fdf = fdf[fdf['doctor_name'] == doc_f]

    cols = ['timestamp', 'patient_name', 'age', 'gender', 'Risk', 'Prob', 'model_used']
    if 'doctor_name' in fdf.columns:
        cols.insert(1, 'doctor_name')
    st.dataframe(fdf[[c for c in cols if c in fdf.columns]].rename(columns={
        'timestamp': 'Date', 'patient_name': 'Patient', 'age': 'Age',
        'gender': 'Gender', 'model_used': 'Model', 'doctor_name': 'Doctor'
    }), hide_index=True, use_container_width=True)

    st.markdown("---")
    c_del, c_exp, c_clr = st.columns(3)

    with c_del:
        st.markdown("**Delete Single Record**")
        if not fdf.empty:
            rec_opts = [f"ID:{r['id']} | {r.get('patient_name', 'N/A')} | {r['timestamp']}"
                        for _, r in fdf.head(50).iterrows()]
            sel_rec = st.selectbox("Select record", rec_opts, label_visibility="collapsed")
            sel_id = int(sel_rec.split("ID:")[1].split("|")[0])
            if st.button("Delete Record", use_container_width=True):
                auth_db.delete_prediction(sel_id, user['username'])
                st.success("Record deleted.")
                st.rerun()

    with c_exp:
        st.markdown("**Export Filtered Data**")
        csv = fdf.to_csv(index=False).encode()
        st.download_button("Export CSV", csv,
                           f"predictions_{datetime.now().strftime('%Y%m%d')}.csv",
                           "text/csv", use_container_width=True)

    with c_clr:
        st.markdown("**Clear ALL Predictions**")
        if st.button("Clear All Records", use_container_width=True):
            auth_db.clear_all_predictions(user['username'])
            st.success("All predictions cleared.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# ADMIN — DATASET MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_dataset_management(user):
    _section_header("Dataset Management", "Upload, preview and manage training datasets")

    data_path = os.path.join(BASE_DIR, "heart.csv")
    custom_path = os.path.join(BASE_DIR, "custom_dataset.csv")

    st.markdown("#### Current Active Dataset")
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    for label, path in [("Default Dataset (heart.csv)", data_path),
                         ("Custom Dataset", custom_path)]:
        if os.path.exists(path):
            size = os.path.getsize(path) / 1024
            df_prev = pd.read_csv(path, nrows=3)
            st.markdown(f"**{label}** - `{os.path.basename(path)}`"
                        f" | Size: `{size:.1f} KB`"
                        f" | Columns: `{len(df_prev.columns)}`")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Upload New Dataset")
    st.markdown('<div class="alert-info">CSV must contain a binary target column (cardio or target).</div>',
                unsafe_allow_html=True)

    uploaded = st.file_uploader("Choose CSV File", type="csv")
    if uploaded:
        try:
            udf = pd.read_csv(uploaded)
            st.success(f"File loaded: **{uploaded.name}** - {udf.shape[0]:,} rows x {udf.shape[1]} columns")
            st.markdown("**Preview (first 5 rows):**")
            st.dataframe(udf.head(5), use_container_width=True)

            info_df = pd.DataFrame({
                'Column': udf.columns,
                'Type': udf.dtypes.astype(str).values,
                'Non-Null': udf.count().values,
                'Sample': [str(udf[c].iloc[0]) for c in udf.columns]
            })
            st.dataframe(info_df, hide_index=True, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Save as Custom Dataset", use_container_width=True):
                    udf.to_csv(custom_path, index=False)
                    auth_db.log_activity(user['id'], user['username'], "Dataset Upload",
                                         f"Custom dataset saved: {uploaded.name} ({udf.shape[0]} rows).")
                    st.success("Custom dataset saved! Go to ML Model Management to retrain.")
            with col_b:
                if st.button("Replace Default Dataset", use_container_width=True):
                    udf.to_csv(data_path, index=False)
                    auth_db.log_activity(user['id'], user['username'], "Dataset Replace",
                                         f"Default dataset replaced: {uploaded.name} ({udf.shape[0]} rows).")
                    st.success("Default dataset replaced!")
        except Exception as e:
            st.error(f"Error reading file: {e}")

    if os.path.exists(data_path):
        st.markdown("---")
        st.markdown("#### Default Dataset Statistics")
        ds = pd.read_csv(data_path)
        tgt = 'cardio' if 'cardio' in ds.columns else 'target'
        if tgt in ds.columns:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Rows", f"{len(ds):,}")
            c2.metric("Features", str(len(ds.columns) - 1))
            c3.metric("Positive Cases", f"{ds[tgt].sum():,}")
            c4.metric("Balance", f"{ds[tgt].mean():.1%}")
            st.dataframe(ds.describe().round(2), use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — ADMIN MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_admin_management(user):
    _section_header("Admin Management", "Manage administrator accounts")

    all_users = auth_db.get_all_users()
    admins = [u for u in all_users if u['role'] in ['Admin', 'SuperAdmin'] and u['id'] != user['id']]

    st.markdown('<div class="kpi-wrap">' +
                _kpi(sum(1 for u in all_users if u['role'] == 'Admin'), "Admins", "#ef4444", "linear-gradient(135deg,#fee2e2,#fecdd3)", "#fca5a5") +
                _kpi(sum(1 for u in all_users if u['role'] == 'SuperAdmin'), "Super Admins", "#dc2626", "linear-gradient(135deg,#fff1f2,#fee2e2)", "#ef4444") +
                _kpi(sum(1 for u in all_users if u.get('is_banned') and u['role'] in ['Admin', 'SuperAdmin']), "Banned", "#6b7280", "linear-gradient(135deg,#f9fafb,#f3f4f6)", "#d1d5db") +
                '</div>', unsafe_allow_html=True)

    if not admins:
        st.info("No other admins found.")
        return

    adf = pd.DataFrame(admins)
    adf['Status'] = adf['is_banned'].apply(lambda x: "Banned" if x else "Active")
    st.dataframe(adf[['id', 'username', 'role', 'fullname', 'email', 'Status', 'created_at']],
                 hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Manage Admin Account")

    sel_opts = [f"[{a['role']}] {a['fullname']} (@{a['username']}) - ID:{a['id']}" for a in admins]
    sel = st.selectbox("Select Admin/SuperAdmin", sel_opts)
    sel_id = int(sel.split("ID:")[1])
    sel_adm = next(a for a in admins if a['id'] == sel_id)

    c1, c2, c3 = st.columns(3)
    with c1:
        lbl = "Unban" if sel_adm['is_banned'] else "Ban"
        if st.button(f"{lbl} Account", use_container_width=True):
            if sel_adm['is_banned']:
                auth_db.unban_user(sel_id, user['username'])
                st.success("Account unbanned.")
            else:
                auth_db.ban_user(sel_id, user['username'])
                st.success("Account banned.")
            st.rerun()
    with c2:
        role_options = ["Admin", "SuperAdmin", "Doctor"]
        cur_role = sel_adm['role'] if sel_adm['role'] in role_options else "Admin"
        new_role = st.selectbox("Change Role To", role_options, index=role_options.index(cur_role))
        if st.button("Update Role", use_container_width=True):
            auth_db.update_user_role(sel_id, new_role, user['username'])
            st.success(f"Role changed to {new_role}.")
            st.rerun()
    with c3:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Delete Account", use_container_width=True):
            auth_db.delete_user(sel_id, user['username'])
            st.success("Account deleted.")
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — ROLE & PERMISSION MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def page_role_permissions(user):
    _section_header("Role & Permission Management",
                    "View role capabilities and reassign user roles across the system")

    st.markdown("#### Role Capability Matrix")
    perm_data = {
        "Feature": [
            "Run Predictions", "View Own History", "View All Predictions",
            "Manage Doctors", "Manage Admins", "Upload Dataset",
            "Train Models", "Toggle Models", "View Analytics",
            "System Audit Logs", "Backup & Restore", "Role Management"
        ],
        "Doctor":    ["Yes", "Yes", "No",  "No",  "No",  "No",  "No",  "No",  "No",  "No",  "No",  "No"],
        "Admin":     ["Yes", "Yes", "Yes", "Yes", "No",  "Yes", "No",  "No",  "Yes", "No",  "No",  "No"],
        "SuperAdmin":["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes"],
    }
    st.dataframe(pd.DataFrame(perm_data), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Bulk Role Reassignment")
    st.markdown('<div class="alert-warning">Use with extreme caution.</div>', unsafe_allow_html=True)

    all_users = auth_db.get_all_users()
    others = [u for u in all_users if u['id'] != user['id']]

    c1, c2 = st.columns(2)
    with c1:
        sel_u = st.selectbox("Select User",
                             [f"[{u['role']}] {u['fullname']} (@{u['username']}) - ID:{u['id']}"
                              for u in others])
        sel_uid = int(sel_u.split("ID:")[1])
        sel_obj = next(u for u in others if u['id'] == sel_uid)
    with c2:
        role_list = ["Doctor", "Admin", "SuperAdmin"]
        cur = sel_obj['role'] if sel_obj['role'] in role_list else "Doctor"
        new_r = st.selectbox("Assign New Role", role_list, index=role_list.index(cur))

    if st.button("Apply Role Change", use_container_width=True):
        auth_db.update_user_role(sel_uid, new_r, user['username'])
        st.success(f"{sel_obj['fullname']} assigned role: {new_r}")
        st.rerun()

    st.markdown("---")
    st.markdown("#### All Users Role Overview")
    udf = pd.DataFrame(all_users)
    udf['Status'] = udf['is_banned'].apply(lambda x: "Banned" if x else "Active")
    st.dataframe(udf[['id', 'username', 'role', 'fullname', 'email', 'Status']],
                 hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — SYSTEM SETTINGS
# ══════════════════════════════════════════════════════════════════
def page_system_settings(user):
    _section_header("System Settings", "Configure platform-wide settings and default parameters")

    settings_path = os.path.join(BASE_DIR, "system_settings.json")
    defaults = {
        "app_name": "HeartGuard AI",
        "institution": "Medical University Hospital",
        # None => follow the model-derived operating point in models/thresholds.json.
        # A hardcoded 0.50 here is what silently overrode the evidence-based value.
        "risk_threshold": None,
        "allow_registration": True,
        "default_model": "Ensemble Voting",
        "max_predictions_per_day": 100,
        "session_timeout_min": 60,
        "contact_email": "admin@heartguard.ai"
    }

    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
        for k, v in defaults.items():
            settings.setdefault(k, v)
    else:
        settings = defaults.copy()

    # ──────────────────────────────────────────────────────────────
    # Run 4 — Decision threshold governance
    #
    # The threshold used to be a naked "Risk Threshold (%)" slider with no indication
    # of what moving it would do. That is precisely how 0.50 sat unexamined while it
    # missed 31% of diseased patients. The control now shows the measured clinical
    # consequence of the selected value, sourced from the trained model's ROC.
    # ──────────────────────────────────────────────────────────────
    thr_path = os.path.join(MODELS_DIR, "thresholds.json")
    thr_cfg = {}
    if os.path.exists(thr_path):
        try:
            with open(thr_path) as f:
                thr_cfg = json.load(f)
        except Exception:
            thr_cfg = {}

    ens = (thr_cfg.get("models", {}) or {}).get("Ensemble Voting", {})
    recommended = ens.get("recommended")

    st.markdown("#### Decision Threshold")
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    if recommended is not None:
        st.markdown(
            f"**Model-derived recommendation: `{recommended:.3f}`** — "
            f"sensitivity {ens.get('sensitivity', 0):.1%}, "
            f"specificity {ens.get('specificity', 0):.1%}, "
            f"PPV {ens.get('ppv', 0):.1%}, "
            f"**{ens.get('missed_per_1000', 0):.0f} missed cases per 1,000**.")
        st.caption(
            "Derived at training time as the highest threshold still achieving the "
            "screening sensitivity target. Leave the override off to track it "
            "automatically when models are retrained.")

        use_override = st.checkbox(
            "Override the model-derived threshold",
            value=settings.get("risk_threshold") is not None,
            key="thr_override_chk")

        if use_override:
            ov = st.slider("Manual threshold", 0.05, 0.95,
                           float(settings.get("risk_threshold") or recommended),
                           step=0.01, key="thr_override_val")
            # Live clinical readout for the chosen value, interpolated from the sweep
            sweep = ((_load_results(include_virtual=True).get("Ensemble Voting") or {})
                     .get("threshold_profile", {}) or {}).get("sweep", [])
            if sweep:
                nearest = min(sweep, key=lambda s: abs(s["threshold"] - ov))
                delta = nearest["missed_per_1000"] - (ens.get("missed_per_1000") or 0)
                tone = "alert-warning" if delta > 0 else "alert-info"
                st.markdown(
                    f'<div class="{tone}">At <b>{ov:.2f}</b>: sensitivity '
                    f'<b>{nearest["sensitivity"]:.1%}</b>, specificity '
                    f'<b>{nearest["specificity"]:.1%}</b>, PPV '
                    f'<b>{nearest["ppv"]:.1%}</b> — '
                    f'<b>{nearest["missed_per_1000"]:.0f} missed per 1,000</b>'
                    + (f' ({delta:+.0f} vs the recommendation).' if delta else '.')
                    + '</div>', unsafe_allow_html=True)
            threshold_value = float(ov)
        else:
            threshold_value = None   # None => app follows models/thresholds.json
            st.markdown('<div class="alert-info">Following the model-derived threshold.</div>',
                        unsafe_allow_html=True)
    else:
        st.markdown('<div class="alert-warning">No trained threshold analysis found. '
                    'Retrain the models to derive an evidence-based operating point.</div>',
                    unsafe_allow_html=True)
        threshold_value = st.slider("Manual threshold", 0.05, 0.95,
                                    float(settings.get("risk_threshold") or 0.5), step=0.01)

    if st.button("Save Decision Threshold", use_container_width=True):
        settings["risk_threshold"] = threshold_value
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=4)
        auth_db.log_activity(
            user['id'], user['username'], "System Settings",
            f"Decision threshold set to "
            f"{'model-derived' if threshold_value is None else f'{threshold_value:.2f}'}.")
        st.success("Decision threshold saved.")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Platform Identity")
    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1:
            app_name = st.text_input("Application Name", value=settings['app_name'])
            institution = st.text_input("Institution Name", value=settings['institution'])
            contact = st.text_input("Contact Email", value=settings['contact_email'])
        with c2:
            # Run 4: the threshold moved out of this form into its own governed
            # control above, which shows the clinical consequence of the value.
            allow_reg = st.checkbox("Allow Public Registration", value=settings['allow_registration'])
            session_to = st.number_input("Session Timeout (min)", 10, 480,
                                         value=settings['session_timeout_min'])
            max_preds = st.number_input("Max Predictions Per Day (per user)", 10, 1000,
                                        value=settings['max_predictions_per_day'])

        saved = st.form_submit_button("Save System Settings", use_container_width=True)
        if saved:
            new_settings = {
                "app_name": app_name, "institution": institution,
                # preserved from the dedicated threshold control above
                "risk_threshold": settings.get("risk_threshold"),
                "allow_registration": allow_reg,
                "default_model": settings['default_model'],
                "max_predictions_per_day": max_preds,
                "session_timeout_min": int(session_to),
                "contact_email": contact
            }
            with open(settings_path, "w") as f:
                json.dump(new_settings, f, indent=4)
            auth_db.log_activity(user['id'], user['username'],
                                 "System Settings", "Platform settings updated.")
            st.success("Settings saved successfully!")
            st.rerun()

    st.markdown("---")
    st.markdown("#### Current Configuration")
    cfg_df = pd.DataFrame([
        {"Setting": k.replace("_", " ").title(), "Value": str(v)}
        for k, v in settings.items()
    ])
    st.dataframe(cfg_df, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# SUPERADMIN — BACKUP & RESTORE
# ══════════════════════════════════════════════════════════════════
def page_backup_restore(user):
    _section_header("Backup & Restore", "Export full system backup or restore from a previous archive")

    st.markdown("#### Create System Backup")
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("Backup includes: **Database**, **Trained Models**, **Config files**, **Dataset**")

    if st.button("Generate Backup Archive", use_container_width=True):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            db_p = auth_db.DB_PATH
            if os.path.exists(db_p):
                zf.write(db_p, "backup/heartguard.db")
            for f in os.listdir(MODELS_DIR):
                fp = os.path.join(MODELS_DIR, f)
                if os.path.isfile(fp):
                    zf.write(fp, f"backup/models/{f}")
            for fname in ["system_settings.json"]:
                fp = os.path.join(BASE_DIR, fname)
                if os.path.exists(fp):
                    zf.write(fp, f"backup/{fname}")

        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        auth_db.log_activity(user['id'], user['username'], "Backup",
                             f"System backup created at {ts}.")
        st.download_button(
            label=f"Download Backup - heartguard_backup_{ts}.zip",
            data=buf,
            file_name=f"heartguard_backup_{ts}.zip",
            mime="application/zip",
            use_container_width=True
        )
        st.success("Backup ready for download!")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### File System Overview")
    items = []
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
        for fname in files:
            if fname.endswith(('.py', '.db', '.pkl', '.json', '.csv', '.png')):
                fp = os.path.join(root, fname)
                rel = os.path.relpath(fp, BASE_DIR)
                size = os.path.getsize(fp)
                items.append({"File": rel, "Size":
                    f"{size / 1024:.1f} KB" if size < 1024 * 1024
                    else f"{size / 1024 / 1024:.1f} MB"})
    if items:
        st.dataframe(pd.DataFrame(items), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Restore from Backup")
    st.markdown('<div class="alert-warning">Upload a previously downloaded .zip backup. '
                'This will overwrite current models and config. DB is NOT overwritten.</div>',
                unsafe_allow_html=True)

    restore_file = st.file_uploader("Upload Backup .zip", type="zip")
    if restore_file:
        try:
            zf = zipfile.ZipFile(io.BytesIO(restore_file.read()))
            members = zf.namelist()
            st.success(f"Backup contains {len(members)} files.")
            st.code("\n".join(members[:20]))

            # ──────────────────────────────────────────────────────────
            # FIXED (BUG-10) — pickle deserialization RCE
            #
            # This loop previously wrote ANY file under backup/models/ straight into
            # models/, where load_models() later pickle.load()s it. A crafted
            # __reduce__ payload therefore executed arbitrary code on the next page
            # view. Chained with the old self-service SuperAdmin registration
            # (BUG-09) that was unauthenticated remote code execution.
            #
            # Two controls now apply:
            #   1. Filenames must be on the known-artifact allowlist. Anything else
            #      is refused, not silently written.
            #   2. If the archive carries a manifest.json, every incoming artifact's
            #      SHA-256 must match the digest recorded when it was trained.
            # ──────────────────────────────────────────────────────────
            # FIXED (BUG-27): sourced from the shared registry rather than duplicated
            # here. The local copy went stale as Runs 4-7 added artifacts, so a genuine
            # backup silently restored without thresholds.json or input_ranges.json —
            # reverting the operating-point fix and killing the applicability guard.
            ALLOWED_ARTIFACTS = fe.MODEL_ARTIFACTS

            expected = {}
            if "backup/models/manifest.json" in members:
                try:
                    expected = {
                        k: v.get("sha256")
                        for k, v in json.loads(
                            zf.read("backup/models/manifest.json").decode("utf-8")
                        ).get("artifacts", {}).items()
                    }
                    st.info(f"Manifest found — {len(expected)} artifact digests will be verified.")
                except Exception:
                    st.warning("Manifest present but unreadable; digest verification skipped.")

            accepted, refused, mismatched = [], [], []
            for member in members:
                if member.startswith("backup/models/"):
                    fname = os.path.basename(member)
                    if not fname:
                        continue
                    if fname not in ALLOWED_ARTIFACTS:
                        refused.append(fname)
                        continue
                    payload = zf.read(member)
                    if fname in expected and expected[fname]:
                        digest = hashlib.sha256(payload).hexdigest()
                        if digest != expected[fname]:
                            mismatched.append(fname)
                            continue
                    accepted.append((fname, payload))
                elif member == "backup/system_settings.json":
                    accepted.append(("system_settings.json", zf.read(member)))

            if refused:
                st.warning(f"Refused {len(refused)} file(s) not on the artifact "
                           f"allowlist: {', '.join(sorted(refused)[:8])}")
            if mismatched:
                st.error(f"Refused {len(mismatched)} file(s) whose SHA-256 did not "
                         f"match the manifest: {', '.join(sorted(mismatched))}. "
                         f"The archive may be corrupt or tampered with.")

            if not accepted:
                st.error("Nothing in this archive passed validation — restore aborted.")
            elif st.button(f"Restore {len(accepted)} verified file(s) (No DB overwrite)",
                           use_container_width=True):
                for fname, payload in accepted:
                    dest = (os.path.join(BASE_DIR, "system_settings.json")
                            if fname == "system_settings.json"
                            else os.path.join(MODELS_DIR, fname))
                    with open(dest, "wb") as dst:
                        dst.write(payload)
                auth_db.log_activity(
                    user['id'], user['username'], "Restore",
                    f"Restored {len(accepted)} artifact(s); "
                    f"refused {len(refused)} unlisted, {len(mismatched)} digest-mismatched.")
                st.success("Restore complete! Please restart the app to reload models.")
        except Exception as e:
            st.error(f"Restore failed: {e}")


# ══════════════════════════════════════════════════════════════════
# ALL ROLES — MODEL PERFORMANCE & EVALUATION
# ══════════════════════════════════════════════════════════════════
def page_model_performance(user):
    _section_header("Model Performance", "Detailed evaluation metrics, confusion matrices and comparisons for all trained AI models")

    results = _load_results()
    if not results:
        st.markdown(
            '<div class="alert-warning">No model results found. '
            'Please ask SuperAdmin to train the models first.</div>',
            unsafe_allow_html=True)
        return

    model_names  = list(results.keys())
    # FIXED (BUG-19): keyed by model name rather than position.
    _sn = {"Logistic Regression": "LR", "Support Vector Machine (SVM)": "SVM",
           "Decision Tree": "DT", "Random Forest": "RF", "XGBoost": "XGB"}
    _palette     = ['#ef4444', '#3b82f6', '#f59e0b', '#10b981', '#a855f7']
    short_names  = [_sn.get(m, m[:3].upper()) for m in model_names]
    colors_bar   = [_palette[i % len(_palette)] for i, m in enumerate(model_names)]

    accs  = [results[m]['accuracy']  for m in model_names]
    aucs  = [results[m]['auc']       for m in model_names]
    f1s   = [results[m]['f1']        for m in model_names]
    precs = [results[m]['precision'] for m in model_names]
    recs  = [results[m]['recall']    for m in model_names]

    best_idx = aucs.index(max(aucs))
    best_name = model_names[best_idx]

    # ── Best model highlight banner ──────────────────────────────
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1e0d2e,#2d1f40);
                border:2px solid #a855f7;border-radius:14px;
                padding:18px 24px;margin-bottom:20px;
                display:flex;align-items:center;gap:16px;">
      <div style="font-size:2.4em;">🏆</div>
      <div>
        <div style="color:#e9d5ff;font-size:1.05em;font-weight:700;">Best Performing Model</div>
        <div style="color:#a855f7;font-size:1.5em;font-weight:800;">{best_name}</div>
        <div style="color:#c4b5fd;font-size:.85em;">
          AUC: <b>{aucs[best_idx]:.4f}</b> &nbsp;|&nbsp;
          Accuracy: <b>{accs[best_idx]:.4f}</b> &nbsp;|&nbsp;
          F1: <b>{f1s[best_idx]:.4f}</b>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Metric KPI cards ─────────────────────────────────────────
    st.markdown('<div class="kpi-wrap">' +
        _kpi(f"{max(accs):.2%}", "Best Accuracy",  "#60a5fa", "linear-gradient(135deg,#1e3a5f,#0f2544)", "#1e40af") +
        _kpi(f"{max(aucs):.4f}", "Best AUC",       "#a855f7", "linear-gradient(135deg,#2d1f40,#180d2e)", "#a855f7") +
        _kpi(f"{max(f1s):.4f}",  "Best F1 Score",  "#10b981", "linear-gradient(135deg,#0d2e1e,#071a10)", "#10b981") +
        _kpi(f"{max(precs):.4f}","Best Precision",  "#f59e0b", "linear-gradient(135deg,#2d1f02,#1a1002)", "#f59e0b") +
        _kpi(f"{max(recs):.4f}", "Best Recall",    "#ef4444", "linear-gradient(135deg,#3b1f1f,#1e0d0d)", "#ef4444") +
        '</div>', unsafe_allow_html=True)

    st.markdown("---")

    # ── TABS ─────────────────────────────────────────────────────
    t1, t2, t3, t4 = st.tabs([
        "📊 Metric Comparison",
        "🔲 Confusion Matrices",
        "📋 Detailed Report",
        "ℹ️ Model Info"
    ])

    # ────────────────────────────────────────────────────────────
    # TAB 1 — Metric Comparison
    # ────────────────────────────────────────────────────────────
    with t1:
        # Comparison table
        import pandas as pd
        df_metrics = pd.DataFrame({
            "Model":     model_names,
            "Accuracy":  [f"{v:.4f} ({v:.1%})" for v in accs],
            "AUC":       [f"{v:.4f}" for v in aucs],
            "F1 Score":  [f"{v:.4f}" for v in f1s],
            "Precision": [f"{v:.4f}" for v in precs],
            "Recall":    [f"{v:.4f}" for v in recs],
            "Best?":     ["🏆" if m == best_name else "" for m in model_names],
        })
        st.markdown("#### All Models — Metric Table")
        st.dataframe(df_metrics, hide_index=True, use_container_width=True)

        st.markdown("---")
        st.markdown("#### Visual Comparison")
        col_l, col_r = st.columns(2)

        # Left: grouped bar chart
        with col_l:
            st.markdown("**Accuracy vs AUC vs F1 (per model)**")
            fig, ax = plt.subplots(figsize=(6, 4), facecolor='#0d1117')
            ax.set_facecolor('#161b22')
            x = range(len(model_names))
            w = 0.25
            b1 = ax.bar([i - w for i in x], accs,  width=w, label='Accuracy',  color='#3b82f6', alpha=0.9)
            b2 = ax.bar(list(x),             aucs,  width=w, label='AUC',       color='#a855f7', alpha=0.9)
            b3 = ax.bar([i + w for i in x], f1s,   width=w, label='F1 Score',  color='#10b981', alpha=0.9)
            ax.set_xticks(list(x))
            ax.set_xticklabels(short_names, color='#c9d1d9', fontsize=9)
            ax.set_ylim(0, 1.12)
            ax.tick_params(colors='#c9d1d9', labelsize=8)
            ax.legend(facecolor='#21262d', labelcolor='#c9d1d9', fontsize=8)
            for sp in ['top', 'right']:
                ax.spines[sp].set_visible(False)
            for sp in ['left', 'bottom']:
                ax.spines[sp].set_color('#30363d')
            for bars in [b1, b2, b3]:
                for bar in bars:
                    ax.annotate(f"{bar.get_height():.2f}",
                                xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                                xytext=(0, 2), textcoords="offset points",
                                ha='center', color='#c9d1d9', fontsize=6.5, fontweight='600')
            plt.tight_layout()
            st.pyplot(fig, transparent=True)
            plt.close()

        # Right: horizontal bar for AUC ranked
        with col_r:
            st.markdown("**AUC Ranking (higher = better)**")
            sorted_idx = sorted(range(len(aucs)), key=lambda i: aucs[i], reverse=True)
            fig2, ax2 = plt.subplots(figsize=(6, 4), facecolor='#0d1117')
            ax2.set_facecolor('#161b22')
            ranked_names = [model_names[i] for i in sorted_idx]
            ranked_aucs  = [aucs[i] for i in sorted_idx]
            ranked_colors = [colors_bar[i] for i in sorted_idx]
            bar_h = ax2.barh(ranked_names, ranked_aucs, color=ranked_colors, height=0.5)
            ax2.set_xlim(0, 1.05)
            ax2.tick_params(colors='#c9d1d9', labelsize=8)
            for sp in ['top', 'right']:
                ax2.spines[sp].set_visible(False)
            for sp in ['left', 'bottom']:
                ax2.spines[sp].set_color('#30363d')
            for bar in bar_h:
                ax2.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                         f"{bar.get_width():.4f}", va='center', color='#c9d1d9', fontsize=8, fontweight='600')
            plt.tight_layout()
            st.pyplot(fig2, transparent=True)
            plt.close()

        st.markdown("---")
        # Precision vs Recall scatter
        st.markdown("**Precision vs Recall Trade-off**")
        fig3, ax3 = plt.subplots(figsize=(7, 4), facecolor='#0d1117')
        ax3.set_facecolor('#161b22')
        for i, m in enumerate(model_names):
            ax3.scatter(recs[i], precs[i], color=colors_bar[i], s=120, zorder=5,
                        label=short_names[i], edgecolors='white', linewidths=0.5)
            ax3.annotate(short_names[i], (recs[i]+0.003, precs[i]+0.003),
                         color=colors_bar[i], fontsize=9, fontweight='700')
        ax3.set_xlabel("Recall (Sensitivity)", color='#c9d1d9', fontsize=9)
        ax3.set_ylabel("Precision", color='#c9d1d9', fontsize=9)
        ax3.tick_params(colors='#c9d1d9', labelsize=8)
        ax3.legend(facecolor='#21262d', labelcolor='#c9d1d9', fontsize=8)
        for sp in ['top', 'right']:
            ax3.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax3.spines[sp].set_color('#30363d')
        ax3.set_xlim(0.3, 1.05)
        ax3.set_ylim(0.3, 1.05)
        plt.tight_layout()
        st.pyplot(fig3, transparent=True)
        plt.close()

    # ────────────────────────────────────────────────────────────
    # TAB 2 — Confusion Matrices
    # ────────────────────────────────────────────────────────────
    with t2:
        st.markdown("#### Confusion Matrices — All Models")
        st.markdown(
            '<div class="alert-info">Rows = Actual Class, Columns = Predicted Class. '
            '0 = No Disease (Low Risk), 1 = Disease (High Risk)</div>',
            unsafe_allow_html=True)

        cols_cm = st.columns(len(model_names))
        for idx, (mn, col) in enumerate(zip(model_names, cols_cm)):
            cm = results[mn]['conf_matrix']
            tn, fp = cm[0][0], cm[0][1]
            fn, tp = cm[1][0], cm[1][1]
            total  = tn + fp + fn + tp
            sens   = tp / (tp + fn) if (tp + fn) else 0
            spec   = tn / (tn + fp) if (tn + fp) else 0

            with col:
                st.markdown(f"**{short_names[idx]}**")
                fig_cm, ax_cm = plt.subplots(figsize=(2.6, 2.2), facecolor='#0d1117')
                ax_cm.set_facecolor('#0d1117')
                cm_arr = [[tn, fp], [fn, tp]]
                cmap_custom = plt.cm.get_cmap('RdYlGn')
                im = ax_cm.imshow(cm_arr, cmap=cmap_custom, aspect='auto', vmin=0)
                for r in range(2):
                    for c_ in range(2):
                        ax_cm.text(c_, r, str(cm_arr[r][c_]),
                                   ha='center', va='center',
                                   color='black', fontsize=10, fontweight='700')
                ax_cm.set_xticks([0, 1])
                ax_cm.set_yticks([0, 1])
                ax_cm.set_xticklabels(['Pred 0', 'Pred 1'], color='#c9d1d9', fontsize=7)
                ax_cm.set_yticklabels(['Act 0', 'Act 1'],  color='#c9d1d9', fontsize=7)
                ax_cm.tick_params(length=0)
                plt.tight_layout(pad=0.3)
                st.pyplot(fig_cm, transparent=True)
                plt.close()

                st.markdown(f"""
                <div style="font-size:.72em;color:#6b7280;line-height:1.6;">
                TP={tp} &nbsp; TN={tn}<br>
                FP={fp} &nbsp; FN={fn}<br>
                Sensitivity: <b style="color:#10b981">{sens:.1%}</b><br>
                Specificity: <b style="color:#3b82f6">{spec:.1%}</b>
                </div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Sensitivity vs Specificity Comparison")
        fig_ss, ax_ss = plt.subplots(figsize=(8, 3.5), facecolor='#0d1117')
        ax_ss.set_facecolor('#161b22')
        w = 0.35
        xr = range(len(model_names))
        sens_list = []
        spec_list = []
        for mn in model_names:
            cm = results[mn]['conf_matrix']
            tn, fp, fn, tp = cm[0][0], cm[0][1], cm[1][0], cm[1][1]
            sens_list.append(tp / (tp + fn) if (tp + fn) else 0)
            spec_list.append(tn / (tn + fp) if (tn + fp) else 0)
        bs = ax_ss.bar([i - w/2 for i in xr], sens_list, width=w, label='Sensitivity', color='#ef4444', alpha=0.85)
        bp = ax_ss.bar([i + w/2 for i in xr], spec_list, width=w, label='Specificity', color='#3b82f6', alpha=0.85)
        ax_ss.set_xticks(list(xr))
        ax_ss.set_xticklabels(short_names, color='#c9d1d9', fontsize=9)
        ax_ss.set_ylim(0, 1.15)
        ax_ss.tick_params(colors='#c9d1d9', labelsize=8)
        ax_ss.legend(facecolor='#21262d', labelcolor='#c9d1d9', fontsize=9)
        for sp in ['top', 'right']:
            ax_ss.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax_ss.spines[sp].set_color('#30363d')
        for bar in list(bs) + list(bp):
            ax_ss.annotate(f"{bar.get_height():.2f}",
                           xy=(bar.get_x() + bar.get_width()/2, bar.get_height()),
                           xytext=(0, 3), textcoords="offset points",
                           ha='center', color='#c9d1d9', fontsize=7.5, fontweight='600')
        plt.tight_layout()
        st.pyplot(fig_ss, transparent=True)
        plt.close()

    # ────────────────────────────────────────────────────────────
    # TAB 3 — Detailed Classification Report
    # ────────────────────────────────────────────────────────────
    with t3:
        st.markdown("#### Per-Class Classification Report")
        sel_m = st.selectbox("Select Model", model_names)
        rep   = results[sel_m].get('report', {})

        rows = []
        for cls_key, cls_label in [("0", "Low Risk (Class 0)"), ("1", "High Risk (Class 1)"),
                                    ("macro avg", "Macro Average"), ("weighted avg", "Weighted Average")]:
            if cls_key in rep:
                d = rep[cls_key]
                rows.append({
                    "Class":     cls_label,
                    "Precision": f"{d.get('precision', 0):.4f}",
                    "Recall":    f"{d.get('recall', 0):.4f}",
                    "F1-Score":  f"{d.get('f1-score', 0):.4f}",
                    "Support":   str(int(d.get('support', 0))),
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        st.markdown("---")
        st.markdown("#### Full Metrics Summary — All Models")
        all_rows = []
        for mn in model_names:
            r = results[mn]
            cm = r['conf_matrix']
            tn, fp, fn, tp = cm[0][0], cm[0][1], cm[1][0], cm[1][1]
            total = tn + fp + fn + tp
            all_rows.append({
                "Model":      mn,
                "Accuracy":   f"{r['accuracy']:.4f}",
                "AUC-ROC":    f"{r['auc']:.4f}",
                "F1 Score":   f"{r['f1']:.4f}",
                "Precision":  f"{r['precision']:.4f}",
                "Recall":     f"{r['recall']:.4f}",
                "TP":         tp, "TN": tn, "FP": fp, "FN": fn,
                "Total Test": total,
            })
        st.dataframe(pd.DataFrame(all_rows), hide_index=True, use_container_width=True)

        csv_rows = pd.DataFrame(all_rows).to_csv(index=False).encode()
        st.download_button("Export Metrics as CSV", csv_rows,
                           "model_metrics.csv", "text/csv", use_container_width=True)

    # ────────────────────────────────────────────────────────────
    # TAB 4 — Model Info
    # ────────────────────────────────────────────────────────────
    with t4:
        st.markdown("#### AI Models Used in HeartGuard")
        model_info = [
            ("Logistic Regression", "LR",
             "A linear probabilistic classifier. Fast, interpretable, suitable as a baseline.",
             "High recall, moderate precision"),
            ("Support Vector Machine (SVM)", "SVM",
             "Finds the optimal hyperplane separating classes. Uses LinearSVC with calibration for probabilities.",
             "Highest recall — catches most at-risk patients"),
            ("Decision Tree", "DT",
             "Tree-based rule classifier. Highly interpretable — can show the exact rules it follows.",
             "Balanced precision/recall"),
            ("Random Forest", "RF",
             "Ensemble of 200 decision trees with bagging. Robust against overfitting.",
             "Best overall balance of metrics"),
            ("XGBoost", "XGB",
             "Gradient-boosted tree ensemble — gold standard for tabular data competitions.",
             "High accuracy, strong generalization"),
        ]
        for i, (name, short, desc, strength) in enumerate(model_info):
            badge_color = colors_bar[i]
            r = results.get(name, {})
            acc = r.get('accuracy', 0)
            auc = r.get('auc', 0)
            is_best = "🏆 " if name == best_name else ""
            st.markdown(f"""
            <div class="panel" style="border-left:4px solid {badge_color};margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <span style="font-size:1.05em;font-weight:700;color:#1f2937;">{is_best}{name}</span>
                  <span style="background:{badge_color};color:white;font-size:.7em;
                               font-weight:700;padding:2px 9px;border-radius:20px;
                               margin-left:8px;">{short}</span>
                </div>
                <div style="text-align:right;font-size:.85em;color:#6b7280;">
                   Acc: <b>{acc:.2%}</b> &nbsp; AUC: <b>{auc:.4f}</b>
                </div>
              </div>
              <div style="color:#6b7280;font-size:.85em;margin-top:6px;">{desc}</div>
              <div style="color:#10b981;font-size:.8em;margin-top:4px;font-weight:600;">
                Strength: {strength}
              </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("""
        <div class="panel">
        <h4 style="color:#3b82f6;">Dataset & Preprocessing Summary</h4>

        | Step | Detail |
        |------|--------|
        | Dataset | Cardiovascular Disease dataset (heart.csv) |
        | Original Rows | ~70,000 patient records |
        | Target Column | `cardio` (0 = no disease, 1 = disease) |
        | Train/Test Split | 80% / 20% (stratified) |
        | Preprocessing | Age conversion, duplicate removal, IQR Winsorization, median imputation |
        | Feature Engineering | BMI, Pulse Pressure, Age Group, High Risk Flag |
        | Normalization | StandardScaler (zero mean, unit variance) |
        | Class Imbalance | Handled via `class_weight='balanced'` |

        </div>
        """, unsafe_allow_html=True)
