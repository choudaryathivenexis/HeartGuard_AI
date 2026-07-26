# HeartGuard AI — Master Project Reference

> **Document type:** Authoritative description of *what this system is and how it works*.
> For engineering state, defects, measurements and the remediation roadmap, see [CONTEXT.md](CONTEXT.md).
>
> **Last verified:** 2026-07-26 (post Run-3 fixes) — every figure, path and line reference below was read from source or measured against the live artifacts, not inferred.
>
> **Run 3 changed this system substantially.** All 21 known bugs are fixed, the models are retrained, and a new shared module (`feature_engineering.py`) owns the encoding contract. See [TASK.md](TASK.md) for the full change log.

---

## 1. Identity

| | |
|---|---|
| **Name** | HeartGuard AI — Cardiovascular Risk Intelligence Portal |
| **Type** | Final Year Project (FYP 2026) — clinical decision-support web application |
| **Purpose** | Predict binary cardiovascular disease risk from 11 routine clinical indicators, with role-based access, audit logging, model management and explainability |
| **Interface** | Streamlit multi-page single-process web app |
| **Version string** | `HeartGuard AI v2.0 · FYP 2026` ([app.py:388](app.py#L388)) |
| **Working directory** | `i:\Ariha\FYP\HeartGuard FYP\HeartGuard FYP` |
| **Version control** | **None** — not a git repository |

### Product claim vs. implementation

The UI presents "5 AI models trained on 70,000 patient records."

**Before Run 3 this claim did not hold** — the pipeline trained on 5,266 rows (7.5% of the data) drawn from a biased sub-cohort. After the Run-3 fixes it does: **68,645 of 70,000 rows (98.1%) are retained**, 54,916 used for training, and the reported metrics are measured on a genuine 13,729-row holdout. Best model AUC is **0.8000**.

---

## 2. Technology stack (verified installed versions)

| Component | Declared in `requirements.txt` | Actually installed in `.venv` |
|---|---|---|
| Python | 3.11–3.13 (comment) | **3.14.6** — outside declared range |
| streamlit | `>=1.30` | 1.59.2 |
| pandas | `>=2.0` | **3.0.3** — major version ahead |
| numpy | `>=1.24` | 2.4.6 |
| scikit-learn | `>=1.9.0` | 1.9.0 |
| xgboost | `>=2.0` | 3.3.0 |
| shap | `>=0.44` | 0.52.0 |
| matplotlib | `>=3.7` | installed |
| sqlite3 | stdlib | stdlib |

No upper bounds are pinned anywhere. Model artifacts are raw `pickle`, so a scikit-learn minor bump can silently invalidate them — `requirements.txt` documents this risk in its header comment.

> **pandas 3.0.3 caught a real bug.** The pipeline used `df[col].fillna(v, inplace=True)`, which
> pandas 3 treats as chained assignment on a copy — a silent no-op (BUG-13). Fixed in Run 3 to
> explicit assignment, and the `warnings.filterwarnings("ignore")` that had been hiding it was removed.

---

## 3. File structure

```
HeartGuard FYP/
├── app.py                    2,726 L  Main Streamlit app: CSS, auth UI, router, 9 pages
├── pages_ext.py              1,169 L  14 extended role-scoped pages (imported as `px`)
├── auth_db.py                         SQLite layer: schema, PBKDF2 auth, CRUD, audit logging
├── train_models.py                    Leak-free preprocessing + 5-model training pipeline
├── feature_engineering.py             SHARED encoding + derived-feature contract (Run 3)
│
├── heart.csv                  3.1 MB  70,000-row Kaggle Cardiovascular Disease dataset
├── heartguard.db               64 KB  SQLite: 8 users, 5 predictions, 50 logs, 4 runs
├── requirements.txt                   Dependency manifest
├── heart_bg_b64.txt            68 KB  UNUSED — see §11
│
├── models/                            Training output — all artifacts regenerated together
│   ├── scaler.pkl                     StandardScaler, n_samples_seen_ = 54,916
│   ├── logistic_regression.pkl  836 B
│   ├── svm.pkl                2.0 KB  CalibratedClassifierCV(LinearSVC)
│   ├── decision_tree.pkl       13 KB
│   ├── random_forest.pkl      11.0 MB
│   ├── xgboost.pkl              958 KB
│   ├── features.json                  Ordered list of the 15 feature columns
│   ├── config.json                    Per-model enable/disable flags
│   ├── results.json                   Metrics + ROC/PR + K-fold + Brier/ECE/reliability
│   ├── imputer_medians.json           Train-split medians (Run 3)
│   ├── manifest.json                  Provenance + SHA-256 per artifact (Run 3)
│   └── preprocess_report.txt          Captured training log
│
├── check.py                      7 L  DEAD — one-shot indentation inspector
├── fix_indent.py                30 L  DEAD — one-shot repair script
├── fix_all_indent.py           107 L  DEAD — one-shot repair script
├── fix_unicode.py               49 L  DEAD — one-shot ASCII transliterator
│
├── .venv/                             Virtual environment
└── __pycache__/                       Stale bytecode (mixed cpython-313 / cpython-314)
```

**Total application code: 4,746 LOC** (excluding the four dead `fix_*`/`check` scripts, 193 LOC).

---

## 4. Dataset

### 4.1 Source and shape

Kaggle **Cardiovascular Disease dataset** — 70,000 rows × 14 columns, essentially balanced (`cardio` mean = 0.4997).

### 4.2 Schema and encoding

| Column | Type | Encoding in `heart.csv` | Notes |
|---|---|---|---|
| *(unnamed)* | int | row index | Dropped as `Unnamed: 0` |
| `id` | int | patient id | Dropped |
| `age` | int | **days** (e.g. 18393) | Converted to years by the pipeline |
| `gender` | int | **0 / 1** | 0 = 45,530 · 1 = 24,470 → 0 = female, 1 = male |
| `height` | int | cm | |
| `weight` | float | kg | |
| `ap_hi` | int | systolic mmHg | Contains extreme outliers (raw range includes negatives / >10000) |
| `ap_lo` | int | diastolic mmHg | Same |
| `cholesterol` | int | **0 / 1 / 2** | 0 = 52,385 · 1 = 9,549 · 2 = 8,066 |
| `gluc` | int | **0 / 1 / 2** | 0 = 59,479 · 1 = 5,190 · 2 = 5,331 |
| `smoke` | int | 0 / 1 | 6,169 smokers |
| `alco` | int | 0 / 1 | 3,764 drinkers |
| `active` | int | 0 / 1 | 56,261 active |
| `cardio` | int | 0 / 1 | **Target.** 35,021 / 34,979 |

> ### ⚠ THE SINGLE MOST IMPORTANT FACT IN THIS PROJECT
>
> **`cholesterol` and `gluc` are 0-indexed (0/1/2) in this CSV.**
>
> The canonical Kaggle release ships them as **1/2/3**. This copy has been re-encoded to 0-based — as has `gender` (0/1 rather than 1/2). Assuming the upstream convention caused the two worst bugs in the project's history (BUG-03 and BUG-04).
>
> **Since Run 3 this contract lives in exactly one place:** [feature_engineering.py](feature_engineering.py) —
> `CHOLESTEROL_LEVELS`, `GLUCOSE_LEVELS`, `ORDINAL_VALID_VALUES`, `ELEVATED_THRESHOLD`.
> The training filter, the diagnosis form and the SHAP background builder all import from it,
> so they can no longer drift apart.
>
> **Any literal `[1,2,3]` or `>= 2` applied to cholesterol/gluc anywhere in this codebase is a bug,
> not a convention.** A `MIN_RETENTION_RATIO` assertion in `_domain_filter` now fails loudly if a
> future edit reintroduces the mismatch.

### 4.3 Measured row attrition through the pipeline

**Current pipeline (post Run-3):**

| Stage | Rows remaining |
|---|---:|
| Raw CSV | 70,000 |
| `drop_duplicates()` — runs **before** age conversion | 69,976 |
| Age days→years, physiological domain filters, ordinals ∈ {0,1,2} | **68,645** |

Final training corpus: **68,645 rows** (98.1% retained) → **54,916 train / 13,729 test**.
Class prevalence **49.47%** — population-representative.

A `MIN_RETENTION_RATIO = 0.80` guardrail in `_domain_filter` now **raises** if the filter ever
discards more than 20% of rows, which is what silently happened before Run 3:

| Old (broken) stage | Rows remaining |
|---|---:|
| After old age-then-dedup order | 66,179 *(3,821 real patients wrongly deleted)* |
| `cholesterol.isin([1,2,3])` ← wrong encoding | 17,088 |
| `gluc.isin([1,2,3])` ← wrong encoding | **6,583** *(prevalence skewed to 65.7%)* |

---

## 5. ML pipeline — `train_models.py`

Entry point: `train_all(data_path=None)`. Resolves `custom_dataset.csv` if present, else `heart.csv` ([train_models.py:336-338](train_models.py#L336-L338)).

### 5.1 The twelve steps

> **Rewritten in Run 3.** Every fitted preprocessing step now happens *after* the train/test
> split, IQR winsorization is gone, and deduplication precedes the age conversion.

| # | Step | Function | Notes |
|---|---|---|---|
| 1 | Load CSV (`sep=None`, python engine — sniffs delimiter) | `_load` | |
| 2 | **Deduplicate** — before age rounding | `_remove_duplicates` | was step 3, after rounding (BUG-06) |
| 3 | Drop id cols; age days→years | `_basic_clean` | |
| 4 | Physiological domain filter + retention guardrail | `_domain_filter` | ordinals ∈ {0,1,2} (BUG-03) |
| 5 | Feature engineering | `fe.engineer_features` | shared module (BUG-05) |
| 6 | **Train/test split (80/20 stratified)** | — | everything fitted comes after this |
| 7 | Median imputation — medians from **train only** | `_fit_median_imputer` | (BUG-13, BUG-14) |
| 8 | Correlation pruning — from **train only** | `_drop_high_correlation` | (BUG-14) |
| 9 | StandardScaler — fit on **train only** | — | |
| 10 | Train 5 classifiers, adaptive class weighting | — | (BUG-08) |
| 11 | Evaluate + measure Brier / ECE / reliability | `_evaluate` | new in Run 3 |
| 12 | 5-fold CV over a Pipeline, **training split only** | `_kfold_cv` | (BUG-15) |

*Removed:* IQR winsorization — the domain filter already bounds every field, and clipping on top
destroyed the strongest clinical signal (BUG-07).

<details><summary>Historical: the original 12 steps (pre-Run-3)</summary>

| # | Step | Function | Line |
|---|---|---|---|
| 1 | Load CSV (`sep=None`, python engine — sniffs delimiter) | `_load` | [152](train_models.py#L152) |
| 2 | Drop `Unnamed: 0` / `id`; convert `age` days→years when `max > 1000` | `_basic_clean` | [161](train_models.py#L161) |
| 3 | `drop_duplicates()` + reindex | `_remove_duplicates` | [177](train_models.py#L177) |
| 4 | Physiological domain filters (see §5.2) | `_domain_filter` | [189](train_models.py#L189) |
| 5 | IQR Winsorization, factor 1.5, on columns with `nunique() > 10` | `_winsorize_iqr` | [229](train_models.py#L229) |
| 6 | Median imputation of remaining NaNs | `_impute_median` | [253](train_models.py#L253) |
| 7 | Feature engineering (see §5.3) | `_feature_engineering` | [269](train_models.py#L269) |
| 8 | Drop features with pairwise \|r\| ≥ 0.90 | `_drop_high_correlation` | [308](train_models.py#L308) |
| 9 | `train_test_split(test_size=0.2, random_state=42, stratify=y)` | — | [395](train_models.py#L395) |
| 10 | `StandardScaler` fit on train, transform both; persist `scaler.pkl` + `features.json` | — | [402](train_models.py#L402) |
| 11 | Train and persist 5 classifiers, evaluate each on the holdout | — | [413](train_models.py#L413) |
| 12 | 5-fold `StratifiedKFold` cross-validation | `_kfold_cv` | [102](train_models.py#L102) |

> **Steps 5, 6 and 8 executed *before* the step-9 split** — every one of them was fitted on data that later became the test set. Textbook preprocessing leakage; fixed in Run 3.

</details>

### 5.2 Domain filter rules ([train_models.py:189-223](train_models.py#L189-L223))

```
age         ∈ [1, 120]
ap_hi       ∈ [60, 250]
ap_lo       ∈ [40, 200]
ap_hi       >  ap_lo
height      ∈ [100, 250]
weight      ∈ [20, 300]
cholesterol ∈ {1, 2, 3}     ← WRONG for this dataset (see §4.2)
gluc        ∈ {1, 2, 3}     ← WRONG for this dataset (see §4.2)
```

The function reports how many rows it removed but never asserts a floor on retention.

### 5.3 Engineered features ([train_models.py:269-302](train_models.py#L269-L302))

| Feature | Formula | Notes |
|---|---|---|
| `bmi` | `weight / (height/100)²`, rounded 2dp, clipped to [10, 70] | |
| `pulse_pressure` | `ap_hi − ap_lo` | |
| `age_group` | `pd.cut(age, bins=[0,30,45,60,75,120], labels=[0..4])` | Ordinal 0–4 |
| `high_risk_flag` | `(cholesterol >= 2) & (ap_hi >= 140)` | **Threshold assumes 1/2/3 encoding** |

Correlation pruning at 0.90 drops nothing on this data, so all 15 columns survive.

### 5.4 Final feature vector — canonical order

**This order is the system's central contract.** It is written to `models/features.json` at train time and must be reproduced exactly at inference:

```json
["age","gender","height","weight","ap_hi","ap_lo","cholesterol","gluc",
 "smoke","alco","active","bmi","pulse_pressure","age_group","high_risk_flag"]
```

15 features. Any reordering silently corrupts every prediction — `StandardScaler` and all five models index positionally.

### 5.5 Models and hyperparameters ([train_models.py:416-490](train_models.py#L416-L490))

| Key in `results.json` | Estimator | Hyperparameters |
|---|---|---|
| `Logistic Regression` | `LogisticRegression` | `max_iter=2000, C=1.0, class_weight='balanced', random_state=42` |
| `Support Vector Machine (SVM)` | `CalibratedClassifierCV(LinearSVC, cv=3)` | `max_iter=3000, C=1.0, class_weight='balanced'` |
| `Decision Tree` | `DecisionTreeClassifier` | `max_depth=7, min_samples_split=20, class_weight='balanced'` |
| `Random Forest` | `RandomForestClassifier` | `n_estimators=200, max_depth=12, min_samples_split=10, class_weight='balanced', n_jobs=-1` |
| `XGBoost` | `XGBClassifier` | `n_estimators=300, max_depth=6, lr=0.05, subsample=0.8, colsample_bytree=0.8, scale_pos_weight=neg/pos` |

XGBoost falls back to `GradientBoostingClassifier(n_estimators=300, max_depth=5, lr=0.05)` when the import fails; the fallback is recorded as `results["XGBoost"]["is_fallback"]`.

Four of five use `class_weight='balanced'`, which deliberately distorts predicted probabilities away from the training base rate. No calibration step corrects for this afterwards.

### 5.6 Metrics captured per model (`results.json`)

`accuracy · auc · f1 · precision · recall · training_time_s · pred_time_ms · conf_matrix · report` (full sklearn dict) `· roc_curve` (≤100 points) `· pr_curve` (≤100 points + `avg_precision`) `· kfold_cv` (per-fold, mean, std for 5 metrics).

### 5.7 Current results (holdout, n = 13,729, population-representative)

| Model | Accuracy | AUC | F1 | Precision | Recall | Brier | ECE | CV AUC (±σ) |
|---|---|---|---|---|---|---|---|---|
| Logistic Regression | 0.7261 | 0.7920 | 0.7091 | 0.7470 | 0.6748 | 0.1864 | 0.0267 | 0.7908 ± 0.0044 |
| SVM | 0.7261 | 0.7918 | 0.7096 | 0.7461 | 0.6765 | 0.1865 | 0.0260 | 0.7905 ± 0.0044 |
| Decision Tree | 0.7253 | 0.7933 | 0.7080 | 0.7465 | 0.6733 | 0.1840 | 0.0144 | 0.7916 ± 0.0043 |
| Random Forest | 0.7303 | **0.8000** | 0.7139 | 0.7512 | 0.6801 | 0.1814 | 0.0110 | 0.7998 ± 0.0036 |
| XGBoost | **0.7330** | **0.8000** | 0.7194 | 0.7492 | 0.6918 | **0.1811** | **0.0103** | 0.7994 ± 0.0037 |

CV and holdout AUC now agree to within 0.0002 — the K-fold figures are genuine
generalisation evidence, cross-validated over the training split only.

**Calibration.** Mean predicted probability 0.4949 vs true prevalence 0.4947. The models neither
over- nor under-state population risk.

<details><summary>Historical: pre-Run-3 results (holdout n = 1,317, biased cohort)</summary>

| Model | Accuracy | AUC |
|---|---|---|
| Logistic Regression | 0.6765 | 0.7245 |
| SVM | 0.7160 | 0.7246 |
| Decision Tree | 0.6834 | 0.6995 |
| Random Forest | 0.7069 | 0.7159 |
| XGBoost | 0.6887 | 0.7152 |

These described a metabolic-syndrome sub-cohort, not the population the app scores.

</details>

---

## 6. Application architecture

### 6.1 Process model

Single Streamlit process. `app.py` executes top to bottom on every interaction:

```
import → st.set_page_config → inject global CSS → define helpers & pages
  → session-state init → if user is None: page_login() else: router
```

`auth_db.init_db()` runs **at import time** ([auth_db.py:317](auth_db.py#L317)) — importing the module creates the schema and seeds default accounts if the `users` table is empty.

State lives entirely in `st.session_state.user` (a dict of the user row) and `st.session_state.page`. There is no server-side session store, no token, and no expiry.

### 6.2 Caching

| Decorator | Target | Line |
|---|---|---|
| `@st.cache_resource` | `load_models()` — scaler + all five estimators | [app.py:196](app.py#L196) |
| `@st.cache_data` | `compute_shap_values()` | [app.py:2314](app.py#L2314) |

`st.cache_resource.clear()` is called after a successful training run ([app.py:1011](app.py#L1011)) so freshly written `.pkl` files are picked up without restart.

### 6.3 Roles and navigation

Three roles. The nav list is built server-side from `user['role']` ([app.py:2649-2684](app.py#L2649-L2684)) and each page is reachable only through that list.

| Page | Doctor | Admin | SuperAdmin | Handler |
|---|:---:|:---:|:---:|---|
| Dashboard | ✅ | ✅ | ✅ | `px.page_dashboard` |
| Heart Disease Prediction | ✅ | — | — | `page_diagnosis` |
| Patient Management | ✅ | ✅ | — | `px.page_patient_management` |
| Prediction History | ✅ | — | — | `page_history` |
| Model Performance | ✅ | ✅ | ✅ | `page_model_performance` *(app.py)* |
| Reports | ✅ | ✅ | — | `px.page_reports` |
| Profile | ✅ | ✅ | ✅ | `page_profile` |
| Doctor Management | — | ✅ | ✅ | `px.page_doctor_management` |
| Prediction Management | — | ✅ | — | `px.page_prediction_management` |
| Dataset Management | — | ✅ | — | `px.page_dataset_management` |
| Analytics | — | ✅ | ✅ | `page_admin_analytics` |
| Admin Management | — | — | ✅ | `px.page_admin_management` |
| Role & Permission Management | — | — | ✅ | `px.page_role_permissions` |
| System Settings | — | — | ✅ | `px.page_system_settings` |
| ML Model Management | — | — | ✅ | `page_training` |
| Activity Logs | — | — | ✅ | `page_audits` |
| Backup & Restore | — | — | ✅ | `px.page_backup_restore` |

**Data scoping rule:** `auth_db.get_predictions(user_id=...)` is called with the caller's id when `role == 'Doctor'`, and with `None` (= all rows, joined to doctor names) otherwise. This is the only row-level access control in the system and it is applied consistently across `page_diagnosis`, `page_history`, `px.page_dashboard`, `px.page_patient_management` and `px.page_reports`.

**Matrix vs. reality:** the capability matrix at [pages_ext.py:614-624](pages_ext.py#L614-L624) claims SuperAdmin can "Run Predictions", but SuperAdmin has no prediction page in its nav list. The matrix is a hard-coded display table, not a live permission source.

### 6.4 Page inventory

**`app.py`**

| Function | Line | Role | Purpose |
|---|---|---|---|
| `page_login` | [290](app.py#L290) | public | Sign In / Register tabs; prints all three default credentials on screen |
| `render_sidebar` | [371](app.py#L371) | all | User card + nav radio + sign-out |
| `page_diagnosis` | [396](app.py#L396) | Doctor | The core inference page — see §7 |
| `page_history` | [661](app.py#L661) | Doctor | Searchable prediction log with CSV export |
| `page_profile` | [714](app.py#L714) | all | Edit name / email / specialisation / password |
| `page_help` | [739](app.py#L739) | — | **DEAD — never routed** |
| `page_admin_users` | [782](app.py#L782) | — | **DEAD — never routed** |
| `page_admin_analytics` | [852](app.py#L852) | Admin, SuperAdmin | Platform-wide statistics and trends |
| `page_training` | [965](app.py#L965) | SuperAdmin | 4 tabs: Train · Enable/Disable · Leaderboard · History |
| `page_audits` | [1104](app.py#L1104) | SuperAdmin | Audit log viewer + destructive "Danger Zone" |
| `page_model_performance` | [1157](app.py#L1157) | all | **1,480-line function**, 8 tabs — see §8 |

**`pages_ext.py`** (imported as `px`)

| Function | Line | Purpose |
|---|---|---|
| `page_dashboard` | [53](pages_ext.py#L53) | Role-aware KPI strip, recent predictions, accuracy bar chart, activity feed |
| `page_patient_management` | [143](pages_ext.py#L143) | Patient records with search/filter, per-record delete, CSV export |
| `page_reports` | [210](pages_ext.py#L210) | Date-range clinical summary, risk-trend chart, downloadable text report |
| `page_doctor_management` | [309](pages_ext.py#L309) | Doctor account CRUD |
| `page_prediction_management` | [387](pages_ext.py#L387) | System-wide prediction administration |
| `page_dataset_management` | [478](pages_ext.py#L478) | Upload CSV → save as custom, or overwrite `heart.csv`; dataset statistics |
| `page_admin_management` | [550](pages_ext.py#L550) | Admin account CRUD |
| `page_role_permissions` | [609](pages_ext.py#L609) | Static capability matrix + bulk role reassignment |
| `page_system_settings` | [662](pages_ext.py#L662) | Writes `system_settings.json` — **none of it is enforced** (CONTEXT.md M3) |
| `page_backup_restore` | [730](pages_ext.py#L730) | Zip export of DB + models + settings; zip import of models + settings |
| `page_model_performance` | [816](pages_ext.py#L816) | **DEAD — 353 lines, shadowed by the `app.py` version** |

### 6.5 Database schema — `heartguard.db`

Created idempotently by `init_db()` ([auth_db.py:14](auth_db.py#L14)). All queries use parameterised statements; no SQL injection surface was found.

```sql
users (id PK, username UNIQUE NOT NULL, password_hash NOT NULL, role NOT NULL,
       fullname, email, specialisation DEFAULT '', is_banned DEFAULT 0, created_at)

predictions (id PK, user_id NOT NULL FK→users ON DELETE CASCADE,
             age, gender, height, weight, ap_hi, ap_lo, cholesterol, gluc,
             smoke, alco, active,
             predicted_class, probability, model_used,
             patient_name DEFAULT '', notes DEFAULT '', timestamp)

system_logs (id PK, user_id, username, action NOT NULL, details, timestamp)

training_runs (id PK, triggered_by, status DEFAULT 'running',
               duration_s, results_json, timestamp)
```

**Notes.** `predictions` stores the eleven *raw* inputs — not the four engineered features — so historical rows cannot be re-scored without recomputing them. `ON DELETE CASCADE` is declared but SQLite does not enforce foreign keys unless `PRAGMA foreign_keys=ON` is set, which it never is; deleting a user therefore orphans their predictions. `patient_id` from the form is never persisted (only `patient_name`).

**Seeded accounts** (created only when `users` is empty):

| Username | Password | Role |
|---|---|---|
| `doctor` | `doctor123` | Doctor |
| `admin` | `admin123` | Admin |
| `superadmin` | `superadmin123` | SuperAdmin |

**Live database state (2026-07-26):** 8 users, 5 predictions, 50 log entries, 4 training runs. Three accounts hold `SuperAdmin` — `superadmin` (seeded) plus `doctor` and `zarqa`, both elevated through the self-service registration hole (CONTEXT.md C3).

**Audit logging.** `log_activity()` is called on: Registration, Login, Logout, Prediction, Profile Update, Role Change, Ban/Unban, Delete User, Delete Prediction, Clear Predictions, Purge Logs, Model Training, Config Update, Dataset Upload/Replace, System Settings, Backup, Restore.

---

## 7. End-to-end prediction workflow

The critical path, `page_diagnosis` ([app.py:396-655](app.py#L396-L655)):

```
1. load_models()                     scaler + 5 estimators (cached)
2. load_config()                     filter to models enabled in config.json
3. Form input                        Patient ID*, Name*, 11 clinical indicators, model choice
4. Validate                          only that ID and Name are non-empty
5. Derive 4 engineered features      app.py:461-474 — mirrors train_models.py by hand
6. Assemble 15-vector                positional, must match features.json order
7. scaler.transform([features])
8. Score every active model          predict() and predict_proba()[0][1]
9. Aggregate
     Ensemble  → mean of probabilities, threshold 0.5
     Single    → that model's predict() and predict_proba()
10. auth_db.add_prediction(...)      persists + writes an audit entry
11. Render                           verdict card, probability bar, feature-importance chart,
                                     per-model breakdown (ensemble only)
12. Downloadable text report
```

### 7.1 Input encoding sent by the form

| Field | Widget | Values sent | Matches training data? |
|---|---|---|---|
| Age | number 1–120 | years | ✅ |
| Gender | select | 1 = Male, 0 = Female | ✅ |
| Height | number 100–250 | cm | ✅ |
| Weight | number 20–200 | kg | ✅ |
| Systolic BP | number 60–250 | mmHg | ✅ |
| Diastolic BP | number 40–200 | mmHg | ✅ |
| **Cholesterol** | select | **0 / 1 / 2** | ✅ from `fe.CHOLESTEROL_LEVELS` |
| **Glucose** | select | **0 / 1 / 2** | ✅ from `fe.GLUCOSE_LEVELS` |
| Smoker | select | 1 / 0 | ✅ |
| Alcohol | select | 1 / 0 | ✅ |
| Active | select | 1 / 0 | ✅ |

All eleven inputs now match the training distribution. The cholesterol/glucose mismatch
(BUG-04) was the highest-severity functional defect on the inference path; it was fixed in Run 3
by sourcing the options from the shared module.

### 7.2 Feature derivation — one implementation, three consumers

Before Run 3 this logic existed in **three unsynchronised copies** (training, diagnosis form, SHAP
background) which had already drifted apart on the `high_risk_flag` threshold.

It now lives solely in [feature_engineering.py](feature_engineering.py):

```python
fe.build_feature_row(...)   # single patient  -> list in FEATURE_ORDER
fe.engineer_features(df)    # vectorised      -> adds the 4 derived columns
```

| Consumer | Call |
|---|---|
| `train_models.py` step 5 | `fe.engineer_features(df)` |
| `app.py` diagnosis form | `fe.build_feature_row(...)` |
| `app.py` SHAP background | `fe.engineer_features(_df_bg)` |

Changing a derived feature now means editing one function.

### 7.3 Decision rule

| Path | Rule |
|---|---|
| Ensemble | `mean(probabilities) >= get_risk_threshold()` |
| Single model | `probability >= get_risk_threshold()` |

One rule for both paths, driven by `risk_threshold` in `system_settings.json` (default 0.5).
Before Run 3 the ensemble hardcoded 0.5 while the single-model path used the estimator's internal
rule — two different answers for the same patient depending on a dropdown (BUG-18).

---

## 8. Model Performance page — 8 tabs

`page_model_performance` ([app.py:1157](app.py#L1157)) renders everything from `results.json`; it never loads a model except in the SHAP tab.

| Tab | Content |
|---|---|
| 1. Metric Comparison | Full table with best-in-class highlighting, grouped bar chart, train/predict timing |
| 2. Confusion Matrices | Per-model heatmaps with TP/TN/FP/FN breakdown |
| 3. Detailed Report | Per-class precision/recall/F1/support from the sklearn report dict |
| 4. Model Info | Algorithm descriptions and characteristics |
| 5. Feature Importance | `feature_importances_` / `coef_` per model |
| 6. ROC & PR Curves | Overlaid curves from the stored 100-point downsamples |
| 7. K-Fold CV | Per-fold lines, mean ± σ bars, stability ranking |
| 8. Explainable AI (SHAP) | `TreeExplainer` / `LinearExplainer` / `KernelExplainer` by model type; mean\|SHAP\| ranking, beeswarm, dependence, waterfall |

**SHAP mechanics** ([app.py:2314-2393](app.py#L2314-L2393)): background is built from raw `heart.csv` (age converted, target/id dropped, four features re-derived, scaled), sampled to 300 rows, `random_state=42`. Tree models use `TreeExplainer`; `CalibratedClassifierCV` and anything else fall back to `KernelExplainer` on an 80-row subsample with `nsamples=60`. Failures return an error string and render a message rather than raising.

**Two caveats.** The background skips the domain filter, so it contains `cholesterol=0` rows no model ever trained on. And the analysis is global only — the per-patient diagnosis page shows static `feature_importances_`, identical for every patient, labelled "Top Risk Factors".

---

## 9. Training workflow (SuperAdmin)

`page_training` → "Start Full Training Pipeline" ([app.py:998-1020](app.py#L998-L1020)):

```
subprocess.run(["python", "train_models.py"], cwd=BASE_DIR, timeout=600)
  → on returncode 0:  reload results.json
                      auth_db.log_training_run(user_id, "success", duration, results)
                      st.cache_resource.clear()
                      display last 3,000 chars of stdout
  → on failure:       display last 2,000 chars of stderr
```

Training runs **in-process-blocking** — the Streamlit worker waits up to 10 minutes. The invocation uses bare `"python"` rather than `sys.executable`, so it depends on PATH resolving to the venv interpreter (CONTEXT.md M6).

`train_models.py` overwrites all six artifacts plus `results.json` and `preprocess_report.txt` in place. There is no versioning, no backup of the previous generation, and no provenance metadata — `preprocess_report.txt` currently records `C:\Users\Ariha\Desktop\self project\HeartGuard FYP\heart.csv`, a path from a different machine.

### Custom dataset path

Both `page_training` and `px.page_dataset_management` can write `custom_dataset.csv`, which `train_all()` prefers over `heart.csv`. `px.page_dataset_management` can also overwrite `heart.csv` outright. No schema validation is performed beyond a preview — an incompatible upload is only discovered when training fails.

---

## 10. Running the project

```powershell
cd "i:\Ariha\FYP\HeartGuard FYP\HeartGuard FYP"
.\.venv\Scripts\Activate.ps1
streamlit run app.py            # → http://localhost:8501
```

Retrain from the CLI:

```powershell
.\.venv\Scripts\python.exe train_models.py
```

First run creates `heartguard.db` and seeds the three default accounts. Sign in with `superadmin / superadmin123` for the full navigation set.

---

## 11. Known dead and unused assets

| Item | Size | Status |
|---|---|---|
| `pages_ext.page_model_performance` | 353 L | Shadowed — router calls the `app.py` version |
| `app.page_help` | 38 L | Defined, never routed |
| `app.page_admin_users` | 66 L | Defined, never routed |
| `check.py` | 7 L | One-shot debug script |
| `fix_indent.py` | 30 L | One-shot repair script |
| `fix_all_indent.py` | 107 L | One-shot repair script |
| `fix_unicode.py` | 49 L | One-shot repair script |
| `heart_bg_b64.txt` | 68 KB | `get_bg_b64()` looks for `heart_bg.png`, which does not exist — always returns `None` |
| `__pycache__/` | — | Mixed cpython-313 / cpython-314 bytecode |

**≈650 lines of dead code and 68 KB of unused assets.** Still present after Run 3 — removal is
tracked as deferred work in [TASK.md](TASK.md) §3.5, since deleting it is cosmetic and carries
non-zero risk of touching a live path.

The unrouted `page_help` also contains two factual errors: it describes Random Forest as "an ensemble of 150 trees" (the code trains 200) and gives overlapping risk bands — "Low Risk (< 50%)", "Borderline (40–59%)", "High Risk (≥ 60%)" — which leave 50–59% unclassified while the code thresholds hard at 50%.

---

## 12. System invariants

Break any of these and the system produces wrong answers silently.

0. **Encoding and feature contract live in [feature_engineering.py](feature_engineering.py).** Import from it; never re-implement. A literal `[1,2,3]` or `>= 2` on cholesterol/gluc is a bug.
1. **Feature order** — `fe.FEATURE_ORDER` / `models/features.json` define the positional contract for `scaler.pkl` and all five estimators. Never reorder.
2. **Feature count** — exactly 15. `app.py:555` guards the importance chart with a length check; nothing else does.
3. **Categorical encoding** — `cholesterol` and `gluc` are **0/1/2** in `heart.csv`. `gender` is **0 = female, 1 = male**.
4. **Artifacts are a set** — `scaler.pkl`, the five `.pkl` models, `features.json` and `imputer_medians.json` are produced by one run and are only valid together. `models/manifest.json` records a SHA-256 for each; Backup & Restore verifies against it.
5. **Engineered features have ONE implementation** — `feature_engineering.py`. Three consumers import it.
6. **`config.json` keys must match `load_models()` labels exactly** — `"Support Vector Machine (SVM)"` including the parenthetical.
7. **`results.json` keys drive the entire Model Performance page** — renaming a model breaks all eight tabs.
8. **`auth_db` import has the side effect of creating the database.**

---

## 13. Where to look first

| Task | File and line |
|---|---|
| Fix the encoding bug | [train_models.py:211-213](train_models.py#L211-L213), [app.py:440-445](app.py#L440-L445), [app.py:474](app.py#L474) |
| Change preprocessing | [train_models.py:326-410](train_models.py#L326-L410) |
| Change models or hyperparameters | [train_models.py:413-490](train_models.py#L413-L490) |
| Change the inference path | [app.py:456-498](app.py#L456-L498) |
| Change the decision threshold | [app.py:486-492](app.py#L486-L492) |
| Add or reorder a page | [app.py:2643-2726](app.py#L2643-L2726) |
| Change auth or the schema | [auth_db.py:14-115](auth_db.py#L14-L115) |
| Change evaluation charts | [app.py:1157-2640](app.py#L1157-L2640) |
| Change SHAP behaviour | [app.py:2251-2640](app.py#L2251-L2640) |

---

**Continue to [CONTEXT.md](CONTEXT.md)** for the audit findings and the measurements behind them,
or to **[TASK.md](TASK.md)** for the run-by-run change log — what was fixed, why, how, and how it
was verified.
