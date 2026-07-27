# HeartGuard AI — Task & Change Log

> **Purpose.** This is the living engineering journal for the project. **Every run appends a new section.**
> Each task records **WHAT** changed, **WHY** it was necessary, **HOW** it was implemented, and **HOW IT WAS VERIFIED**.
> Never overwrite a previous run's entry — append below it.
>
> **Companions:** [PROJECT.md](PROJECT.md) — what the system is · [CONTEXT.md](CONTEXT.md) — audit findings & measurements

---

## Run index

| Run | Date | Scope | Status |
|---|---|---|---|
| 1 | 2026-07-26 | Full audit — 28 findings, no code changes | ✅ Complete |
| 2 | 2026-07-26 | Runtime bug hunt — executed all 27 page×role paths | ✅ Complete |
| 3 | 2026-07-26 | **Fix all 21 bugs + retrain** | ✅ Complete — 22/22 fixed (BUG-22 found in verification), 27/27 pages passing |
| 4 | 2026-07-27 | **Evidence-based decision threshold** — replace hardcoded 0.50 with derived per-model operating points | ✅ Complete — miss rate halved, 27/27 pages passing |
| 5 | 2026-07-27 | **Subgroup performance & fairness** — age-stratified thresholds, subgroup reporting, OOF derivation | ✅ Complete — sensitivity equalised across ages, 27/27 pages passing |
| 6 | 2026-07-27 | **Clinical benchmark & dataset ceiling** — Framingham/BP-rule/clinical-LR comparators, ceiling proven 3 ways | ✅ Complete — 27/27 pages passing |
| 7 | 2026-07-27 | **BUG-23 applicability guard** + patient entity, outcome capture, model versioning, units, monotonic constraints | ✅ BUG-23 complete — see §7.9 for pending wiring |
| 8 | 2026-07-27 | **Live testing campaign** — clicked every button/form; found & fixed BUG-24…28 | ✅ Complete — 0 failures across 5 suites |

---

# RUN 3 — Fix all bugs (2026-07-26)

## 3.0 — Bug register (the 21 defects being fixed)

| ID | Severity | Defect | Location |
|---|---|---|---|
| BUG-01 | 🔴 Crash | CSS `rgba()` string passed to matplotlib — Model Performance page dies for all 3 roles | [app.py:1640](app.py#L1640) |
| BUG-02 | 🔴 Crash | Same defect, second instance in SHAP tab | [app.py:2411](app.py#L2411) |
| BUG-03 | 🔴 Data | `isin([1,2,3])` on 0-indexed data discards 89.8% of rows | [train_models.py:213](train_models.py#L213) |
| BUG-04 | 🔴 Data | Diagnosis form sends 1/2/3 to models trained on 0/1/2 | [app.py:441,444](app.py#L441) |
| BUG-05 | 🔴 Data | `high_risk_flag` threshold inconsistent across 3 unsynchronised copies | [train_models.py:296](train_models.py#L296), [app.py:474](app.py#L474), [app.py:2349](app.py#L2349) |
| BUG-06 | 🟠 Data | Age rounded before dedup → 3,821 fabricated duplicates deleted | [train_models.py:167](train_models.py#L167) |
| BUG-07 | 🟠 Data | IQR winsorization flattens 181 severe hypertensives (89% cardio rate) | [train_models.py:363](train_models.py#L363) |
| BUG-08 | 🔴 ML | Models under-predict risk by 7.7 points vs true prevalence | consequence of BUG-03 |
| BUG-09 | 🔴 Sec | Public registration form grants SuperAdmin on request | [app.py:345](app.py#L345) |
| BUG-10 | 🔴 Sec | Pickle RCE — restore writes unvalidated `.pkl` into the load path | [pages_ext.py:795](pages_ext.py#L795) |
| BUG-11 | 🔴 Sec | Unsalted SHA-256 password hashing | [auth_db.py:10](auth_db.py#L10) |
| BUG-12 | 🟠 Sec | Stored XSS — user fields interpolated into raw HTML | [app.py:375](app.py#L375) |
| BUG-13 | 🟠 Silent | `fillna(inplace=True)` is a no-op under pandas 3 | [train_models.py:261](train_models.py#L261) |
| BUG-14 | 🟠 ML | Preprocessing fitted on test data (leakage) | [train_models.py:363-376](train_models.py#L363) |
| BUG-15 | 🟠 ML | K-fold CV reuses training rows and a train-fitted scaler | [train_models.py:497](train_models.py#L497) |
| BUG-16 | 🟡 Bug | `subprocess.run(["python"])` instead of `sys.executable` | [app.py:1003](app.py#L1003) |
| BUG-17 | 🟡 Bug | `risk_threshold` / `allow_registration` etc. saved but never enforced | [pages_ext.py:662](pages_ext.py#L662) |
| BUG-18 | 🟡 Bug | Ensemble and single-model paths use different decision rules | [app.py:483,488](app.py#L483) |
| BUG-19 | 🟡 Bug | `short_names` positional — mislabels models if `results.json` is a subset | [app.py:828](app.py#L828) |
| BUG-20 | 🟡 Bug | `ON DELETE CASCADE` inert — `PRAGMA foreign_keys` never enabled | [auth_db.py:41](auth_db.py#L41) |
| BUG-21 | ⚪ Bug | Arrow serialization failure on K-Fold table (mixed int/str column) | K-Fold tab |
| BUG-22 | 🔴 Data | *Found during verification.* Retention guardrail cannot detect a 1-indexed dataset — silently deletes every "well above normal" patient | `train_models.py` `_domain_filter` |

**Two exploit chains closed by this run:** `BUG-09 → BUG-10` (unauthenticated RCE) and `BUG-03 → BUG-04 → BUG-08` (unsafe clinical scores).

---

## 3.1 — Planned task list

| # | Task | Fixes | Files |
|---|---|---|---|
| T1 | Back up all sources + model artifacts | — | `.backup_pre_fix_20260726/` |
| T2 | Create `feature_engineering.py` — single source of truth for encodings & derived features | BUG-05 | new file |
| T3 | Rewrite `train_models.py` preprocessing to be leak-free and encoding-correct | BUG-03,06,07,13,14,15 | `train_models.py` |
| T4 | Adaptive class weighting + calibration metrics (Brier/ECE) in results | BUG-08 | `train_models.py` |
| T5 | Fix matplotlib colour bugs | BUG-01,02 | `app.py` |
| T6 | Fix diagnosis form encoding + shared feature builder + unified threshold | BUG-04,05,18 | `app.py` |
| T7 | Lock registration to Doctor role | BUG-09 | `app.py` |
| T8 | Escape user-controlled HTML | BUG-12 | `app.py` |
| T9 | Use `sys.executable` for training subprocess | BUG-16 | `app.py` |
| T10 | Key model short-names by name, not position | BUG-19 | `app.py` |
| T11 | Fix K-Fold table column dtype | BUG-21 | `app.py` |
| T12 | PBKDF2 password hashing with transparent legacy upgrade | BUG-11 | `auth_db.py` |
| T13 | Enable SQLite foreign-key enforcement | BUG-20 | `auth_db.py` |
| T14 | Allowlist + SHA-256 digest verification on backup restore | BUG-10 | `pages_ext.py` |
| T15 | Enforce `risk_threshold` and `allow_registration` | BUG-17 | `pages_ext.py`, `app.py` |
| T16 | Retrain all 5 models on the corrected pipeline | — | `models/*` |
| T17 | Verify — re-run all 27 page×role paths + measure calibration | — | — |
| T18 | Update PROJECT.md / CONTEXT.md / TASK.md | — | docs |

---

## 3.2 — Design decisions (evidence-based)

### D1 — Do NOT wrap models in `CalibratedClassifierCV`

**Question.** BUG-08 (under-prediction) suggested adding isotonic calibration. Should we?

**Evidence.** Measured on the corrected 68,621-row corpus, honest holdout:

| Config | AUC | Brier | ECE | Mean predicted |
|---|---:|---:|---:|---:|
| LR `class_weight='balanced'` | 0.7894 | 0.1876 | 0.0320 | 0.497 |
| LR no class weight | 0.7894 | 0.1876 | 0.0317 | 0.494 |
| RF `class_weight='balanced'` | 0.7985 | 0.1819 | 0.0126 | 0.496 |
| RF no class weight | 0.7989 | 0.1818 | **0.0124** | 0.493 |
| XGB `scale_pos_weight` | 0.7990 | 0.1815 | 0.0093 | 0.496 |
| XGB default | 0.7993 | 0.1814 | **0.0094** | 0.493 |
| RF + isotonic | 0.7988 | 0.1818 | 0.0116 | 0.492 |
| *true prevalence* | | | | *0.495* |

**Decision.** No calibration wrapper.

**Why.** Fixing BUG-03 restores natural class balance (49.5%), which fixes BUG-08 on its own — mean predicted probability now lands within 0.002 of true prevalence, and ECE is already ~0.01. Isotonic calibration measurably *fails to improve* on this (0.0116 vs 0.0124) and would strip `feature_importances_` from RF/XGB, breaking the Feature Importance tab and the SHAP `TreeExplainer`. Paying an XAI cost for no calibration gain is a bad trade.

**Instead:** report Brier score and Expected Calibration Error in `results.json` so calibration is *measured and visible* rather than assumed.

### D2 — Class weighting becomes adaptive, not hardcoded

`class_weight='balanced'` was distorting probabilities on data that is now balanced. But a user-uploaded `custom_dataset.csv` may well be imbalanced. **Decision:** compute the imbalance ratio at train time and enable class weighting only when it exceeds 1.5×. Correct for both cases, no manual switch.

### D3 — Keep `scaler.pkl` separate rather than moving to a full `Pipeline`

A `Pipeline(StandardScaler, model)` is the textbook leakage fix, but the app, the SHAP background builder and the Feature Importance tab all call `scaler.transform(...)` then `model.predict(...)` independently. **Decision:** keep the artifact contract, and fix the leakage at its actual source — remove pre-split winsorization, compute imputation medians and correlation pruning on the training split only, and cross-validate a freshly-built pipeline over the training split only. Leak-free with a far smaller blast radius.

### D4 — Delete winsorization outright rather than moving it inside the split

Step 4's physiological domain filter already bounds every field to a clinically plausible range. IQR clipping on top of that removes real signal (BUG-07: 181 patients at 89% cardio rate flattened). **Decision:** remove it. Documented in the training log so the choice is visible in the report.

---

## 3.3 — Execution log

*(populated as each task completes — see below)*

### T1 — Back up sources and artifacts ✅

**Why.** The project has no version control (CONTEXT.md L4), so there is no rollback path if a fix regresses.
**How.** Copied `app.py`, `auth_db.py`, `train_models.py`, `pages_ext.py`, `requirements.txt`, `heartguard.db` and the entire `models/` directory into `.backup_pre_fix_20260726/`.
**Verified.** 6 files + 10 model artifacts present in the backup directory.

---

### T2 — Create `feature_engineering.py` ✅  *(fixes BUG-05)*

**Why.** The four derived features (`bmi`, `pulse_pressure`, `age_group`, `high_risk_flag`) were implemented **three times** — in `train_models.py`, in the diagnosis form, and in the SHAP background builder. They had already drifted: `high_risk_flag` used `cholesterol >= 2`, which meant "well above normal" against the training data but "above normal or worse" against the form's scale. The flag fired on a different population at train time than at serve time, and nothing could detect that.

**How.** New module holding the single source of truth for:
- **Encoding constants** — `CHOLESTEROL_LEVELS`, `GLUCOSE_LEVELS`, `GENDER_LEVELS`, `ORDINAL_VALID_VALUES`, all 0-indexed, with a prominent docstring warning that any `[1,2,3]` literal elsewhere is a bug
- **`FEATURE_ORDER`** — the positional contract the scaler and all five estimators depend on
- **`ELEVATED_THRESHOLD = 1`** — one named constant instead of three magic numbers
- **`build_feature_row(...)`** — the only supported way to construct an inference vector
- **`engineer_features(df)`** — vectorised equivalent for training and SHAP

**Verified.** `compute_high_risk_flag(chol=1, ap_hi=150) → 1` and `(chol=0, ap_hi=150) → 0`, identical in all three call sites because there is now only one implementation.

---

### T3 — Rewrite `train_models.py` preprocessing ✅  *(fixes BUG-03, 06, 07, 13, 14, 15)*

**Why.** The pipeline was discarding 89.8% of the dataset, deleting 3,797 real patients, destroying the strongest clinical signal, silently failing to impute, and fitting three preprocessing steps on data that later became the holdout.

**How — step by step:**

| Fix | Change | Reason |
|---|---|---|
| BUG-03 | `.isin([1,2,3])` → `.isin(fe.ORDINAL_VALID_VALUES)` = `{0,1,2}` | Matches this dataset's 0-indexed encoding |
| BUG-03 | Added `MIN_RETENTION_RATIO = 0.80` guardrail that **raises** on excessive attrition | This assertion is what would have caught the bug on day one; it now fails loudly instead of silently training on 10% of the data |
| BUG-06 | Reordered: dedup (step 2) now runs **before** age days→years (step 3) | Rounding first collapsed patients differing by days into "duplicates" |
| BUG-07 | Deleted `_winsorize_iqr` entirely | The domain filter already bounds every field; clipping on top flattened 181 severe hypertensives (89% cardio rate) onto the cap |
| BUG-13 | `df[col].fillna(v, inplace=True)` → `df[col] = df[col].fillna(v)` | The old form is chained assignment on a copy — a silent no-op under pandas 3 |
| BUG-13 | Removed module-level `warnings.filterwarnings("ignore")` | It was actively suppressing the `ChainedAssignmentError` that would have revealed BUG-13 |
| BUG-14 | Split moved to step 6; imputation medians, correlation pruning and scaler all fitted on the **train split only** | No preprocessing sees the holdout |
| BUG-15 | `_kfold_cv` now cross-validates an unfitted `Pipeline(StandardScaler → clone(estimator))` over the **training split only** | Previously it used a train-fitted scaler over the full dataset, so CV "test" folds were scaled by their own statistics and overlapped the training rows |

**Also added:** `imputer_medians.json` (so inference could apply the same medians), and a provenance manifest (below).

**Verified.** Training runs clean; retention 97.1% (68,645 of 70,000); the guardrail does not trip.

---

### T4 — Adaptive class weighting + calibration metrics ✅  *(fixes BUG-08)*

**Why.** Models under-predicted population risk by 7.7 points — the harmful direction for a screening tool, since it produces false reassurance.

**How.** Two changes, both driven by the measurements in §3.2 D1/D2:
1. **Adaptive weighting.** `class_weight` and `scale_pos_weight` are now derived from the measured imbalance ratio — `'balanced'` only when it exceeds 1.5×, otherwise `None`. On the corrected data (1.02× imbalance) weighting is correctly disabled; an imbalanced custom upload still gets it automatically.
2. **Calibration is measured, not assumed.** `_evaluate()` now records `brier`, `ece` (Expected Calibration Error), `mean_predicted`, `test_prevalence`, plus a binned `reliability` curve, into `results.json`. A calibration summary table prints at the end of every training run.

**Why no `CalibratedClassifierCV`.** Measured: isotonic calibration made RF *worse* (ECE 0.0116 vs 0.0124) and would have stripped `feature_importances_`, breaking the Feature Importance tab and the SHAP `TreeExplainer`. Fixing BUG-03 restored natural class balance, which fixed the calibration on its own.

**Verified.** Mean predicted probability now lands within **0.0002** of true prevalence:

| Model | Brier | ECE | Mean predicted | Actual prevalence |
|---|---:|---:|---:|---:|
| Logistic Regression | 0.1864 | 0.0267 | 0.4947 | 0.4947 |
| SVM | 0.1865 | 0.0260 | 0.4947 | 0.4947 |
| Decision Tree | 0.1840 | 0.0144 | 0.4940 | 0.4947 |
| Random Forest | 0.1814 | 0.0110 | 0.4945 | 0.4947 |
| XGBoost | 0.1811 | **0.0103** | 0.4949 | 0.4947 |

---

### T5 — Fix matplotlib colour crash ✅  *(fixes BUG-01, BUG-02)*

**Why.** The Model Performance page — the flagship 8-tab evaluation suite, visible to all three roles — crashed on load. Because Streamlit renders every tab in one pass, the exception in Tab 5 also killed Tabs 6, 7 and 8, so ROC/PR curves, K-Fold CV and the entire SHAP explainability section never rendered.

**Root cause.** Both sites built CSS `rgba(r,g,b,a)` strings and passed them to `ax.barh(color=...)`. Matplotlib accepts hex strings or 0–1 float tuples, not CSS syntax → `ValueError: Invalid RGBA argument: 'rgba(61,112,206,0.85)'`.

**How.** Added `gradient_hex(j, n, start, end)` returning a matplotlib-safe `#rrggbb`, and replaced both colour-list comprehensions with calls to it.

**Verified.** All three roles now load Model Performance without exception (see T17).

---

### T6 — Fix diagnosis form encoding + shared features + unified threshold ✅  *(fixes BUG-04, 05, 18)*

**Why.** The form sent 1/2/3 to models trained on 0/1/2, so "Normal" was scored as above-normal and "Well Above Normal" sent a value (3) that appears nowhere in the training data — the scaler mapped it to z = +2.87 against a training maximum of +0.83.

**How.**
- Selectbox options now come from `fe.CHOLESTEROL_LEVELS` / `fe.GLUCOSE_LEVELS` (0-indexed)
- Report labels come from `fe.CHOLESTEROL_LABELS` / `fe.GLUCOSE_LABELS`
- The 14 lines of hand-rolled feature derivation were replaced with one `fe.build_feature_row(...)` call
- **BUG-18:** both branches now threshold on `get_risk_threshold()`. Previously the ensemble used a hardcoded `>= 0.5` while the single-model path used the estimator's internal `predict()` — two different rules for the same patient depending on a dropdown.

**Verified.** Every selectable value now maps inside the training range:

| Value | z-score before | z-score now |
|---|---:|---:|
| Normal | −1.20 *(mislabelled)* | −0.54 |
| Above Normal | +0.83 | +0.93 |
| Well Above Normal | **+2.87** *(never seen)* | +2.41 |

End-to-end: healthy 30-year-old **7.2%** risk, high-risk 65-year-old **90.5%** — sharper separation than the pre-fix 12.9% / 84.9%.

---

### T7 — Lock registration to the Doctor role ✅  *(fixes BUG-09)*

**Why.** The unauthenticated Register tab let a visitor pick their own role from a dropdown that included `SuperAdmin`. Already exploited — two accounts in the live database (`doctor`, `zarqa`) had elevated themselves this way. Combined with BUG-10 this was unauthenticated RCE.

**How.** Replaced the selectbox with `r_role = "Doctor"` plus a caption explaining how to request elevation. Role changes now happen only through Role & Permission Management, by an authenticated SuperAdmin.

**Verified.** `grep 'r_role = ' app.py` → `r_role = "Doctor"`, single occurrence.

---

### T8 — Escape user-controlled HTML ✅  *(fixes BUG-12)*

**Why.** `fullname`, `username` and `email` — all settable by any user at registration or in Profile Settings — were interpolated directly into `unsafe_allow_html` sidebar markup.

**How.** Added `esc()` (wrapping `html.escape`) and applied it to all three interpolations.

---

### T9 — Use `sys.executable` for training ✅  *(fixes BUG-16)*

**Why.** `subprocess.run(["python", script])` resolved `python` from PATH. Launched outside an activated venv it would hit a different interpreter — silently degrading XGBoost to `GradientBoostingClassifier`, or failing outright.

**How.** `["python", script]` → `[sys.executable, script]`, and imported `sys`.

---

### T10 — Key model labels by name, not position ✅  *(fixes BUG-19)*

**Why.** `short_names = ["LR","SVM","DT","RF","XGB"][:len(model_names)]` was zipped positionally against whatever keys `results.json` happened to hold. If training partially failed and only some models were saved, **every confusion matrix, bar and legend was labelled with the wrong model's name** — silently, with no error.

**How.** Added name-keyed `MODEL_SHORT_NAMES` and `MODEL_COLORS` dicts with a safe fallback for unknown models. Applied in both `app.py` and `pages_ext.py`.

---

### T11 — Fix K-Fold table dtype ✅  *(fixes BUG-21)*

**Why.** The `Fold` column mixed integers (`1..5`) with the strings `"Mean"` and `"Std"`, producing an object-dtype column that pyarrow could not serialise — Streamlit logged a full traceback on every render before falling back to coercion.

**How.** `"Fold": fid + 1` → `"Fold": str(fid + 1)`.

---

### T12 — PBKDF2 password hashing ✅  *(fixes BUG-11)*

**Why.** Passwords were bare unsalted SHA-256 — identical passwords produced identical digests, and the whole table falls to a rainbow table instantly.

**How.** PBKDF2-HMAC-SHA256, 16-byte random salt, 200,000 iterations, stored as `pbkdf2_sha256$<iters>$<salt>$<hash>`. Verification uses `hmac.compare_digest` to avoid timing leaks.

**Why PBKDF2 rather than bcrypt/argon2.** It is in the standard library, so the project still installs from `requirements.txt` with no new dependency — important for an FYP that has to run on a marker's machine.

**Migration.** No user is locked out: legacy 64-hex digests are still *verified*, and on the next successful login the password is transparently re-hashed to PBKDF2.

**Verified.** All three default accounts logged in successfully against their existing legacy hashes and were upgraded in place; wrong passwords still rejected; salts unique per call.

---

### T13 — Enable SQLite foreign keys ✅  *(fixes BUG-20)*

**Why.** `predictions.user_id` declares `ON DELETE CASCADE`, but SQLite ignores foreign keys unless the PRAGMA is set per connection — so deleting a user silently orphaned all their prediction rows.

**How.** Added `_connect()` which sets `PRAGMA foreign_keys = ON`, and routed all 17 direct `sqlite3.connect(DB_PATH)` calls through it.

**Note.** The bulk replace initially rewrote the body of `_connect()` itself into infinite recursion; caught and corrected before any test run.

**Verified.** `PRAGMA foreign_keys` returns `1` on a fresh connection.

---

### T14 — Harden Backup & Restore ✅  *(fixes BUG-10)*

**Why.** The restore loop wrote **any** file under `backup/models/` straight into `models/`, where `load_models()` later `pickle.load`s it. A crafted `__reduce__` payload executed arbitrary code on the next page view.

**How.** Two independent controls:
1. **Allowlist** — only the 12 known artifact filenames are accepted; anything else is refused and reported, not silently written.
2. **Digest verification** — if the archive carries `manifest.json`, each incoming artifact's SHA-256 must match the digest recorded at training time.

The UI now reports how many files were accepted, refused as unlisted, and refused for digest mismatch, and aborts entirely if nothing validates.

**Verified.**

| Payload | Outcome |
|---|---|
| `evil.pkl` | REFUSED — not on allowlist |
| `backdoor.py` | REFUSED — not on allowlist |
| `random_forest.pkl` (tampered) | REFUSED — SHA-256 mismatch |
| `random_forest.pkl` (genuine) | ACCEPTED — digest matches |

---

### T15 — Enforce system settings ✅  *(fixes BUG-17)*

**Why.** `risk_threshold`, `allow_registration`, `max_predictions_per_day` and `session_timeout_min` were written to `system_settings.json`, displayed back to the SuperAdmin, and read by **no code anywhere**. Pure UI theatre.

**How.** Added `get_risk_threshold()` and `registration_allowed()`. The threshold now drives both decision paths in the diagnosis page (also resolving BUG-18); the registration tab refuses to render its form when registration is disabled.

**Verified.** Setting `risk_threshold: 0.35` → app reads `0.35`; `0.50` → reads `0.5`; `allow_registration: false` → `registration_allowed()` returns `False`.

**Not yet wired:** `max_predictions_per_day` and `session_timeout_min` still have no enforcement — they need a rate-limit table and a session-expiry mechanism respectively. Carried forward as open work (§3.5).

---

### T16 — Retrain on the corrected pipeline ✅

**How.** `python train_models.py` — 29.89 s, all five models, plus leak-free 5-fold CV.

**Result — before vs after:**

| Model | AUC before | AUC after | Δ | Accuracy before | Accuracy after |
|---|---:|---:|---:|---:|---:|
| Logistic Regression | 0.7245 | **0.7920** | +0.068 | 0.6765 | 0.7261 |
| SVM | 0.7246 | **0.7918** | +0.067 | 0.7160 | 0.7261 |
| Decision Tree | 0.6995 | **0.7933** | +0.094 | 0.6834 | 0.7253 |
| Random Forest | 0.7159 | **0.8000** | +0.084 | 0.7069 | 0.7303 |
| XGBoost | 0.7152 | **0.8000** | +0.085 | 0.6887 | 0.7330 |

| | Before | After |
|---|---:|---:|
| Training rows | 5,266 | **54,916** (10.4×) |
| Test rows | 1,317 | **13,729** |
| Corpus retained | 6,583 / 70,000 (9.4%) | **68,645 / 70,000 (98.1%)** |
| Class prevalence | 65.7% (biased) | **49.5%** (population-representative) |
| CV vs holdout AUC gap | leak-contaminated | 0.7998 vs 0.8000 — agree to 0.0002 |

**Also emitted:** `models/manifest.json` — dataset SHA-256, row count, prevalence, class-weight mode, library versions, and a digest for each of the 11 artifacts (addresses CONTEXT.md M7, and underpins T14's verification).

---

### T17 — Verification ✅

**How.** Re-ran the same `streamlit.testing.v1.AppTest` harness used to find BUG-01: every page, for every role, against the live database.

**Before fixes:**
```
[EXC ] Doctor      Model Performance   ValueError: Invalid RGBA argument
[EXC ] Admin       Model Performance   ValueError: Invalid RGBA argument
[EXC ] SuperAdmin  Model Performance   ValueError: Invalid RGBA argument
exceptions: 3   (24/27 passing)
```

**After fixes:**
```
[ ok ] Doctor      7/7 pages
[ ok ] Admin       9/9 pages
[ ok ] SuperAdmin  11/11 pages
exceptions: 0   (27/27 passing)
```

Static analysis clean — `py_compile` passes on all five modules; `pyflakes` reports only pre-existing unused locals, no undefined names.

---

### T19 — Encoding auto-normalisation ✅  *(fixes BUG-22 — found during post-fix verification)*

**How it was found.** After declaring Run 3 complete, I probed the most likely remaining weak spot: uploading the *canonical* Kaggle CSV (which encodes cholesterol/gluc as 1/2/3) through Dataset Management and retraining.

**The bug.** Training **succeeded silently** and produced a biased model. The `MIN_RETENTION_RATIO = 0.80` guardrail added in T3 is a *retention floor*, not an *encoding check* — and a one-off encoding shift is not expensive enough to trip it:

| | |
|---|---:|
| Rows dropped by `cholesterol == 3` | 8,066 |
| Rows dropped by `gluc == 3` | 5,331 |
| Retention | **85.8%** — above the 80% floor, so it **passed** |
| Prevalence | 0.4998 → **0.4644** |

Every "well above normal" patient — the most severe category, the strongest signal in the dataset — was deleted without a word. This is a milder recurrence of exactly the failure mode BUG-03 represented, which is precisely why it mattered: my guardrail protected against the *symptom* (mass attrition) rather than the *cause* (encoding mismatch).

**How it was fixed.** Added `fe.normalize_ordinal_encoding(df)`, called from `_basic_clean` before the domain filter runs. Detection rule: a 0-indexed column has `max == 2`; if a column's observed values sit in `[1, 3]` with `max == 3`, it is 1-indexed and is shifted down by one. Values outside both known encodings emit a warning naming the column and its observed range.

This turns a silent corruption into correct behaviour, and as a side effect makes the pipeline **encoding-agnostic** — it now trains correctly on either the project's `heart.csv` or the upstream Kaggle release.

**Verified.** Retraining on the 1/2/3-encoded copy now logs the shift and produces results **identical** to the 0/1/2 copy:

```
'cholesterol' detected as 1-indexed (observed 1..3) -> shifted to 0-indexed
'gluc'        detected as 1-indexed (observed 1..3) -> shifted to 0-indexed
Rows : 70,000 -> 68,645 (98.1% retained)   AUC 0.8000   ECE 0.0103
```

Canonical artifacts were then regenerated from `heart.csv` (the biased run had overwritten them), and the full 27-path regression re-run: **0 exceptions**.

**Lesson recorded.** A guardrail that measures a *consequence* can be evaded by a smaller dose of the same cause. Validate the invariant itself — here, the encoding — not just its blast radius.

---

## 3.4 — Summary of Run 3

| | |
|---|---|
| **Bugs fixed** | **22 / 22** (21 audited + BUG-22 found during verification) |
| Files modified | `app.py`, `auth_db.py`, `train_models.py`, `pages_ext.py` |
| Files created | `feature_engineering.py`, `models/manifest.json`, `models/imputer_medians.json`, `TASK.md` |
| Bug found *by* the fixes | BUG-22 — guardrail measured attrition, not the encoding invariant |
| Page×role paths passing | 24/27 → **27/27** |
| Best AUC | 0.7246 → **0.8000** |
| Training corpus | 6,583 → **68,645** rows |
| Calibration (ECE, best) | not measured → **0.0103** |
| Exploit chains closed | 2 (unauthenticated RCE; unsafe clinical scores) |

## 3.5 — Carried forward (not bugs; deferred work)

| Item | Note |
|---|---|
| `max_predictions_per_day` | Needs a per-user daily counter table before it can be enforced |
| `session_timeout_min` | Needs a session-expiry mechanism; Streamlit has no server-side session store |
| CONTEXT.md M1 | Diagnosis page still shows **global** `feature_importances_` labelled "Top Risk Factors" — should be a per-patient SHAP waterfall |
| CONTEXT.md L1 | ~650 lines of dead code still present (`page_help`, `page_admin_users`, shadowed `page_model_performance`, four `fix_*` scripts) |
| CONTEXT.md L3/L4 | No tests, no version control |
| Operating threshold | Now configurable, but still defaults to 0.5 — a screening tool would justify ~0.35–0.40 |

---
---

# RUN 4 — Evidence-based decision threshold (2026-07-27)

## 4.0 — The finding

The app classified at a hardcoded `0.50`. Measured on the holdout, that operating point **missed 31% of diseased patients**:

| Threshold | Sensitivity | Specificity | PPV | Missed per 1,000 |
|---|---:|---:|---:|---:|
| 0.30 | 0.880 | 0.488 | 0.627 | 59 |
| 0.35 | 0.831 | 0.584 | 0.662 | 84 |
| 0.40 | 0.781 | 0.668 | 0.697 | 108 |
| **0.50 (was in use)** | **0.692** | 0.773 | 0.749 | **152** |

**Why 0.50 was wrong here.** 0.50 is the default for a *balanced-accuracy* objective — it treats a false positive and a false negative as equally costly. This is a **screening** tool: it triages patients into further testing rather than diagnosing them. A false positive costs one follow-up appointment; a false negative sends home a patient with undetected cardiovascular disease. Those costs are wildly asymmetric, and 0.50 encoded the assumption that they are equal.

This was never a deliberate clinical decision. It was the default of `predict()`, inherited unexamined — and the System Settings page exposed it as a naked "Risk Threshold (%)" slider with no indication of what moving it would do, which is precisely how it stayed unexamined.

## 4.1 — What I did NOT do

**I did not hardcode 0.35.** Swapping one magic number for a better magic number leaves the same defect: a threshold nobody can justify, that does not adapt when the model is retrained, and that is identical across five models with different probability distributions.

The threshold is now **derived from the holdout ROC at training time**, per model, against an explicit clinical policy — and re-derived automatically on every retrain.

## 4.2 — Design

### Policy (declared in `train_models.py`, persisted in `thresholds.json`)

```python
SCREENING_TARGET_SENSITIVITY = 0.85   # action threshold - bound the miss rate
RULE_OUT_SENSITIVITY         = 0.95   # confident exclusion
RULE_IN_SPECIFICITY          = 0.90   # confident escalation
```

Three operating points are derived per model:

| Point | Rule | Clinical meaning |
|---|---|---|
| `rule_out` | highest threshold with sensitivity >= 0.95 | below this, disease confidently excluded |
| **`recommended`** | **highest threshold with sensitivity >= 0.85** | **the action threshold the app classifies at** |
| `rule_in` | lowest threshold with specificity >= 0.90 | above this, escalate directly |

Youden's J, F2-optimal and legacy-0.50 are also computed **for comparison**, so the choice is defensible rather than asserted.

### Why target-sensitivity rather than Youden's J

Youden maximises `sensitivity + specificity - 1`, which again weights both errors equally — the same flaw as 0.50, just relocated. Target-sensitivity encodes the actual clinical asymmetry: *bound the miss rate, then take the best specificity available subject to that bound.* Youden is still reported so a reviewer can see what the symmetric choice would have been.

## 4.3 — Derived operating points

| Model | Threshold | Sensitivity | Specificity | PPV | Missed/1k | Was @0.50 |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 0.360 | 0.850 | 0.537 | 0.642 | **74** | 161 |
| SVM | 0.361 | 0.850 | 0.539 | 0.644 | **74** | 160 |
| Decision Tree | 0.326 | 0.855 | 0.527 | 0.639 | **72** | 160 |
| Random Forest | 0.335 | 0.850 | 0.554 | 0.651 | **74** | 158 |
| XGBoost | 0.331 | 0.850 | 0.547 | 0.648 | **74** | 152 |
| **Ensemble Voting** (app default) | **0.348** | 0.850 | 0.556 | 0.652 | **74** | 157 |

**Miss rate more than halved: ~157 → 74 per 1,000.** Note the thresholds are *not* identical across models (0.326–0.361) — a single shared constant would have been wrong for four of the six.

## 4.4 — Tasks

### T20 — Threshold science in the training pipeline ✅

**Why.** The operating point must be a measured property of the model, not a constant in the UI layer.

**How.** Added to `train_models.py`: `_confusion_at`, `_threshold_for_sensitivity`, `_threshold_for_specificity`, `_youden_threshold`, `_fbeta_threshold`, `_net_benefit`, `_build_threshold_profile`. Each model gets a full profile — six candidate operating points, a 91-point sweep (0.05→0.95), risk-band edges, and a decision-curve net-benefit series.

**Verified.** `models/thresholds.json` written with six entries; profile embedded per model in `results.json`.

### T21 — Ensemble gets its own operating point ✅

**Why.** "Ensemble Voting" is the app's **default** model, but it is not a saved estimator — it is the mean of the five probabilities, with its own distribution. It had no derived threshold at all.

**How.** New Step 12 computes ensemble probabilities on the holdout and derives its profile. Stored as a virtual entry flagged `is_virtual: true`.

**Verified.** Ensemble threshold 0.348, sensitivity 0.850, AUC 0.8003.

### T22 — Reported metrics now describe actual behaviour ✅

**Why.** `accuracy`, `f1`, `precision`, `recall` and `conf_matrix` were computed via `model.predict()` — i.e. at 0.50 — while the app was about to classify at ~0.35. The Model Performance page would have described a decision rule the app no longer used.

**How.** `_evaluate()` derives the operating threshold first, then computes every threshold-dependent metric at it. Threshold-independent metrics (AUC, Brier, ECE, ROC, PR, reliability) are unchanged. `operating_threshold` is now an explicit field, and metrics at 0.50 are retained under `operating_points.legacy_half` for comparison.

**Note.** Reported accuracy *drops* (0.7330 → 0.6971 for XGBoost) because the model now trades specificity for sensitivity. **This is the correct trade for a screening tool** and should be presented as such — accuracy is the wrong headline metric here.

### T23 — App consumes derived, model-specific thresholds ✅

**How.** `load_thresholds()`, `get_risk_threshold(model_name)`, `get_risk_bands(model_name)`, `classify_risk_band(prob, model_name)`. Resolution order: SuperAdmin override → model-derived value → 0.5 fallback. Every model is scored at *its own* threshold.

### T24 — Four-tier risk bands replace binary HIGH/LOW ✅

**Why.** A bare HIGH/LOW verdict discards most of the information in a calibrated probability. Clinicians act differently at 12% and at 68%.

**How.** Bands derive from the same three operating points:

| Band | Range (Ensemble) | Action |
|---|---|---|
| Low | < 0.229 | Confidently excluded — routine review |
| Borderline | 0.229 – 0.348 | Below action threshold — lifestyle advice, re-assess |
| Intermediate | 0.348 – 0.700 | Above action threshold — further testing indicated |
| High | >= 0.700 | Escalate directly to clinical review |

### T25 — Operating point disclosed in UI and report ✅

**Why.** A clinician cannot calibrate their trust in a flag without knowing the operating point. Hiding it is how 0.50 survived.

**How.** The diagnosis result now shows threshold, sensitivity, specificity and PPV beneath the verdict, with a plain-language note that the tool is tuned for screening sensitivity. The downloadable report gained an `OPERATING POINT` section stating that a positive result indicates *need for further testing, not disease*.

### T26 — New Tab 9: Threshold & Clinical Utility ✅

**How.** Candidate operating-point table (six rows incl. legacy 0.50), sensitivity/specificity/PPV/NPV sweep chart with the operating point and legacy 0.50 marked, **decision-curve analysis** (net benefit vs treat-all/treat-none, per Vickers & Elkin 2006), risk-band table, and CSV export of the full sweep.

**Why decision curves.** They are the standard for justifying an operating point in clinical prediction literature — and give the dissertation a defensible answer to "why this threshold?"

### T27 — System Settings threshold governance ✅

**Why.** The old control was a naked percentage slider with no consequence shown.

**How.** Replaced with a dedicated panel: displays the model-derived recommendation and its full clinical profile; override is now opt-in via checkbox; when overriding, a **live readout** interpolates the sweep to show sensitivity/specificity/PPV and missed-per-1,000 for the chosen value, plus the delta against the recommendation. Default `risk_threshold` changed from `0.50` to `None`, meaning *follow the model* — so retraining updates the operating point automatically instead of being silently overridden by a stale constant.

### T28 — Bands track the override ✅ *(inconsistency caught during verification)*

**Found by** the functional hunt: overriding the threshold to 0.05 changed the binary verdict but **not** the band, so the UI could show "LOW RISK" for a patient the system had just flagged positive.

**How.** `get_risk_bands()` now shifts the middle boundary to the active threshold and clamps the outer bands to preserve ordering.

**Verified.** Same patient: derived 0.348 → *Low*; override 0.05 → *Intermediate*; override 0.95 → *Low*. Verdict and band agree in all three.

### T29 — Regression fix: virtual ensemble broke tabs 1–8 ✅ *(self-inflicted, caught in verification)*

**Cause.** The new virtual `Ensemble Voting` entry has no `conf_matrix` / `report` / `roc_curve` / `kfold_cv`, but `page_model_performance` iterates every key in `results.json`. All three roles crashed with `KeyError: 'conf_matrix'`.

**Fix.** `load_results()` / `_load_results()` now exclude `is_virtual` entries by default; only Tab 9 passes `include_virtual=True`.

**Lesson.** Adding a differently-shaped record to a shared collection breaks every consumer that assumed uniformity. The verification sweep caught it in one run.

## 4.5 — Verification

```
27/27 page x role paths          0 exceptions
Diagnosis form submitted E2E     verdict + band + operating point render
Threshold override 0.05 / 0.95   band and verdict stay consistent
Empty database                   no crashes
SHAP tab                         0 st.error
py_compile / pyflakes            clean
```

## 4.6 — Summary

| | Before | After |
|---|---|---|
| Threshold source | hardcoded `0.50` | derived per model from holdout ROC |
| Sensitivity (ensemble) | 0.692 | **0.850** |
| **Missed cases per 1,000** | **157** | **74** |
| Specificity (ensemble) | 0.773 | 0.556 |
| Output granularity | binary HIGH/LOW | 4-tier risk bands |
| Operating point visibility | hidden | shown in UI, report, and a dedicated tab |
| Justification | none | decision-curve analysis + 6 candidate points |
| On retrain | stale constant persisted | threshold re-derived automatically |

**The trade.** Specificity falls from 0.773 to 0.556 — roughly 22 additional false positives per 100 healthy patients, each costing a follow-up assessment. In exchange, 83 fewer diseased patients per 1,000 are sent home undetected. For a screening instrument that is the correct direction, and it is now an explicit, documented, adjustable clinical policy rather than an accident of the classifier's default.

## 4.7 — Carried forward

| Item | Note |
|---|---|
| Threshold derived on the holdout | Ideally use a dedicated validation split so the reported operating point is not selected on the same data it is scored on. Low practical impact at n=13,729, but methodologically cleaner |
| Subgroup-specific thresholds | AUC varies 0.65–0.84 across age and cholesterol strata; a single global threshold is a compromise |
| Cost-sensitive threshold | Target-sensitivity is a proxy. Explicit FP/FN cost ratios from clinical literature would be more rigorous |
| `max_predictions_per_day`, `session_timeout_min` | Still unenforced (Run 3 §3.5) |
| Per-patient SHAP on diagnosis page | Still global importance (CONTEXT.md M1) |

---
---

# RUN 5 — Subgroup performance & fairness (2026-07-27)

## 5.0 — The finding

| Subgroup | n | Prevalence | AUC |
|---|---:|---:|---:|
| Overall | 13,729 | 0.495 | 0.8000 |
| age < 45 | 2,015 | 0.283 | 0.8361 |
| age 55–60 | 3,167 | 0.568 | 0.7307 |
| age 60+ | 3,085 | 0.653 | 0.7349 |
| cholesterol normal | 10,310 | 0.435 | 0.7891 |
| cholesterol well above | 1,570 | 0.764 | **0.6494** |

Discrimination collapsed to 0.65 in the highest-risk cholesterol group and 0.73 in the 55+ cohort — and **only the aggregate was reported**, so nobody would know.

## 5.1 — Diagnosis before treatment

The obvious response — "build better models for the weak subgroups" — would have been **wrong**. I tested it first.

### Test 1: is the drop statistically real?

Bootstrap 95% CIs per stratum:

| Subgroup | AUC | 95% CI | Overlaps 0.80? |
|---|---:|---|---|
| Overall | 0.8000 | [0.7939, 0.8075] | — |
| age < 45 | 0.8361 | [0.8139, 0.8562] | No (higher) |
| age 55–60 | 0.7307 | [0.7134, 0.7477] | **No (lower)** |
| age 60+ | 0.7349 | [0.7172, 0.7539] | **No (lower)** |
| chol well above | 0.6494 | [0.6164, 0.6797] | **No (lower)** |

Real, not noise.

### Test 2: is it model weakness, or range restriction?

Trained a specialist model on each weak stratum alone and compared it to the global model on the same holdout rows:

| Stratum | n_train | Global AUC | Specialist AUC | Δ |
|---|---:|---:|---:|---:|
| age < 45 | 7,880 | 0.8361 | 0.8145 | **−0.0216** |
| age 55–60 | 12,569 | 0.7307 | 0.7177 | **−0.0131** |
| age 60+ | 12,334 | 0.7349 | 0.7321 | −0.0028 |
| chol normal | 41,165 | 0.7891 | 0.7893 | +0.0002 |
| chol well above | 6,298 | 0.6494 | 0.6161 | **−0.0333** |

**Specialist models are worse in every case.** The global model is already the best available estimator for each stratum.

**Conclusion: the AUC drop is RANGE RESTRICTION, not model weakness.** Stratifying on a strong predictor removes that predictor's variance from within the stratum, so ranking inside a homogeneous group is inherently harder. Within-stratum AUC is simply not comparable to overall AUC — the overall figure benefits from *between*-stratum separation that no longer exists once you condition on age or cholesterol.

### Test 3: is calibration also degraded?

| Subgroup | Mean predicted | Actual | Gap |
|---|---:|---:|---:|
| Overall | 0.495 | 0.495 | −0.000 |
| age < 45 | 0.281 | 0.283 | −0.003 |
| age 55–60 | 0.556 | 0.568 | −0.013 |
| age 60+ | 0.648 | 0.653 | −0.005 |
| chol normal | 0.437 | 0.435 | +0.002 |
| chol well above | 0.757 | 0.764 | −0.007 |

**Calibration holds everywhere** — every gap under 0.02, including in the AUC-0.65 stratum. For a risk *score*, this is the property that matters: the probability means what it says regardless of patient type.

### Test 4: so where is the actual harm?

Operating characteristics per subgroup at the single global threshold of 0.348:

| Subgroup | Prevalence | Sensitivity | Specificity | Flagged |
|---|---:|---:|---:|---:|
| age < 45 | 0.283 | **0.634** | 0.909 | 24.5% |
| age 45–55 | 0.440 | 0.743 | 0.694 | 49.9% |
| age 55–60 | 0.568 | 0.917 | 0.228 | 85.4% |
| age 60+ | 0.653 | 0.979 | **0.106** | **95.0%** |
| chol well above | 0.764 | 0.997 | **0.049** | **98.6%** |

**Found it.** A single cut-point applied to strata whose baseline risk ranges 28%→76% produces:

- **Under-45s: 63.4% sensitivity** — missing 37% of diseased young patients, despite a stated 85% target
- **Over-60s: 10.6% specificity, 95% flagged** — the model says "yes" to almost everyone; worthless as triage
- **High cholesterol: 4.9% specificity, 98.6% flagged** — no discriminative value at all in practice

That is **unequal care**, and it is a threshold problem, not a modelling problem.

## 5.2 — The fix

Age-stratified operating points, each derived to achieve the target sensitivity *within its band*.

**Why age is the stratification variable.** Baseline cardiovascular risk rises steeply with age, and every established risk instrument — Framingham, SCORE2, QRISK3 — is age-stratified for that reason. Other dimensions (sex, cholesterol, BMI, glucose, smoking) are **measured and reported** but do not get separate thresholds: splitting on several variables at once fragments the data faster than it buys accuracy.

### Result

| Age band | n | Prevalence | Threshold | Sensitivity | Specificity | Flagged | *Sens under global* |
|---|---:|---:|---:|---:|---:|---:|---:|
| Under 45 | 2,015 | 0.283 | **0.182** | 0.835 | 0.601 | 52.3% | *0.639* |
| 45–54 | 5,462 | 0.440 | **0.287** | 0.853 | 0.464 | 67.6% | *0.752* |
| 55–59 | 3,167 | 0.568 | **0.371** | 0.837 | 0.375 | 74.6% | *0.930* |
| 60 and over | 3,085 | 0.653 | **0.486** | 0.839 | 0.426 | 74.7% | *0.980* |

- **Sensitivity equalised at 0.835–0.853** across every band (was 0.639–0.980) — the **equal opportunity** fairness criterion
- **Over-60 specificity: 0.106 → 0.426**; flagged rate 95.0% → 74.7%. Usable as triage again
- **Under-45 sensitivity: 0.639 → 0.835**. 20 percentage points more diseased young patients caught

## 5.3 — Tasks

### T30 — Shared subgroup definitions ✅

**Why.** Training needs strata to measure and stratify on; the app needs the same strata to tell a clinician which one the patient is in. Two implementations would drift, exactly as the feature logic did before Run 3.

**How.** Added to `feature_engineering.py`: `AGE_BANDS`, `age_band_index()`, `age_band_label()`, `BMI_CLASSES`, `bmi_class_label()`, `assign_subgroups(df)` (six reported dimensions), `MIN_SUBGROUP_N = 200`.

### T31 — Thresholds derived out-of-fold, not on the holdout ✅ *(closes the Run 4 caveat)*

**Why.** Run 4 selected operating points on the same holdout it then reported them on — optimistic, and I logged it as carried-forward work. It is now fixed rather than left standing.

**How.** New Step 10 generates out-of-fold probabilities via `cross_val_predict` (5-fold, per model). Thresholds are chosen on OOF training predictions; performance is then **measured on the untouched holdout** and stored as `holdout_at_operating_point`. `profile["derived_from"]` records which source was used.

**Effect.** Ensemble threshold shifted 0.348 → 0.340, and the honest holdout sensitivity is 0.857 (slightly above target, as expected when the threshold is picked on independent data). Training time 30s → 57s — worth it.

### T32 — Subgroup analysis with confidence intervals ✅

**Why.** A point estimate per stratum invites over-reading noise in a 1,570-patient cell.

**How.** `_bootstrap_auc_ci()` (300 resamples) and `_subgroup_report()`, which records per level: n, prevalence, AUC + 95% CI, Brier, ECE, mean predicted, calibration gap, and the operating characteristics **at the threshold the app would actually apply** — not a hypothetical shared cut-point. Six dimensions; strata under 200 patients are suppressed as unreportable.

### T33 — Age-stratified operating points ✅

**How.** `_stratified_thresholds()` derives one threshold per band from OOF predictions. Persisted to `models/thresholds.json` under `stratified`, with a `stratification` block recording the variable, the bands, and the clinical rationale.

### T34 — Diagnosis page applies the band threshold and discloses reliability ✅

**Why.** This is the actual fix for *"nobody would know."*

**How.** `get_stratified_threshold(model, age)` and `patient_subgroup_reliability(age, model)`. Every model is scored at its own band-specific point. The result panel now shows: age band, discrimination rated **Strong / Moderate / Limited** with AUC and CI, calibration gap, holdout n, and the band-specific sensitivity/specificity/PPV. When band AUC < 0.75 an explicit caution appears — *"the model discriminates less well in this age band; weight clinical judgement more heavily than the score."*

**Verified.**

| Patient age | Threshold applied | Band AUC shown | Rating | Caution shown |
|---|---:|---:|---|---|
| 30 | 0.182 | 0.838 | Strong | No |
| 50 | 0.287 | 0.785 | Moderate | No |
| 57 | 0.371 | 0.730 | Limited | **Yes** |
| 68 | 0.486 | 0.733 | Limited | **Yes** |

### T35 — Risk bands track the stratified threshold ✅

**Why.** Run 4's T28 made bands follow the SuperAdmin override. With per-age thresholds there is now a third source of truth, and the same contradiction would have reappeared.

**How.** `get_risk_bands()` / `classify_risk_band()` take an `active_threshold` argument; the diagnosis page passes the resolved band threshold. Verdict and band cannot disagree.

### T36 — New Tab 10: Subgroup Performance & Fairness ✅

**How.** A "how to read this" panel stating the three findings plainly (calibration holds / within-stratum AUC drop is expected range restriction / the real defect was the shared threshold); the stratified operating points in force with measured performance; a per-dimension selector with the full table incl. CIs; an AUC-with-error-bars chart colour-coded by strength against the overall reference line; a calibration-gap chart with the ±0.02 acceptable zone shaded; and CSV export of the whole report.

**Why it matters most.** The original defect was not the numbers — it was that the numbers were invisible. This tab makes subgroup weakness impossible to ship unnoticed again.

### T37 — Report includes stratified operating point and reliability ✅

**How.** The downloadable report gained `OPERATING POINT (age-stratified)` and `MODEL RELIABILITY FOR THIS PATIENT GROUP` sections, with AUC + CI, calibration gap, holdout n, and a plain-language note on why the threshold is age-stratified.

## 5.4 — Verification

```
27/27 page x role paths           0 exceptions
Stratified thresholds per age     0.182 / 0.287 / 0.371 / 0.486 applied correctly
Subgroup AUC surfaced per patient 0.838 / 0.785 / 0.730 / 0.733
Low-reliability caution           fires only when band AUC < 0.75
Verdict/band consistency          holds under stratified + override thresholds
py_compile / pyflakes             clean
```

## 5.5 — Summary

| | Before | After |
|---|---|---|
| Subgroup performance | unmeasured, unreported | 6 dimensions, AUC + 95% CI + calibration + operating chars |
| Threshold | one global value | age-stratified, 4 bands |
| Threshold derivation | holdout (optimistic) | out-of-fold training predictions |
| **Sensitivity spread across ages** | **0.639 – 0.980** | **0.835 – 0.853** |
| Over-60 specificity | 0.106 (flagged 95%) | **0.426** (flagged 75%) |
| Under-45 sensitivity | 0.639 | **0.835** |
| Clinician sees reliability | no | rated Strong/Moderate/Limited per patient, with caution flag |
| Fairness evidence | none | equal-opportunity table + fairness tab + CSV export |

## 5.6 — What I deliberately did NOT do

| Rejected | Why |
|---|---|
| Specialist models per stratum | **Measured worse** in every case (−0.033 to +0.000). The ceiling is the data |
| Cholesterol/BMI-stratified thresholds | Multi-way stratification fragments the data faster than it buys accuracy. Measured and reported instead |
| "Improving" the 0.65 cholesterol AUC | It is range restriction. Calibration there is fine (gap −0.007) and the score remains usable |
| Reporting subgroup AUC without CIs | A 1,570-patient cell has a ±0.03 interval; a bare point estimate invites over-reading |

## 5.7 — Carried forward

| Item | Note |
|---|---|
| Sex, cholesterol, BMI thresholds | Reported but not stratified. Revisit if deployed to a skewed population |
| Intersectional subgroups | e.g. older women with high cholesterol — cells fall below MIN_SUBGROUP_N on this data |
| Prospective fairness monitoring | Needs the outcome-feedback loop (gap analysis §3) before drift can be detected |
| `max_predictions_per_day`, `session_timeout_min` | Still unenforced (Run 3 §3.5) |
| Per-patient SHAP on diagnosis page | Still global importance (CONTEXT.md M1) |

---
---

# RUN 6 — Clinical benchmark & the dataset ceiling (2026-07-27)

## 6.0 — Two linked findings

**Finding A — the ceiling is the data, not the algorithm.** Feature ablation showed blood pressure accounting for the large majority of achievable discrimination, and self-reported lifestyle fields contributing +0.002. The claim "more tuning buys ~0.005, more features buy 0.05+" was asserted but unproven.

**Finding B — AUC 0.80 had no reference point.** A clinician's first question is not "how accurate?" but "better than what I already use?" Unanswered, 0.80 is uninterpretable.

These are the same problem seen from two directions: without a baseline you cannot tell whether 0.80 is good, and without a ceiling analysis you cannot tell whether chasing 0.81 is worth anything.

## 6.1 — Finding B: the clinical benchmark

### Implementation

New module `clinical_baselines.py` with three comparators, deliberately spanning the range of what "existing practice" means:

| Comparator | What it represents |
|---|---|
| `bp_staging_score` | ACC/AHA 2017 blood-pressure category. What a nurse does with a cuff alone |
| `framingham_proxy` | Framingham 2008 General CVD equation (D'Agostino et al., *Circulation*) |
| `fit_clinical_logistic` | Logistic regression on the 7 classic risk factors — **the fair comparison** |

### Results (same holdout, n = 13,729)

| Model | AUC | ML advantage | 95% CI | Significant |
|---|---:|---:|---|---|
| **HeartGuard ML ensemble** | **0.8003** | — | — | — |
| Clinical logistic regression | 0.7912 | **+0.0092** | +0.0075 to +0.0109 | Yes |
| BP staging rule (ACC/AHA) | 0.7221 | +0.0782 | +0.0725 to +0.0836 | Yes |
| Framingham 2008 (proxy) | 0.7060 | +0.0944 | +0.0876 to +0.1017 | Yes |

Differences tested with a **paired** bootstrap (500 resamples of patients, not predictions). Pairing matters: two overlapping independent CIs can still correspond to a highly significant paired difference, because it preserves the correlation between the two models' errors.

### The honest headline

> The ML ensemble significantly outperforms every clinical comparator — but gains only **+0.009 AUC over conventional logistic regression on the same risk factors**.

That is a more defensible and more interesting sentence than "we beat Framingham," because:

- The +0.094 margin over Framingham is **inflated by the proxy's handicaps** (below). Quoting it unqualified would be misleading.
- The +0.009 margin over clinical logistic regression is the **method-attributable** difference — identical inputs, identical missing lipids, identical outcome.
- **A blood-pressure cuff alone reaches 0.7221** — 90% of the way to the full ML ensemble. That deserves to be reported, not buried.

### Caveats, recorded in code and surfaced in the UI

The Framingham implementation is a **proxy, not the validated instrument**. Two required inputs are absent:

| Missing input | Substitution | Effect |
|---|---|---|
| Total cholesterol (mg/dL) | Ordinal category → band midpoint (180 / 220 / 260) | Within-band variance lost |
| HDL cholesterol | Sex-specific population means (44 / 55) | Constant within sex → contributes **zero** discriminative information |

Both **handicap** the proxy, so the ML margin against it is an **upper bound**. A third mismatch applies to all baselines: Framingham and SCORE2 estimate 10-year **incident** risk, whereas this dataset's target is **prevalent** disease at examination. Rank comparisons remain valid; absolute risk values do not transfer, and are not presented as if they did.

## 6.2 — Finding A: proving the ceiling

### Proof 1 — incremental feature value

Feature groups added in clinical acquisition order, each rung fitted with the deployed model family:

| Acquisition step | #Features | AUC | Marginal gain |
|---|---:|---:|---:|
| Demographics only | 3 | 0.6429 | — |
| **+ Blood pressure** | 6 | **0.7851** | **+0.1422** |
| + Body metrics | 9 | 0.7873 | +0.0022 |
| + Cholesterol & glucose | 12 | 0.7985 | +0.0111 |
| + Lifestyle (all 15) | 15 | 0.8001 | +0.0016 |

**Blood pressure alone delivers +0.142 of the +0.157 total gain — 90%.** Everything after the BP cuff contributes +0.015 combined. Self-reported smoking, alcohol and activity contribute +0.0016.

### Proof 2 — hyperparameter search does not help

40-trial randomised search over 8 XGBoost hyperparameters (n_estimators, max_depth, learning_rate, subsample, colsample_bytree, min_child_weight, reg_lambda, gamma), 3-fold CV on the training split:

| | AUC |
|---|---:|
| Shipped hand-picked hyperparameters | 0.80005 |
| Best of 40 random trials | 0.80241 |
| **Gain** | **+0.0024** |
| Search time | 104s |

The bootstrap CI on a single AUC estimate is roughly ±0.007 wide. **A +0.0024 gain is not distinguishable from noise.**

**Decision: shipped hyperparameters retained.** Reproducibility and stability are worth more than a gain inside the noise floor. The search is preserved as a callable (`train_models.tune()`) with its result cached to `models/tuning_result.json`, so the claim can be re-verified rather than taken on trust — and revisited if the feature set ever changes.

### Proof 3 — interaction terms do not help

Six clinically motivated interactions added (`age×SBP`, `bmi×SBP`, `chol×SBP`, `age×chol`, `metabolic_burden`, mean arterial pressure):

| Model family | Base | + Interactions | Δ |
|---|---:|---:|---:|
| Tree (XGBoost) | 0.8001 | 0.7997 | **−0.0003** |
| Linear (LogReg) | 0.7920 | 0.7963 | +0.0043 |

This is the informative pair. Trees already represent interactions implicitly, so the **null result there means the functional form is saturated**. The linear gain merely confirms the interactions are real — it brings logistic regression closer to the trees without exceeding them. Neither raises the ceiling.

**Conclusion: performance is bounded informationally, not functionally.** Three independent lines of evidence agree.

### What would actually help

Recorded in `benchmarks.json` and displayed in the UI, in descending expected value:

1. **HDL and LDL cholesterol as continuous values** (currently a 3-level ordinal)
2. **Confirmed diabetes status** (currently proxied by ordinal glucose)
3. **Family history** of premature cardiovascular disease
4. **Antihypertensive / lipid-lowering medication status**
5. **Objective activity measurement** (self-reported adds +0.002)

## 6.3 — Tasks

### T38 — `clinical_baselines.py` ✅

**Why.** Comparators must be reproducible code with their assumptions written down, not numbers quoted from a paper.

**How.** New module: `bp_staging_score()`, `framingham_proxy()` (full 2008 coefficients for both sexes), `fit_clinical_logistic()`, `FEATURE_LADDER`, `interaction_features()`, `paired_auc_difference()`. Substitutions and their direction of bias are documented in the module docstring and repeated in `benchmarks.json`, so the caveat cannot be separated from the number.

### T39 — Paired bootstrap significance testing ✅

**Why.** Comparing two independent confidence intervals is not a test of difference.

**How.** `paired_auc_difference()` resamples **patients**, recomputing both AUCs on the same resample, preserving error correlation. Returns the observed difference, its 95% CI, a two-sided bootstrap p-value, and a significance flag.

### T40 — Benchmark & ablation built into the pipeline ✅

**How.** Three new training steps:
- **Step 15** `_baseline_benchmark()` — ML vs all three comparators with paired tests
- **Step 16** `_incremental_value_analysis()` — the feature ladder with per-rung CIs and paired tests against the previous rung
- **Step 17** `_interaction_test()` — tree and linear families, base vs augmented

All persisted to `models/benchmarks.json` alongside the interpretation, caveats and data roadmap. **The framing now travels with the numbers** instead of living only in a report a reader may not have.

### T41 — Hyperparameter search as verifiable evidence ✅

**How.** `run_hyperparameter_search()` plus a standalone `tune()` entry point, cached to `models/tuning_result.json` and folded into `benchmarks.json`. Deliberately **not** part of normal training — it costs 104s to demonstrate a gain inside the noise floor.

### T42 — New Tab 11: Clinical Benchmark & Feature Value ✅

**How.** Headline and ceiling statements; the benchmark table with AUC, CIs, paired advantage and significance; a callout isolating the fair comparison; an expander with comparator definitions and caveats; a horizontal AUC comparison chart; the incremental-value table and a step chart annotating each marginal gain (large gains in red); side-by-side hyperparameter-search and interaction-test evidence; the ranked data roadmap; and JSON export.

**Why it matters.** The finding was not that the ceiling exists — it is that nothing in the product said so. A reader saw "0.80" with no reference point and no indication that further tuning was pointless. Both are now first-class UI.

## 6.4 — Verification

```
27/27 page x role paths           0 exceptions
Tab 11 content rendered           benchmark / Framingham / BP rule / fair-comparison
                                  callout / incremental value / ceiling evidence /
                                  data roadmap  — all present
st.error on Model Performance     0
py_compile / pyflakes             clean
```

## 6.5 — Summary

| | Before | After |
|---|---|---|
| Clinical reference point | none | 3 comparators, paired-tested |
| "Better than practice?" | unanswered | +0.009 vs clinical LR · +0.078 vs BP rule · +0.094 vs Framingham proxy |
| Significance testing | none | paired bootstrap, 400–500 resamples |
| Ceiling claim | asserted | **proven** three ways (ablation, tuning, interactions) |
| Tuning gain | unknown | measured: +0.0024, inside noise |
| Interaction gain | unknown | measured: −0.0003 on trees |
| Feature roadmap | none | 5 ranked additions in UI + JSON |
| Caveats | verbal | in code, in JSON, in UI |

## 6.6 — What I deliberately did NOT do

| Rejected | Why |
|---|---|
| Adopt the tuned hyperparameters | +0.0024 sits inside the ±0.007 noise floor. Reproducibility is worth more than a gain that cannot be distinguished from chance |
| Claim "we beat Framingham" unqualified | The proxy is handicapped by missing lipids. Reporting +0.094 without that caveat would be misleading |
| Implement SCORE2 | Requires the same absent lipid panel. A second handicapped proxy adds no information over the first |
| Run tuning on every retrain | 104s to re-demonstrate a null result. Cached instead, re-runnable on demand |
| Add interaction terms to the shipped model | Measured −0.0003 on trees. Complexity for nothing |

## 6.7 — Carried forward

| Item | Note |
|---|---|
| Real lipid panel (HDL/LDL) | The single highest-value data addition. Would also allow a faithful, non-proxy Framingham/SCORE2 comparison |
| External validation | A second cohort would test whether 0.80 transfers. Currently one dataset, one split |
| Incident vs prevalent outcome | Framingham comparison is inherently approximate until an incident-outcome cohort is available |
| `max_predictions_per_day`, `session_timeout_min` | Still unenforced (Run 3 §3.5) |
| Per-patient SHAP on diagnosis page | Still global importance (CONTEXT.md M1) |

---
---

# RUN 7 — Applicability guard, patient entity, monotonicity (2026-07-27)

> **Status: BUG-23 complete.** Several supporting capabilities landed alongside it
> (patient entity, outcome capture, model versioning, units, monotonic constraints).
> Items still pending are listed in §7.9 — they are unfinished wiring, not defects.

## 7.0 — BUG-23: no applicability guard

| Feature | Training range | Form accepted |
|---|---|---|
| **age** | **30 – 65** | **1 – 120** |
| ap_lo | 40 – 182 | 40 – 200 |
| ap_hi | 60 – 240 | 60 – 250 |
| weight | 21 – 200 | 20 – 200 |

An **82-year-old cardiology patient** — entirely plausible, arguably the archetypal user of a cardiovascular risk tool — received a confident risk probability, an age-stratified operating point, a peer percentile and a four-tier risk band from a model that had **never seen anyone over 65**. Nothing in the UI, the report or the database indicated extrapolation. The same applied to a 19-year-old, and to a hypertensive crisis at 245/195.

**Why this is severe.** Every other safeguard built in Runs 4–6 silently assumed the patient was inside the training population. The age-stratified threshold for "60 and over" was derived from patients aged 60–65 and was being applied to an 82-year-old. The peer percentile ranked them against 60–65 year-olds and could report them as "typical". The risk band, the sensitivity figure, the reliability panel — all presented with full confidence, none of it valid. A risk estimate is only as good as the population it was estimated on, and that scope was never stated anywhere.

## 7.1 — How it was found

Not by reading the code. By writing a test that exercised previously-unrun paths with deliberately adversarial inputs (`risk_percentile` at age 8 and age 120), noticing the function returned a confident percentile for both, then comparing the form's accepted bounds against the training data's actual bounds.

The lesson: the guard's absence was invisible from inside any single function. Every component behaved correctly given its inputs. Only the *composition* was unsafe.

## 7.2 — The fix

Four layers, because a warning alone is not a guard.

### Layer 1 — Measure and persist the envelope

`train_models.py` Step 18 now emits `models/input_ranges.json`: per-feature min, max, 1st and 99th percentile, mean and cardinality, computed on the training corpus.

```
Applicability envelope -> models/input_ranges.json
  age support: 30-65 years (p1-p99: 40-64)
```

### Layer 2 — Classify, with two severities

`clinical_ui.check_applicability(inputs)` returns per-field warnings:

| Severity | Meaning | Consequence |
|---|---|---|
| `hard` | outside observed min/max | genuine extrapolation — score is not validated |
| `soft` | inside min/max but beyond p1–p99 | sparse support — usable, less certain |

Checks `age`, `ap_hi`, `ap_lo`, `weight`, `height` and derived `bmi`.

### Layer 3 — Prevent, then warn

**Prevent:** every numeric input carries a `help` tooltip stating its supported range, and a **"Model applicability — who this model is valid for"** expander sits above the submit button showing the full envelope table. The clinician sees the limit *before* submitting.

Values are deliberately **not clamped** to the envelope. A real 82-year-old must be enterable — refusing to accept the patient would be worse than scoring them with a warning. The score is produced, then labelled.

**Warn:** on hard extrapolation a red-bordered banner renders **above the verdict**, listing each offending value against its supported range. Placement is deliberate: if the model is extrapolating, that is the most important thing on the screen, and it must be read before a number that looks authoritative.

The risk band itself is suffixed `(EXTRAPOLATED)`.

### Layer 4 — Withhold what is genuinely invalid

The **peer percentile is suppressed** under hard extrapolation. This is not decoration: `risk_percentile` does a `searchsorted` against an age × sex reference distribution. For an 82-year-old there is no such stratum, so the fallback silently ranked them against 60–65 year-olds — potentially reporting an 82-year-old as "typical for their group" when no such group exists in the model. Withheld rather than approximated.

The reliability panel, the operating point and the score remain visible, because those are still meaningful *with* the caveat.

### Persistence and reporting

New columns `extrapolated` and `applicability_notes` on `predictions`, via additive migration. A reviewer auditing a past decision must be able to see the prediction was made outside the supported population — a screen warning that vanishes on reload is not an audit trail.

The text report gains a `*** WARNING - OUTSIDE MODEL APPLICABILITY ***` block above the operating point, listing each violation, plus the model version and the peer-comparison status.

## 7.3 — A bug in my own fix, caught by strengthening the test

The first version of the end-to-end test asserted only on **rendered UI strings**. All five cases passed:

```
[ok ] 82yo — above age support    banner=True  peer_withheld=True
```

But inspecting the database showed:

```
age= 82 sbp=150 extrapolated=0 ... |            <- flag NOT persisted
age= 55 sbp=245 extrapolated=0 ... |            <- flag NOT persisted
```

**Cause.** I added `extrapolated` and `applicability_notes` to `add_prediction`'s *signature* but never to the `INSERT` column list or values tuple. Python accepted the keyword arguments and silently discarded them. The UI warned correctly; the audit trail — the entire point of the column — recorded nothing.

**Fixed** the INSERT, then rewrote the test to assert on database contents rather than screen text. Now:

```
age= 82 extrapolated=1 | Age=82 outside 30-65 (hard)
age= 19 extrapolated=1 | Age=19 outside 30-65 (hard)
age= 55 extrapolated=1 | Systolic BP=245 outside 60-240 (hard); Diastolic BP=195 outside...
age= 52 extrapolated=0 |
age= 64 extrapolated=0 |
```

**Lesson recorded:** a test that checks what the user sees is not a test that the system recorded it. Assert on the durable state, not the rendering.

## 7.4 — Verification

End-to-end through the real Streamlit UI, five patient profiles:

| Patient | Banner | `(EXTRAPOLATED)` tag | Peer shown | Peer withheld | DB flag |
|---|---|---|---|---|---|
| 82yo | ✅ | ✅ | — | ✅ | `1` + reason |
| 19yo | ✅ | ✅ | — | ✅ | `1` + reason |
| 55yo, BP 245/195 | ✅ | ✅ | — | ✅ | `1` + 2 reasons |
| 52yo typical | — | — | ✅ | — | `0` |
| 64yo (near p99) | — | — | ✅ | — | `0` |

```
27/27 page x role paths     0 exceptions
24 new-code probes          0 failures
5 OOD scenarios + DB        0 failures
py_compile / pyflakes       clean
```

## 7.5 — Supporting work completed in this run

### T43 — Patient entity ✅
`predictions` previously conflated an **event** with a **person**: the only identity was free-text name per row, so the same patient assessed twice produced two unrelated records. Cardiovascular risk management is inherently longitudinal. New `patients` table with unique `patient_code`; `upsert_patient()` attaches repeat visits to the same person; `get_patient_timeline()` returns the trajectory. Verified idempotent on repeat codes.

### T44 — Model version per prediction ✅
`model_used` stored `"Ensemble Voting"` — a label, not a version. After one retrain every historical prediction became unexplainable. Now records `model_version` (training timestamp) and `model_manifest_sha` (dataset digest), plus `threshold_used` and `risk_band`, since thresholds are age-stratified and configurable so a probability alone no longer reconstructs the decision.

### T45 — Outcome capture + drift monitoring ✅
`record_outcome()` and `get_outcome_stats()`. One field — "was this confirmed?" — is what makes deployed performance measurable rather than assumed. Returns raw counts alongside rates and a `reliable` flag (n ≥ 30), because with few outcomes the rates are noise and the caller must know that.

### T46 — GDPR erasure ✅
`delete_patient()` removes the identity and scrubs `patient_name` to `[erased]` while retaining the anonymised clinical record. Verified.

### T47 — Clinical units (mg/dL ↔ mmol/L) ✅
Hardcoded mg/dL made the tool unusable across Europe/UK/Australia and invited misreading of boundary values. `ordinal_labels_with_units()` annotates each ordinal level with its clinical range in the chosen unit (cholesterol `< 5.17 mmol/L` / `5.17–6.21` / `≥ 6.21`; glucose `< 5.5` / `5.5–7.0` / `≥ 7.0`). The ordinal model input is untouched — only labels change. Unknown units fall back to bare labels rather than guessing.

### T48 — Monotonic clinical constraints ✅ *(significant safety fix)*

Probing the model revealed it was **not monotonic in blood pressure**: a systolic sweep 100→200 mmHg produced **6 inversions in 20 steps**, i.e. the model implied +5 mmHg could *reduce* risk across ~30% of the range. Tolerable for pure ranking; unacceptable once a counterfactual simulator turns those gradients into care advice.

Measured the cost of constraining:

| Model | Unconstrained AUC | Constrained AUC | Unconstrained ECE | Constrained ECE |
|---|---:|---:|---:|---:|
| **XGBoost** | 0.8000 | **0.7999** | 0.0103 | **0.0103** |
| Random Forest | 0.8000 | 0.7890 | 0.0110 | **0.0934** |
| Decision Tree | 0.7933 | 0.7841 | 0.0144 | — |

**Decision: constrain XGBoost only.** There it is free (−0.0001 AUC, 0 inversions). scikit-learn's `monotonic_cst` on Random Forest cost 0.011 AUC and inflated calibration error **8.5×** — calibration is this system's most valuable property and is not tradeable for tidiness. RF and DT stay unconstrained; XGBoost becomes the clinically coherent model and is flagged `monotonic: true` in `results.json`.

Confirmed the constraint is what fixes counterfactual coherence:

| Engine | Paradoxical recommendations |
|---|---:|
| Ensemble (4 unconstrained members) | **3** |
| Monotonic XGBoost only | **0** |

### T49 — AUC-weighted ensemble ✅
Replaced the unweighted mean with weights proportional to OOF skill above chance. **Honest result: +0.0001 AUC.** All five members sit within 0.009 AUC of each other, so weights are near-uniform (0.198–0.204). Principled but negligible on this data — recorded as such rather than presented as an improvement.

### T50 — Bootstrap CIs on headline metrics ✅
Every model's `results.json` entry now carries `auc_ci_low` / `auc_ci_high`. e.g. Random Forest `0.8000 [0.7925, 0.8072]`. A bare point estimate invites over-reading.

### T51 — Population percentile distributions ✅
`models/risk_distribution.json` with 8 age × sex strata plus a cohort fallback. Peer-relative rather than cohort-relative because age dominates absolute risk — comparing a 68-year-old against the whole cohort says almost nothing about whether they are unusual *for their age*.

### T52 — Counterfactual engine, with two clinical-safety fixes ✅

Built `standard_scenarios()` / `counterfactual_table()`, then found and fixed two defects that would have produced harmful advice:

**(a) "Lower your diastolic BP" reported risk INCREASING (+2.9%).** Dropping `ap_lo` 96→80 while holding systolic at 158 widens pulse pressure 62→78, which the model correctly reads as higher risk. The model was right; **my scenario was fiction** — no antihypertensive lowers diastolic alone. Scenarios now target recognised BP *pairs* (140/85, 130/80, 120/75).

**(b) "Lose 5 kg" reported +1.0%.** Sub-noise wobble presented as advice. Changes below `NEGLIGIBLE_DELTA = 1.5%` are now labelled "no material change" rather than given a direction, and genuinely paradoxical results are flagged as model limitations — never as recommendations.

Also fixed: the combined scenario merged mutually-exclusive BP targets, so "ALL 3 combined" silently applied only the last one. Now keeps the single best override per field-set.

### T53 — Per-patient SHAP + PDF reporting (built, pending UI wiring) ✅ code / ⏳ wiring
`explain_patient()` produces true per-patient SHAP (fixes the long-standing M1 defect where global `feature_importances_` was captioned as patient-specific reasoning); `waterfall_figure()` renders it; `build_pdf_report()` produces a multi-page A4 PDF with the waterfall embedded at vector quality. Verified on all four fast-explainable models, with SVM declining gracefully rather than crashing.

**matplotlib `PdfPages` rather than reportlab/fpdf:** neither is installed, matplotlib already is. Adding a PDF dependency for one feature would break `pip install -r requirements.txt` on a marker's machine for no gain, and the SHAP figure is already a matplotlib object.

## 7.6 — What I deliberately did NOT do

| Rejected | Why |
|---|---|
| Clamp form inputs to the training envelope | A real 82-year-old must be enterable. Refusing the patient is worse than scoring with a warning |
| Block prediction on extrapolation | Clinician judgement may still want the number; removing it invites working around the tool |
| Approximate the peer percentile for out-of-range ages | Ranking an 82-year-old against 60–65 year-olds and calling them "typical" is worse than no answer |
| Constrain Random Forest for monotonicity | 8.5× calibration regression. Not tradeable |
| Retrain to include wider ages | The data does not contain them. Fabricating support is not an option |

## 7.7 — Files changed

`auth_db.py` · `train_models.py` · `feature_engineering.py` · `app.py`
**New:** `clinical_ui.py`, `models/input_ranges.json`, `models/risk_distribution.json`

## 7.8 — Summary

| | Before | After |
|---|---|---|
| Out-of-scope patients | scored silently with full confidence | flagged `hard`/`soft`, banner above verdict, band tagged |
| Supported range visible | nowhere | per-input tooltips + applicability panel |
| Peer percentile when unsupported | silently approximated | withheld with explanation |
| Extrapolation in audit trail | not recorded | `extrapolated` + reasons persisted |
| Model version per prediction | label only | version + dataset digest + threshold + band |
| Patient identity | free-text name per event | first-class entity with timeline |
| Monotonic in blood pressure | **6 inversions / 20 steps** | **0** (XGBoost) |
| Counterfactual paradoxes | 3 | **0** on the monotonic engine |
| Headline metrics | bare point estimates | bootstrap 95% CIs |

## 7.9 — Carried forward (unfinished wiring, not defects)

| Item | State |
|---|---|
| Per-patient SHAP waterfall on the diagnosis page | `clinical_ui.explain_patient` + `waterfall_figure` built & tested; not yet rendered in the UI |
| Counterfactual what-if panel | engine built & tested; must route through **monotonic XGBoost**, not the ensemble |
| PDF download button | `build_pdf_report` built & tested; not yet replacing the .txt download |
| Patient Records page (trajectory) | data layer complete (`get_patient_timeline`); page not built |
| Outcome Review / drift page | data layer complete (`get_outcome_stats`); page not built |
| Batch scoring page | not started |
| Model card + intended-use statement | not started |
| CIs displayed in Tab 1 | computed and stored; not yet rendered |
| `max_predictions_per_day`, `session_timeout_min` | still unenforced (Run 3 §3.5) |
| External validation | requires a second cohort — not available |
| Encryption at rest | requires a key-management decision (project owner's call) |

---
---

# RUN 8 — Live testing campaign: 5 bugs found and fixed (2026-07-27)

App launched on `localhost:8501`, then tested by **clicking every button and submitting
every form**, not merely loading pages. Page-load tests had been passing since Run 3;
every bug below lived in a widget interaction, a file-I/O path, or a stale constant —
none were reachable by loading a page.

## 8.0 — Bugs found

| ID | Severity | Defect |
|---|---|---|
| BUG-24 | 🔴 | Deleted user crashes the diagnosis page (unhandled `IntegrityError`) |
| BUG-25 | 🔴 | Banning or deleting a user does not end their active session |
| BUG-26 | 🔴 | Physiologically impossible measurements scored with confidence |
| BUG-27 | 🔴 | Restore silently reverts Run 4–7 safety features |
| BUG-28 | 🟠 | Manifest digest for `preprocess_report.txt` always stale |

---

### BUG-24 — Deleted user crashes the diagnosis page

**Found by** clicking every button on every page. "Delete Account" removed the session
user; the next diagnosis submission then raised:

```
sqlite3.IntegrityError: FOREIGN KEY constraint failed
  at auth_db.upsert_patient -> INSERT INTO patients (... created_by)
```

**Cause.** `patients.created_by` references `users(id)`, and foreign keys are now
enforced (the BUG-20 fix). Run 7 added `upsert_patient()` to the diagnosis flow without
considering that the logged-in user might no longer exist. Real scenario: an
administrator deletes a clinician who is mid-session; that clinician's next assessment
hard-crashes the page.

**Fix.** `upsert_patient` validates `created_by` and degrades to `NULL` if the user is
gone. The diagnosis page additionally wraps the call — losing the attribution is
acceptable, **losing the clinical assessment is not**, so the prediction is still
recorded and the UI says the timeline link failed.

---

### BUG-25 — Ban and delete did not end an active session

Investigating BUG-24 exposed something worse. `st.session_state.user` is a plain dict
captured at login and **never revalidated**. Therefore:

- a **banned** user kept working with full privileges until they chose to sign out
- a **deleted** user kept working
- a **demoted** user kept their old navigation, including pages above their new role

The ban button's entire purpose is to revoke access, and it did not.

**Fix.** The router now revalidates against the database on every rerun: missing
account → signed out; banned → signed out with an audit entry; role changed → session
refreshed in place so a demotion takes effect immediately.

**Verified.**

| Session | Signed out | Nav present |
|---|---|---|
| deleted user | ✅ | — |
| banned user | ✅ | — |
| valid SuperAdmin | — | ✅ |
| stale Doctor, DB says Admin | — | 9 Admin pages; Doctor-only page gone |

---

### BUG-26 — Impossible measurements scored with confidence

**Found by** submitting boundary values. `90/180` — systolic *below* diastolic —
returned **"LOW RISK"**, `extrapolated=False`, no warning.

**Cause.** Two gaps compounding:

1. `check_applicability` tested each raw input separately. 90 is within `ap_hi`'s range
   [60, 240]; 180 is within `ap_lo`'s [40, 182]. Both pass individually while their
   **combination** yields a pulse pressure of **−90** against a training range of
   [5, 140].
2. The training pipeline rejects `ap_hi <= ap_lo` rows (`_domain_filter`). The input
   form enforced no such rule, so it silently laundered a transcription error into a
   clinical record.

**Fix.** Two changes, kept conceptually distinct:

- `fe.validate_physiology()` — a **hard refusal**, shared with the training rule.
  Extrapolation means "a real patient the model has not seen" and earns a warning;
  this means "not a possible measurement" and must be refused. Also catches pulse
  pressure < 5 mmHg and implausible BMI.
- `pulse_pressure` and `bmi` added to the envelope check, so **derived** features are
  validated too — the general lesson from this bug.

**Verified.**

| Input | Refused | Reason |
|---|---|---|
| 90/180 | ✅ | systolic must exceed diastolic |
| 120/120 | ✅ | systolic must exceed diastolic |
| 122/119 | ✅ | pulse pressure 3 mmHg below training minimum |
| 100 cm / 200 kg | ✅ | BMI 70 outside plausible range |
| 160/95 | — | valid, scored normally |

---

### BUG-27 — Restore silently reverted the Run 4–7 safety features

**Found by** a backup round-trip test. A **genuine** archive produced:

```
accepted=12  refused=5  mismatch=1
refused = [benchmarks.json, input_ranges.json, risk_distribution.json,
           thresholds.json, tuning_result.json]
```

**Cause.** The restore allowlist was hardcoded inside `page_backup_restore` in Run 3.
Runs 4–7 added five artifacts and nobody updated it. The failure was **silent and
safety-critical**:

| Artifact refused | Consequence |
|---|---|
| `thresholds.json` | `get_risk_threshold()` falls back to **0.50** — undoes all of Run 4, **doubling the miss rate from 74 to 157 per 1,000** |
| `input_ranges.json` | `check_applicability()` returns nothing — the BUG-23 extrapolation guard **goes dead** |
| `risk_distribution.json` | peer percentile unavailable |
| `benchmarks.json` | Tab 11 blank |
| `tuning_result.json` | ceiling evidence lost |

A "restore" quietly downgrading clinical safety is the worst possible failure mode for
that feature — you would reach for it precisely when something had gone wrong.

**Fix, designed so it cannot recur.** The canonical artifact set now lives in
`fe.MODEL_ARTIFACTS`, beside the feature contract, and `page_backup_restore` imports it
instead of keeping a copy. More importantly, **`train_models` now asserts at the end of
every run that it wrote nothing outside the registry**:

```
Artifact registry check: all 17 files registered.
```

Adding a future artifact without registering it breaks training loudly and immediately,
rather than quietly breaking restore months later. That is the actual fix — the stale
list was a symptom of having two sources of truth.

---

### BUG-28 — Manifest digest for the report was always stale

`preprocess_report.txt` was written **after** `_write_manifest()`, so the manifest
recorded the digest of the *previous* run's report. Every genuine backup reported a
digest mismatch on that file and refused to restore it.

**Fix.** Report written before the manifest — anything the manifest digests must exist
in final form first. All 16 digests now match their files.

---

## 8.1 — A flaw in my own test method, worth recording

The first version of the deep test was **invalid**. Phase 1 clicked every button
including "Delete Account", "Clear All Predictions" and "Purge Audit Logs", which wiped
the fixtures (predictions 20 → 0, users 8 → 5) and deleted the session user. Phases 2–3
then hit empty-state pages with no widgets and my code indexed `[0]` blindly, producing
17 spurious `IndexError` "bugs" that were entirely artifacts of the harness.

Each phase now runs against a pristine database snapshot, restored between every single
button click.

**A second, more serious testing lesson:** the BUG-23 verification in Run 7 asserted
only on **rendered UI strings** and passed — while the `extrapolated` flag was being
silently discarded before reaching the database. A test that checks what the user sees
is not a test that the system recorded it. Both suites now assert on durable state.

## 8.2 — Verification

```
PHASE 1  every button, every page, fresh DB per click      27 pages, 0 exceptions
PHASE 2  XSS / SQLi / unicode / empty in search inputs     0 failures, no raw payload
PHASE 3  diagnosis boundaries + XSS in patient name        6 cases, 2 correctly refused
PHASE 4  data integrity                                    0 orphans, 0 FK violations,
                                                           integrity_check ok
IO-A     backup archive generation                         8.4 MB, 19 members
IO-B     restore validation                                18 accepted / 0 refused;
                                                           tampered + evil.pkl + path
                                                           traversal all rejected
IO-C     custom dataset -> training                         3,924 rows, 98.1% retained
IO-C     invalid dataset (cholesterol=7)                   correctly rejected, exit 1
IO-D     app loads restored artifacts                      0 exceptions
```

Plus the standing suites: 27/27 page×role paths, 24 new-code probes, 5 OOD scenarios —
all 0 failures. `py_compile` clean on all 7 modules.

## 8.3 — Summary

| | Before | After |
|---|---|---|
| Deleted user submits assessment | hard crash | degrades, assessment still saved |
| Banned user's active session | **keeps full access** | signed out on next interaction |
| Demoted user's navigation | stale until logout | refreshed immediately |
| Systolic < diastolic | scored "LOW RISK" | refused with explanation |
| Derived features vs envelope | unchecked | `pulse_pressure` + `bmi` checked |
| Genuine backup restore | 5 artifacts silently dropped | all 18 restored |
| Artifact registry drift | possible and silent | training fails loudly |
| Manifest digests | 1 permanently stale | all 16 match |

## 8.4 — Still carried forward

Unchanged from Run 7 §7.9 — per-patient SHAP waterfall, what-if panel, PDF download
button, Patient Records / Outcome Review / Batch Scoring pages, model card, Tab 1 CIs.
All engines built and tested; UI wiring outstanding. Plus `max_predictions_per_day`
and `session_timeout_min` still unenforced, external validation needs a second cohort,
and encryption at rest needs a key-management decision.

---

# RUN 9 — Frontend redesign, Phases 0–5 (2026-07-27)

A ten-phase rebuild of the presentation layer against the "Instrument Panel" design
brief, under one hard contract: **zero behavioural change**. No clinical or statistical
logic moves. Threshold resolution order, risk-band classification, the applicability
check and its `extrapolated` persistence, peer-percentile suppression, row-level data
scoping and every `log_activity()` call site are all preserved exactly, and a 27-path
AppTest gate re-runs after every phase to prove it.

`requirements.txt` does not grow across any of the ten phases.

## 9.0 — Phase 0: recon and baseline (`2777857`)

**Why.** A redesign that cannot prove it changed nothing is a rewrite. Before touching
anything I captured the structural output of all 27 page×role paths to
`baseline/widget_tree.json`, so every later phase can be diffed against what the
application produced before it.

**How.** Inventoried the surface: 116 `unsafe_allow_html` blocks, 24 legacy CSS classes
with 111 usages, 39 matplotlib call sites carrying 85 hard-coded hexes and 24 `rgba()`
strings, 157 lines of inline CSS in `app.py`.

**One gate item cannot be satisfied and is substituted, not skipped.** The brief asks
for screenshots of every affected page in both themes. No browser automation is
available — playwright, selenium, html2image and imgkit are all absent — and the brief
forbids new dependencies. Visual verification is therefore done by (a) structural
comparison against `baseline/widget_tree.json` and (b) targeted matplotlib renders of
any geometry whose correctness is visual. This is weaker than a screenshot and is
recorded as such.

## 9.1 — Phase 1: the token layer (`a5f8f31`, `04e00c9`)

**Why.** 85 hard-coded hexes across 39 chart call sites is not a theming problem, it is
a *correctness* problem — BUG-01/02 were CSS `rgba()` strings reaching matplotlib and
crashing the entire Model Performance page. The fix has to be structural.

**How.** `ui/tokens.py` (541 lines) is the single source of truth: six brand colours,
colour maths, risk ramp, semantic and hazard families, dark counterparts. The key
decision is that `CSS` and `MPL` are **separate dicts**. Matplotlib rejects `rgba()`;
CSS wants it. Keeping one dict and hoping call sites choose correctly is how BUG-01
happened. A test asserts every value in `MPL` is a 6-digit hex, which makes the class
of bug structurally impossible rather than merely fixed.

Also in Phase 1: `ui/format.py` (decimal discipline — AUC always 4dp, percentages 1dp,
en-dash intervals), a 262-key native theme in `.streamlit/config.toml`, and
`ui/styles.py` as a single cached stylesheet with a fixed cascade order. Zero
`.st-emotion-cache-*` selectors — all scoping goes through `st.container(key=…)` →
`.st-key-<key>`, which is the officially supported hook and survives Streamlit
upgrades.

Phase 1b built the **Caliper Mark** and a 29-icon set. The icons are stored as
*structured primitives* with two renderers (SVG and matplotlib) because no SVG
rasteriser is available and the favicon has to be generated with Pillow. Building both
renderers exposed a real bug: they disagreed on arc direction (`cy − r·sin θ` vs
`cy + r·sin θ`), mirroring every arc, so shoulders rendered as smiles. Unified on
screen-space `+sin`.

**Three measured corrections to the brief**, each recorded rather than quietly ignored:
the risk ramp is not luminance-monotonic and cannot be made so while staying in the
Brand Six; "UI borders ≥3:1" is unachievable with a hairline; and the derivation
tolerance needed empirical calibration to 45 (family members measured 27–37, foreign
hues 71–123).

## 9.2 — Phase 2: the shell (`60ba5f5`)

**Why.** A flat 17-item `st.radio` is not navigation. It cannot carry an icon, cannot
group, and cannot take a per-item active treatment.

**How.** Replaced with one button per item inside a keyed container, grouped under
eyebrow labels, with selection held in `st.session_state.nav_page`. The routing
contract is unchanged — `render_sidebar` still returns the same page label the router
already matched on, so no route moved.

## 9.3 — Phase 3: the Reference Rail (`e939604`)

**Why.** The design thesis is that a reading and its tolerance are always shown
together. The rail is the element that makes that literal.

**How.** `ui/rail.py` is a pure geometry layer with five renderers. The important
function is `envelope_geometry()`, which **expands the domain** when a value falls
outside the training envelope — an out-of-range value must still be visible and visibly
outside, not clamped to the edge where it would look merely extreme. 71 geometry
assertions.

## 9.4 — Phase 4: the component library (`0b495e7`)

**Why.** Phases 5–10 all render clinical output. Building the vocabulary once, with the
clinical rules asserted rather than documented, is what stops those rules drifting
across six pages.

**How.** `stat`, `stat_grid`, `alert` (five severities including `extrapolation`),
`risk_verdict`, `operating_point`, `reliability_panel`, `data_table`, `static_table`.
Bands and thresholds are **passed in, never recomputed**, so an embedded rail cannot
disagree with the verdict the app already decided. The tests assert the forbidden
clinical vocabulary appears nowhere, that `extrapolation` takes no risk colour, and
that reliability renders as text and not colour alone.

**A CSS budget problem, fixed at the cause.** The stylesheet reached 56.3 KB of a 60 KB
budget with six phases left. Measurement showed ~15 KB was nav icon data URIs emitted
**twice** each — once for `mask-image`, once for `-webkit-mask-image` — and the
container key encoded active state (`nav-on-…` / `nav-off-…`), forcing two selectors
per icon: 36 payloads for 18 icons. Fixed by making the key stable, moving active state
to the button `type`, and declaring each URI once as a custom property that a shared
rule consumes. 48.3 KB, 8 KB reclaimed.

**A verification that proved nothing, caught before commit.** The active-state check
returned `primary=[]` for every page — AppTest does not expose `button.type`, so the
assertion was vacuous. Re-verified at the function level instead: `sidebar_nav` emits
exactly one `type="primary"` per render, for the active label, with unique keys.

## 9.5 — Phase 5: the sign-in screen

**Why — the security finding.** The login page printed **all three seeded credential
pairs in plaintext to every anonymous visitor**, one of them SuperAdmin. A demo
convenience that ships as a published credential list is not a demo convenience; it is
three unauthenticated accounts. The brief flagged it and it is the reason this phase
exists independently of the visual work.

**How.** The seeds moved to `auth_db.SEED_CREDENTIALS` and are printed **once, to the
server console**, at the moment an empty database is created, with the login page
carrying a caption saying where to look. Someone with the terminal already controls the
machine; someone with the URL does not. They are deliberately *not* written to
`system_logs` — that table is readable through Activity Logs by any Admin, which would
put the plaintext back in a browser by a longer route.

**The screen itself:** a 44/56 full-bleed split. Left panel is Ink in both themes with
the mono lockup, one statement of substance, three trust markers, and a large static
Reference Rail as ambient art at 8% opacity. Right panel is a single 400px card with a
segmented control instead of tabs.

Two decisions worth recording:

- **The trust markers are derived, never written.** A hard-coded "AUC 0.8000" on the
  sign-in screen becomes a false claim the first time anyone retrains. They read the
  shipped artifacts through the existing loaders, and they quote the **ensemble** —
  which is what the prediction path actually uses — rather than the best single model,
  because a headline describing a model the user never touches is a worse lie than no
  headline. A missing artifact drops its marker instead of substituting a plausible
  number.
- **The ambient rail carries no value marker.** It shows the empty instrument: track,
  four band zones at the shipped threshold proportions, notches, scale. A rail
  displaying a *reading* on the sign-in screen would be a measurement taken on a
  patient who does not exist. It is `aria-hidden`, unfocusable and unanimated.

**Validation moved inline** — beneath each field, not a banner above. This needed the
message to survive into the next run, so failures are written to session-state error
dicts and cleared on every submit. Sign-in failure deliberately does not say *which*
field was wrong: naming it turns the form into a username oracle.

**Preserved exactly:** the `validate_login` call and its three statuses, the
`log_activity` on success, the `registration_allowed()` gate (BUG-17), the Doctor-only
role lock (BUG-09), and the six-character password minimum.

**A test that polluted the live database, caught and fixed.** The XSS probe registers
with an `<img … onerror=…>` username — and *succeeds*, because `register_user` accepts
any non-empty string. The suite runs against `heartguard.db`, not a fixture, so it was
leaving that account behind. The test now deletes it and asserts the deletion.

**A finding left deliberately unfixed, for the record:** `register_user` performs no
character validation on usernames. This is defended in depth — every render site passes
through `esc()`, and the probe confirms no tag can form — but the underlying input
validation is absent. Fixing it means changing `auth_db` authentication logic, which
the zero-behavioural-change contract places out of bounds for a presentation-layer
phase. Flagged rather than changed unilaterally.

## 9.6 — Phase 5 gate

```
27-path AppTest         27/27 routed, 0 exceptions
py_compile              clean on 12 modules
pyflakes                no new warnings vs baseline
test_tokens             0 failures   (63 assertions)
test_brand              0 failures   (60)
test_rail               0 failures   (71)
test_components         0 failures   (95)
test_login              0 failures   (68)
CSS budget              53.4 KB / 60 KB       emotion-cache selectors: 0
screenshots             SUBSTITUTED — see 9.0
```

## 9.7 — Carried forward

Phases 6–10 remain: the diagnosis page (SHAP waterfall, counterfactual panel through
the monotonic XGBoost, PDF download, applicability rails), `ui/charts.py` and the 39
matplotlib call sites, dashboards and history, the Model Performance IA restructure
from 11 tabs to 4 segmented groups, and the admin pages with the final accessibility,
responsive and print passes.

Everything listed in Run 8 §8.4 is still outstanding and unchanged.

---

# RUN 10 — Frontend redesign, Phase 6: the diagnosis page (2026-07-27)

The highest-stakes screen in the application. Rebuilt against §7.3, and the three
engines built in Run 7 but never wired — per-patient SHAP, the counterfactual
simulator, the PDF report — are now reachable from the UI for the first time.

## 10.1 — Three structural changes, each with a reason

**The inputs left `st.form`.** §7.3 requires the applicability rails to show "the
patient's current value as a live marker" so a clinician sees they are about to
extrapolate *before* submitting. A form withholds its widget values until submit, which
would draw every marker at its default position while the fields above showed something
the clinician had already changed. A marker that disagrees with its own field is worse
than no marker at all.

**The result therefore moved into session state.** Without a form, every keystroke
reruns the script, and a result rendered inline would vanish the moment the clinician
touched a field to compare. Scoring and the database write still happen **only** inside
the submit branch, so the one-row-per-submit contract is unchanged — and there is now a
test that edits two inputs after a submit and asserts no second row appears.

**That change created a hazard, which needed its own fix.** A persisted result stays on
screen while the clinician starts entering the *next* patient — so the verdict beside
the form could belong to someone else. The result now opens with an identity strip
carrying the patient code, name and model version. It is not decoration; it is what
makes the persistence safe.

## 10.2 — The result stack, in the order §7.3 fixes

1. **Extrapolation banner** — full width, above everything, never collapsed, never
   dismissible. A probability rendered at 64px is authoritative-looking whether or not
   the model has ever seen a patient like this one, and the only defence is that the
   caveat is read first. The test asserts the banner's index in the document is *lower*
   than the verdict's, not merely that both exist.
2. **`risk_verdict`** — probability, band chip beside it, the full Reference Rail
   beneath, eyebrow reading "Screening result".
3. **`operating_point`** — threshold, sensitivity, specificity, PPV, and a sentence
   naming the source: derived for this age band from out-of-fold predictions.
4. **`reliability_panel`** — band AUC with CI on a rail, calibration gap, holdout n,
   Strong/Moderate/Limited as text. The low-reliability caution keeps its exact Run 5
   wording.
5. **Per-patient SHAP waterfall** — replaces the global `feature_importances_` chart
   entirely.
6. **Counterfactual panel** — routed through the monotonic XGBoost.
7. **Peer percentile**, or an empty slot with a reason.
8. **Downloads** — `.txt` and PDF, side by side.

## 10.3 — Why the global importance chart had to go

It was a static, model-level ranking — **identical for every patient** — captioned
"Top Risk Factors" and placed directly beneath that patient's score. It read as
personalised reasoning while containing none. The caption is now "Contributions for
this patient", which is a claim the SHAP waterfall can actually support.

Three disclosures ship with it, because a waterfall invites over-reading:

- bars are in **log-odds**, the model's native output space, and the copy says they do
  not sum to the probability above;
- they are explicitly **not causal**;
- when the explainer is a **surrogate** — it is, for the ensemble and for SVM — the
  panel names the substitute model. A waterfall captioned as this patient's reasoning,
  computed on a different estimator than produced the number above it, is a quiet lie.

## 10.4 — Why counterfactuals route through XGBoost and not the ensemble

Not a preference. XGBoost carries `monotone_constraints`, so a change in a protective
direction **cannot** raise its predicted risk. Averaging it with unconstrained members
reintroduces exactly the paradoxical rows the constraint exists to prevent — and the
panel would then report "lower your blood pressure" as an increase in risk.

If the constrained model is unavailable, the panel says so and simulates nothing.
Falling back to the ensemble would make a real model limitation indistinguishable from
an artifact of averaging.

Three presentation rules enforce what the engine already decided:

- a **negligible** row renders with no direction and no arrow — the engine classifies
  anything under its noise floor as immaterial, and a signed −0.3% beside it would read
  as a small reason to act;
- a **paradoxical** row is labelled a model limitation, never a recommendation;
- crossing the action threshold is called out explicitly, because that — not the size
  of the delta — is what changes the clinical decision.

## 10.5 — `ui/charts.py`

Built here rather than in Phase 7 because the SHAP waterfall needs it. Its contract is
one line: **a CSS colour string must never leave this module.** `T.MPL` holds 6-digit
hexes only, a test asserts it, and `palette()` is the only sanctioned way to obtain a
chart colour.

Two decisions recorded:

- **Figures are themed at construction, not via `rcParams`.** `plt.rcParams` is
  process-global and Streamlit reruns the script per interaction, so a page that mutated
  it would leak its styling into every other page's figures in an order-dependent way.
- **`render()` closes every figure it draws.** matplotlib keeps unclosed figures in a
  global registry; a page that leaks one per rerun leaks one per keystroke.

## 10.6 — Bugs found and fixed during the phase

**The PDF button was silently disabled for an entire test cycle.** `_pdf_report` had a
bare `except Exception: return None`, and behind it sat two real contract mismatches
against `build_pdf_report`: it wants `percentile['pct']` and `operating['band']`, and
was being handed `percentile['percentile']` and `operating['age_band']`. A third latent
fault was `dict.get(k, 0)` returning `None` rather than the default for keys that are
*present and None* — which they are for any model whose threshold profile lacks NPV,
and every rate in the report is formatted with `:.1%`. The function now returns
`(bytes, error)` and the disabled button names the reason.

**The old empty state hotlinked a Wikimedia PNG.** It breaks on any machine without
internet and violates the vendor-don't-hotlink rule. Replaced with `empty_state`.

**A test-harness trap worth recording.** `import app` executes the page body in a bare
Streamlit context, which leaves the container stack pointing inside a container that
never closed. Every `AppTest` run afterwards fails with *"st.button() can't be used in
an st.form()"* — an error that looks exactly like a product bug and is not one. The
suite now completes all AppTest interaction before importing `app` for the report
generators, with the reason recorded at the import.

**My own test filter invalidated most of the suite, twice.** The stylesheet is emitted
as markdown and defines a rule for every class the tests search for, so any filter that
lets it through turns `"hg-peer--void" in md` into a constant `True`. Filtering on
`--hg-` was worse: it also dropped every component carrying an inline custom property,
including the verdict. Nine assertions were reporting on the stylesheet rather than the
page.

**A dead-CSS search that reported zero, wrongly.** It excluded the legacy block by
`src.replace(_legacy_block(), "")` — which never matched, because `_legacy_block()`
returns CSS with the f-string tokens already substituted. Every class matched its own
rule. Excluding styles.py *by file* found six genuinely dead rules.

## 10.7 — The CSS budget, solved structurally

The sheet reached 58.5 KB of a 60 KB budget with four phases left. Measurement found
**12.0 KB — 21% of the stylesheet — was comments.** Those comments are why the next
person can change a rule without breaking the cascade, and they are worthless to a
browser. `stylesheet()` now strips them at assembly: the reasoning stays in the source,
the payload does not carry it.

The guard matters more than the saving. A regex eating `/* … */` across 46 KB of
generated CSS could in principle chew through a `url("data:image/svg+xml,…")` payload
and produce a sheet that parses but renders wrong — the worst failure mode, because
nothing raises. The stripped sheet is returned only if it still balances its braces and
still carries all 18 data URIs; otherwise the commented original ships, heavier and
definitely correct.

```
source (commented)   58.6 KB
shipped              46.3 KB / 60 KB      13.7 KB headroom
```

## 10.8 — Phase 6 gate

```
27-path AppTest         27/27 routed, 0 exceptions
py_compile              clean on 13 modules
pyflakes                no new warnings vs baseline
test_tokens             0 failures   (63 assertions)
test_brand              0 failures   (60)
test_rail               0 failures   (71)
test_components         0 failures   (95)
test_login              0 failures   (68)
test_diagnosis          0 failures   (76)
CSS budget              46.3 KB / 60 KB   emotion-cache selectors: 0
screenshots             SUBSTITUTED — see 9.0
```

**The extra gate §7.3 demands — the five OOD scenarios re-asserted on database
contents, not rendered strings:**

```
82yo above age support        extrapolated=1  notes recorded  ver+thr+band stamped  linked
19yo below age support        extrapolated=1  notes recorded  ver+thr+band stamped  linked
55yo BP 245/195               extrapolated=1  notes recorded  ver+thr+band stamped  linked
52yo fully supported          extrapolated=0                  ver+thr+band stamped  linked
64yo near p99                 extrapolated=0                  ver+thr+band stamped  linked
```

This is the assertion that matters. The Run 7 verification of BUG-23 checked only UI
text and **passed** while the `extrapolated` flag was being discarded before the INSERT.
A test that checks what the user sees is not a test that the system recorded it.

## 10.9 — Preserved exactly

Physiology refusal before scoring (BUG-26), the applicability check before rendering
(BUG-23), shared feature engineering (BUG-05), one decision rule for both paths
(BUG-18), per-model age-stratified operating points (Run 5), the 0-indexed cholesterol
and glucose encoding (BUG-04), patient linking that cannot lose the assessment
(BUG-24), peer-percentile suppression under extrapolation, and every clinical sentence
in the plain-text report — that report is a record a clinician may already have filed,
and rewording it would make two archived copies of the same assessment disagree.

## 10.10 — Carried forward

Phases 7–10: retheme the remaining matplotlib call sites onto `ui/charts.py`,
dashboards and history, the Model Performance IA restructure from 11 tabs to 4
segmented groups, and the admin pages with the final accessibility, responsive and
print passes.

Two items noted but deliberately not acted on, both outside a presentation phase's
remit:

- `register_user` performs no character validation on usernames. Defended in depth —
  every render site passes through `esc()` — but the input validation is absent.
- `use_container_width` is deprecated in favour of `width='stretch'` and is used
  throughout. A global sweep belongs in Phase 10, not scattered across six phases.

---

# RUN 11 — Frontend redesign, Phase 7: the chart layer (2026-07-27)

Every matplotlib figure in the application now takes its colour from the token module.
The goal was not tidiness — it was to make BUG-01/02 structurally impossible rather
than merely fixed.

## 11.1 — The recon undercounted by a factor of three

Phase 0 reported "39 call sites, 85 hard-coded hexes". The real figure is **38 call
sites and 268 hexes across 22 distinct colours**, plus 19 named colours the hex search
could not see at all and 7 built-in colormaps. The recon only counted lines that also
named a chart function, so every colour held in a list, a tuple or a dict was invisible
to it.

Recorded because it is the same lesson as BUG-22: a measurement that looks at a
consequence rather than the cause will under-report.

## 11.2 — What `ui/charts.py` provides

| | |
|---|---|
| `color(role)` | one colour by role, resolved against the viewer's theme **at call time** |
| `palette(theme)` | the whole flat dict, optionally pinned to a named theme |
| `series_color(name)` | a model's colour, **keyed by name** |
| `categorical(n)` | the brand ramp for series with no inherent order |
| `cmap(kind, reverse)` | `sequential` / `risk` / `diverging`, built from the token ramps |
| `on_color(bg)` | readable ink for text sitting on a filled cell |
| `figure()` / `style_axes()` / `render()` | themed, transparent, self-disposing |

Three decisions worth recording:

- **`color()` is a function, not a module constant.** The correct value depends on the
  active theme, which is only knowable during a script run. A constant would freeze
  whichever theme was active when the process started — which is exactly what happened
  to `MODEL_COLORS` mid-sweep and is why it was deleted.
- **An unknown role raises.** A silent fallback produces a chart in the wrong colour
  with nothing to indicate it, which is the failure the token layer exists to prevent.
- **Figures are themed at construction, not through `rcParams`.** `rcParams` is
  process-global and Streamlit reruns per interaction, so a page that mutated it would
  leak styling into every other page's figures in an order-dependent way.

## 11.3 — The colormaps had to go, and one honest limitation

The pages used `RdYlGn`, `YlOrRd` and `RdBu_r`. All three are off-brand. `RdYlGn` is
also the worst available choice for clinical work: red-green is the commonest form of
colour-vision deficiency, so its two endpoints are indistinguishable for roughly one
man in twelve.

Measured luminance of the replacements:

```
sequential   0.919 -> 0.175 -> 0.006     monotonic; survives greyscale
diverging    0.139 -> 0.911 -> 0.137     symmetric, dark-light-dark
risk         0.195 -> 0.261 -> 0.137     NOT monotonic
```

The `risk` ramp cannot be made luminance-monotonic inside the Brand Six — the same
finding recorded for the risk ramp in Phase 1. So it is documented as safe for **band
identity**, where hue carries a category that is also labelled in text, and wrong for
**magnitude**, where a reader would infer an ordering the lightness does not support.
Every magnitude heatmap uses `sequential`. A test pins the non-monotonicity so that
nobody later "corrects" the documentation.

`pages_ext.py` was also still calling `plt.cm.get_cmap`, removed in matplotlib 3.9 —
a deprecation waiting to become a crash.

## 11.4 — Three bugs that only rendering could find

No browser automation exists, so the substitute for a screenshot was to drive the Model
Performance page — which owns 30 of the 38 figures — in both themes, intercept every
figure at the moment the page disposes of it, and look at them. 71 figures per theme.
Three defects came out of that which no assertion I had written would have caught:

**The metric charts were painted in risk colours.** Pass 1 mapped five categorical
metrics (Accuracy, AUC, F1, Precision, Recall) onto five semantic roles, which put
Accuracy and F1 in near-identical verdigrises *and* implied a clinical reading of a
metric bar. §3.10 reserves the risk hues for clinical meaning. Now `categorical(5)`.

**The model bar charts reintroduced BUG-19.** Colour was assigned by position in a list
sorted by AUC, so a model changed colour whenever its ranking changed. Now
`series_color(name)`, and a test reverses the model list and asserts nothing moves.

**Every confusion matrix had its largest cell dark-on-dark.** The heatmaps chose cell
text colour from the underlying *value* — `'black' if val > 0.12` — which only worked
because `RdYlGn` happens to be light at its high end. A ramp that is dark there
inverted the logic. Replaced with `on_color(cell_colour)`, deciding from the background
rather than the datum.

## 11.5 — Two bugs in my own verification

**The dark-theme render was not testing the dark theme.** `charts.py` does
`from .styles import active_theme`, which binds the function *object* at import, so
patching `ui.styles.active_theme` never reached it. The first two rounds of "verified in
both themes" rendered the light palette twice. Caught by noticing that dark-theme value
labels looked dark.

**`on_color`'s threshold was mistuned and the test caught it.** It used
`luminance > 0.45`, but Ink and Bone cross over at ≈0.18 — so every cell between 0.18
and 0.45 was given the *worse* of the two options. Measured worst-case contrast across
the three ramps was 2.00–2.85 against a 3:1 floor. It now measures both candidates and
takes the better, which cannot be wrong by a mistuned constant. Worst case is now ≥4.1.

## 11.6 — The PDF must never follow the viewer

`waterfall_figure` renders in two places with opposite requirements: on screen it must
follow the viewer, in the PDF it is printed on white A4. A dark-mode user exporting a
report would otherwise get near-white ink on a white page — an unreadable file,
produced silently, that they then hand to someone else.

It now takes a `theme` argument; `app.py` passes `theme="light"` for the PDF copy and
nothing for the screen. `_pdf_text_page` pins `palette('light')` and never calls
`color()`. The post-hoc repaint in `build_pdf_report` stays as a backstop for any
caller that hands over a screen-built figure, with a note that it cannot recover the
bar colours and the theme argument is the real fix.

## 11.7 — The invariant

The most valuable test in `tests/test_charts.py` reads the page modules as **source**
and fails if any colour literal — hex or named — sits on a line reaching matplotlib.
That is the guarantee. Everything else tests the alternative that `ui/charts.py`
provides; a suite that only exercised `ui/charts.py` would have passed happily while
`app.py` carried 268 hard-coded hexes, which is the state this phase began in.

`'white'` is permitted on exactly one path — `clinical_ui.py`'s printed A4 page — and
the test enforces that exception by file.

## 11.8 — Phase 7 gate

```
27-path AppTest         27/27 routed, 0 exceptions
py_compile              clean on 14 modules
pyflakes                no new warnings vs baseline
test_tokens             0 failures   (63 assertions)
test_brand              0 failures   (60)
test_rail               0 failures   (71)
test_components         0 failures   (95)
test_login              0 failures   (68)
test_diagnosis          0 failures   (76)
test_charts             0 failures   (78)
figures rendered        71 per theme, light and dark, 0 exceptions
colour literals reaching matplotlib      0
screenshots             SUBSTITUTED — see 9.0
```

## 11.9 — Carried forward

Phases 8–10: dashboards, history, reports and profile; the Model Performance IA
restructure from 11 tabs to 4 segmented groups; the admin pages with the final
accessibility, responsive and print passes.

The 389 hexes inside HTML strings are untouched and deliberately so — they belong to
the pages Phases 8–10 rebuild, and moving them now would have made a Phase 7 regression
impossible to attribute.

---

# RUN 12 — Frontend redesign, Phase 8: dashboards, history, reports, profile (2026-07-27)

Four pages moved onto the component library. §7.4 is explicit that role-aware **content**
stays exactly as it is — same figures, same roles, same queries — and only the
presentation changes. That constraint held: no query, no scoping rule and no role gate
was touched.

## 12.1 — The KPI cards are gone

They were gradient-filled, six different hues, each with its own border colour, and they
read as six detached objects competing for attention. `stat_grid` renders the same
numbers hairline-separated on one surface, so the strip reads as a single instrument
panel. §3.5 prefers hairlines to shadows precisely because a dashboard where every tile
floats looks like a template.

**Tone is now applied only where a figure carries clinical meaning** — the flagged and
below-threshold counts. User counts, doctor counts and model counts take no tone,
because colouring an inventory number the same crimson as a clinical finding is what
makes a dashboard unreadable at a glance. The old cards coloured all six.

19 of the original 35 KPI call sites are converted. The remaining 16 belong to the admin
and management pages, which Phase 10 rebuilds; the `.kpi-*` rules stay in the legacy
shim until then.

## 12.2 — Three labels that were making claims the numbers cannot support

| Was | Now | Why |
|---|---|---|
| "Confidence: 62.0%" | "Risk estimate" | A calibrated probability is not the model's confidence in itself. 0.62 means roughly 62 in 100 such patients have the outcome, not that the model is 62% sure — the old label invited exactly the misreading §3.10 forbids. |
| "Avg Risk Score" | "Mean risk estimate", hinted *cohort mean, not one patient's score* | The mean of a set of probabilities belongs to nobody. Calling it a score invites reading it as a cohort verdict. |
| "High Risk" / "Low Risk" as row verdicts | "Flagged" / "Below threshold" | §3.10's fixed vocabulary. A row saying "Low Risk" reads as reassurance; the threshold is tuned for screening sensitivity and misses roughly one diseased patient in seven. |

## 12.3 — The persisted extrapolation flag now surfaces in history

`predictions.extrapolated` has been stored since Run 7 and displayed nowhere outside the
diagnosis page. Prediction History now carries an **Applicability** column reading
"Extrapolated" or "In envelope".

This is the whole point of having stored it. A historical score taken outside the
training envelope must stay marked as one for as long as the record exists — otherwise
the caveat lives only in the session that produced it, and the row that outlives it
looks exactly like a valid one.

## 12.4 — Empty states name an action

§7.4: never "No data available". Every empty state on these four pages now says what to
do next — open Heart Disease Prediction, widen the date range, clear the filters, ask a
SuperAdmin to train. The filtered-to-nothing case is distinguished from the
nothing-exists case, because they need different actions.

## 12.5 — A component that shipped broken and was never once called

`data_table` forwarded `height=None` to `st.dataframe`, which rejects it outright with
`StreamlitInvalidHeightError` — it wants a positive integer, `'stretch'`, `'content'`,
or the argument absent. So the component **raised on every call a page would naturally
make**, and it had been in the library since Phase 4.

It survived because the Phase 4 test suite only ever exercised `static_table`.
`data_table` was exported, documented, and never invoked. A library test that skips an
export is not a library test.

Fixed by building the kwargs conditionally, and — more importantly — the component suite
now drives **every one of the 16 public exports through AppTest with its default
arguments**, and separately asserts that nothing is exported without appearing in that
list. That second assertion is what stops the same gap reopening. It immediately found a
second arity error in the test itself (`footer_meta` takes three arguments, not two).

## 12.6 — Profile

Rebuilt on §7.2's inline-validation pattern: errors beneath the field they concern,
carried in session state so they survive the rerun. The password minimum now matches
registration's — a profile form that accepts a 3-character password silently undoes the
rule enforced at sign-up.

Username and role are shown read-only beside the form, with a caption saying why they
are not editable there: self-service role elevation was BUG-09, a real vulnerability
that two accounts in the live database had already exploited. Stating the reason is
better than leaving a user hunting for a field that was deliberately removed.

## 12.7 — Phase 8 gate

```
27-path AppTest         27/27 routed, 0 exceptions
py_compile              clean on 14 modules
pyflakes                no new warnings vs baseline
test_tokens             0 failures   (63 assertions)
test_brand              0 failures   (60)
test_rail               0 failures   (71)
test_components         0 failures   (98 — +3 smoke assertions)
test_login              0 failures   (68)
test_diagnosis          0 failures   (76)
test_charts             0 failures   (78)
CSS budget              46.3 KB / 60 KB   emotion-cache selectors: 0
KPI cards on the four rebuilt pages       0
screenshots             SUBSTITUTED — see 9.0
```

## 12.8 — Carried forward

Phase 9: the Model Performance IA restructure — eleven horizontal tabs into four
segmented groups — plus rendering the bootstrap CIs in the metric table.

Phase 10: the admin and management pages (16 remaining KPI call sites, the typed-
confirmation pattern for destructive actions, the Activity Logs danger zone), the
accessibility audit against §8, responsive verification at 1440/1280/1024/768, the print
stylesheet, and the `use_container_width` → `width='stretch'` sweep.

---

# RUN 13 — Frontend redesign, Phase 9: the Model Performance IA (2026-07-27)

Eleven horizontal tabs became four groups. §7.5 calls this "the single largest usability
gain available on this page" and requires **zero content changes** — pure information
architecture.

```
Performance      Metric Comparison · Confusion Matrices · Detailed Report · ROC & PR Curves
Validation       K-Fold CV · Subgroup Performance & Fairness
Clinical         Threshold & Clinical Utility · Clinical Benchmark & Feature Value
Explainability   Feature Importance · SHAP · Model Info
```

## 13.1 — It is also a 7× performance fix

`st.tabs` renders **every** tab body on every run. All eleven were executing on each
page load. Measured warm, in the same process:

```
before   all eleven tabs            55.3s
after    Performance (the default)   7.8s
         Validation                  8.0s
         Clinical                    9.1s
         Explainability             27.6s   (SHAP is genuinely expensive)
```

This is why each body sits behind `if label in _slot:` rather than merely being handed a
different container. A container swap would have produced the same navigation with none
of the saving — the bodies would still all run.

My first measurement of this was wrong and nearly hid the win. I timed the page at 24.5s
before and 23.0s after and concluded the restructure had barely helped. Both numbers came
from a process where AppTest had already rendered the page once, so the caches were partly
warm and the comparison was meaningless. Timing each variant in a cleanly warmed process
showed 55.3s → 7.8s.

## 13.2 — How a 2,000-line re-indent was made safe

Moving eleven bodies under a guard means re-indenting roughly 2,000 lines, and many of
them sit inside triple-quoted f-strings. Indenting a *continuation* line inside one of
those changes the string's contents — and in markdown, four extra leading spaces silently
turn a paragraph into a code block. That is a corruption no test of the rendered page
would reliably catch.

So the transform was done with `ast` rather than a regex: every line that falls inside a
multi-line string literal is protected from indentation, because only the AST can
identify those reliably.

**The verification is the part worth keeping.** `tests/test_performance_ia.py` parses the
pre-restructure snapshot and the current module, extracts every string literal from both,
and classifies any literal that is no longer present:

- **corrupted** — the same text exists but its indentation changed. Detected by matching
  on the dedented form. **0 of 2,978.**
- **deleted** — genuinely gone. 16, all located by *source line range* inside the two
  blocks Phase 9 deliberately replaced.

Locating them by line range rather than by keyword matters: an f-string splits into one
AST node per gap between placeholders, so fragments like `</b> &nbsp;|&nbsp;` contain
none of the words a keyword list would search for. My first version of that check
reported all 16 intentional deletions as failures — a test that cannot tell intent from
accident.

## 13.3 — The bootstrap CIs, and what they say

§7.5 asked for the intervals to be rendered. They have been computed and stored since
Run 4 and displayed nowhere, so the table ranked five models by AUC and starred the
leader while:

```
Random Forest                  0.8000  [0.7925, 0.8072]
XGBoost                        0.7999  [0.7922, 0.8070]
Decision Tree                  0.7933  [0.7853, 0.8005]
Logistic Regression            0.7920  [0.7841, 0.7987]
Support Vector Machine (SVM)   0.7918  [0.7839, 0.7985]
```

A gap of **0.0001** between first and second, and every interval overlapping the
leader's. The star was presenting noise as a result.

There is now an `AUC 95% CI` column and, above the table, a sentence that is **computed,
not written**: it reports the actual overlap and currently reads *"every model's interval
overlaps Random Forest's [0.7925–0.8072], so the ranking is not evidence that any one of
them is better than another."* If a future retrain genuinely separates two models, that
sentence changes to say so. A caveat that is true regardless of the data is one readers
learn to skip.

## 13.4 — Two things removed from the headline

**The trophy banner.** A gold-medal emoji beside a leader whose interval overlaps every
other model's is a celebration of noise.

**Accuracy as the largest number on the page.** §3.10 forbids it as a headline, and at
this dataset's near-balanced prevalence 0.70 accuracy tells a reader almost nothing. The
headline strip now carries the leading model, AUC **with its interval**, and sensitivity
at the operating point — the metric a screening tool is actually chosen on. Accuracy
remains in the table.

## 13.5 — Phase 9 gate

```
27-path AppTest          27/27 routed, 0 exceptions
py_compile               clean on 15 modules
pyflakes                 no new warnings vs baseline
test_tokens              0 failures   (63 assertions)
test_brand               0 failures   (60)
test_rail                0 failures   (71)
test_components          0 failures   (98)
test_login               0 failures   (68)
test_diagnosis           0 failures   (76)
test_charts              0 failures   (78)
test_performance_ia      0 failures   (40)
string literals          2,978 checked · 0 corrupted · 16 deliberately removed
tab bars                 max 4 items (was 11)
warm render, default     7.8s (was 55.3s)
screenshots              SUBSTITUTED — see 9.0
```

## 13.6 — Carried forward

Phase 10 only: the admin and management pages (16 remaining KPI call sites, §7.6's
typed-confirmation pattern for destructive actions, the Activity Logs danger zone as a
hairline `danger` panel rather than a red fill), the §8 accessibility audit including
protanopia/deuteranopia simulation of the four band colours, responsive verification at
1440/1280/1024/768, the print stylesheet, and the `use_container_width` →
`width='stretch'` sweep.

---

# RUN 14 — Frontend redesign, Phase 10: admin pages, accessibility, print (2026-07-27)

The last phase. Destructive actions gated, the quality floor in §8 measured rather than
asserted, and the legacy shim reduced to what is genuinely still referenced.

## 14.1 — Ten destructive actions had no confirmation at all

Every one was a bare `st.button`, the same size and weight as the benign control beside
it, one click from irreversible. Two of them — *Clear All Predictions* and *Purge Audit
Logs* — sat adjacent with no guard whatsoever, and **the Phase 4 deep test destroyed the
entire fixture database by clicking them in sequence.** If an automated sweep can wipe
the system by accident, so can a person.

§7.6's pattern is now a component:

- **`danger_zone(title, body)`** — a `danger`-toned panel with a **hairline border, never
  a red fill**. The brief's reasoning is right and worth repeating: red fills
  desensitise. A user who sees a red block every time they open Activity Logs stops
  seeing it by the third visit. The signal has to be rare to work.
- **`destructive(label, confirm, key)`** — returns `True` only when the exact phrase has
  been typed. The phrase is **the target's own identifier**, not a generic "DELETE", so
  muscle memory cannot carry someone through the gate: confirming requires reading which
  record is about to go. The button stays enabled and reports the mismatch rather than
  being disabled, because a disabled button with no explanation is a dead end.

The two audit-log operations now also **state the counts first** — "3,247 assessments,
including their model versions, thresholds and applicability flags" — because a
confirmation that does not say *how much* is about to go is not informed consent. The
audit purge additionally notes that it erases the record of the purge itself.

## 14.2 — The last of the KPI cards

The 16 remaining call sites are converted by reshaping `_kpi` / `kpi` into shims that
keep the old five-argument signature and **ignore the colour arguments entirely**. That
is the point: every call site passed its own hex plus a gradient plus a border colour,
which is how the dashboards ended up with six competing hues.

Tone is not inferred from the discarded colour — a label mentioning risk gets a clinical
tone and everything else stays neutral, so an inventory count is never painted the same
crimson as a clinical finding.

`_section_header` likewise became an adapter onto `page_header`, retiring
`.hg-title` / `.hg-subtitle` / `.hg-divider`.

**Legacy shim: 24 classes → 8, 3.4 KB → 1.32 KB.** The eight that remain are genuinely
referenced by six admin CRUD pages that this phase restyled but did not rebuild — which
is the correct scope call, not an oversight. Rebuilding them was never in the brief.

## 14.3 — The accessibility audit, computed

§8: *"Verify every risk-band text/surface pair with an actual contrast calculation — do
not eyeball it."* `tests/test_a11y.py` does exactly that, plus Machado et al. (2009)
colour-vision simulation, reproduced inline because §1.3 forbids new dependencies.

**Two real defects found and fixed:**

| | Was | Now |
|---|---|---|
| `text_subtle` (light) | NEUTRAL[500] — **4.12:1** on white, under AA, and it carries 11.5px captions with no large-text exemption | NEUTRAL[550] `#606B7A` — solved against the *darkest* surface a caption sits on: surface 5.41 / canvas 4.99 / sunken 4.57 |
| `text_subtle` (dark) | `#7A8493` — 4.57:1 on the dark surface but **3.42:1** on the dark sunken panel, which is where the peer and reliability captions actually sit | `#98A0AC` — 6.56 / 4.91 |

The light fix carries a trade-off recorded in the token rather than hidden: at
NEUTRAL[550] it is only 1.16:1 from `text_muted`, so the muted/subtle distinction is no
longer legible as a colour difference. **The palette has one neutral text level too many
for AA at caption size**, and the honest resolution is that the remaining hierarchy is
carried by size and weight. Compliance beats a hierarchy nuance nobody can see.

**One defect in my own measurement.** The suite first reported all four dark risk bands
failing at 1.91–2.66:1 — which looked like a serious token bug. The dark band surfaces
are 8-digit hexes (the rail colour at 14% alpha, `#1E8A6A24`), and measuring text against
the raw hex measures it against the full-strength colour, which nobody sees. Composited
correctly they are **7.53–8.90:1**. The tokens were fine. A contrast audit that ignores
alpha is always wrong in this direction: it flags the safe, and would equally miss the
unsafe.

## 14.4 — The colour-blindness finding, stated rather than asserted away

```
protanopia     worst pair low/intermediate = 1.12:1    low/high = 1.94:1
deuteranopia   worst pair low/high         = 1.05:1    low/high = 1.05:1
tritanopia     worst pair low/intermediate = 1.14:1    low/high = 1.29:1
```

**Under deuteranopia the LOW and HIGH rails converge to 1.05:1 — indistinguishable.**
This is intrinsic. Verdigris-to-crimson *is* the red-green axis, §3.10 fixes the Brand
Six, and no reassignment inside those six escapes it.

It is recorded as a measured limitation, not a pass/fail, because a threshold the palette
cannot meet is not a test — it is a wish. What is asserted hard instead is the property
§8 actually requires and that genuinely protects the reader: **no information carried by
colour alone.** For all four bands, by exercising the real components:

- the chip carries its label as text;
- the verdict carries the band label as text, the numeric probability, **and** a rail
  position;
- the rail names every band in text and exposes an `aria-label` stating the value, the
  band and the threshold;
- the reliability rating is a word — Strong / Moderate / Limited.

With the hue collapse measured, that redundancy is not a nice-to-have. It is the only
thing separating the bands for a deuteranopic reader.

## 14.5 — Print and responsive

The print block was two lines. §8 requires the diagnosis result to print legibly on A4
with *"the extrapolation banner visible with its hatch pattern intact"*, and the hatch is
the reason it is now thirty:

- **light tokens are forced**, or a dark-mode user prints near-white ink on white paper;
- **`print-color-adjust: exact`** on every fill and hatch, because browsers drop
  background images when printing — a dark-mode user printing an extrapolated result
  would otherwise get the banner's *text* with no hazard stripe, the caveat stripped of
  the marking that makes it obvious;
- **`break-inside: avoid`** on the banner, verdict, operating point and reliability panel,
  so the one thing that must never be lost to a page break is not;
- shadows suppressed (they print as grey mud) and URL footnotes off.

Breakpoints now cover the four widths §8 names. 1440 is the design width and is handled
by the content-column cap rather than a media query; 1280, 1024 and 768 each have rules.

## 14.6 — `use_container_width` → `width`

72 call sites plus 4 inside the component library. Deprecated since 2025-12-31 and still
only warning, but every one emitted a console warning on **every rerun**. Verified
`width="stretch"` works in this Streamlit version before sweeping.

## 14.7 — Two of my own tests corrected

**The component suite's "no export is left untested" guard fired** on `danger_zone` and
`destructive` the moment I added them — which is exactly what it exists for. That guard
was added in Phase 8 after `data_table` shipped broken and uncalled; it has now caught
its first real omission.

**The Phase 9 snapshot diff was retired, deliberately and with the reason recorded.** It
compared every string literal against a pre-restructure snapshot and returned 0 corrupted
of 2,978 — the result that made the re-indent safe to commit. But it was a *one-time
migration verification against a frozen snapshot*, and Phase 10's 24 intentional
deletions made it report false failures. A test that cries wolf is worse than no test,
because it trains you to ignore it. Replaced with snapshot-free structural guarantees
that hold permanently: eleven `if label in _slot` guards, no orphaned `with tN:` inside
`page_model_performance`, no markdown literal indented into an accidental code block,
and **every tab bar in the application ≤ 4 items**.

That last one immediately caught that my first regex was unscoped and matching
`page_admin_analytics`' own legitimate four-tab layout.

## 14.8 — Phase 10 gate

```
27-path AppTest          27/27 routed, 0 exceptions
py_compile               clean on 16 modules
pyflakes                 no new warnings vs baseline
test_tokens              0 failures   (63 assertions)
test_brand               0 failures   (60)
test_rail                0 failures   (71)
test_components          0 failures   (101 — 18 exports smoke-tested)
test_login               0 failures   (68)
test_diagnosis           0 failures   (76)
test_charts              0 failures   (78)
test_performance_ia      0 failures   (44)
test_a11y                0 failures   (84) + 2 recorded limitations
CSS budget               47.1 KB / 60 KB    emotion-cache selectors: 0
legacy shim              8 classes, 1.32 KB (from 24 classes, 3.4 KB)
KPI cards                0 anywhere in the application
destructive actions      10/10 behind typed confirmation
use_container_width      0 remaining
screenshots              SUBSTITUTED — see 9.0
```

## 14.9 — What the redesign did not do

Recorded plainly rather than left implicit:

- **Screenshots were never possible.** No browser automation exists in this environment
  and §1.3 forbids adding one. Every phase substituted structural comparison against
  `baseline/widget_tree.json` plus targeted matplotlib renders — which is how three
  Phase 7 defects were caught that no assertion had covered. It is weaker than a
  screenshot and was reported as such at every gate.
- **Six admin CRUD pages were restyled, not rebuilt.** Doctor / Prediction / Dataset /
  Admin Management, Role & Permissions and System Settings now use the tokens, the
  component chrome and the gated destructive actions, but their internal layouts are
  original. §7.6 describes a pattern; applying it fully to six more pages was outside
  this brief's ten phases.
- **`register_user` still performs no username character validation.** Defended in depth
  — every render site passes through `esc()`, and the XSS probe confirms no tag can form
  — but the input validation is absent, and fixing it means changing `auth_db`
  authentication logic that §1.1 puts out of bounds.
- **The risk ramp cannot be made colour-blind-safe or luminance-monotonic** inside the
  Brand Six. Both are measured, recorded, and mitigated by redundant encoding.

---

# RUN 15 — The stylesheet was rendering as text (2026-07-28)

Reported from the browser on first load: thousands of lines of CSS printed onto the
sign-in page above the form. It looked like the application was dumping errors. It was
not — it was printing its own stylesheet as prose.

Nothing was wrong with the app's logic. Every automated gate had been green.

## 15.1 — Two causes, both introduced by me

**1. `st.markdown` Markdown-processes its argument before the HTML reaches the page.**
Markdown turns any line indented four or more spaces into a code block. 223 lines of the
stylesheet were indented that far, so the parser cut out of the `<style>` element partway
down the sheet and emitted everything after it as visible text.

The indentation had been there since Phase 1 and was harmless while blank lines separated
the blocks. Phase 6's `_minify()` removed those blank lines to reclaim 12 KB, which
changed how the Markdown parser grouped what followed. The regression was introduced four
phases before it became visible.

**2. Phase 10's `_legacy_block()` rewrite shipped invalid CSS.** It was written through a
shell heredoc with FOUR braces (`{{{{`), so the f-string collapsed them to `{{` in the
output rather than `{`. Twelve rules shipped as `.panel {{ … }}`, and one declaration
shipped as the literal text `font-weight: {T.WEIGHT['semibold']};`.

## 15.2 — Why every check I had was blind to it

This is the part worth keeping.

| Check | Why it passed anyway |
|---|---|
| 27-path AppTest | Sees a markdown element and reports success whether its content renders as a stylesheet or as prose. **It does not render CSS at all.** |
| Brace balance | `{{ … }}` balances perfectly. **Balance is not validity.** |
| "Key selectors present" | `.panel {{` still contains `.panel`. |
| CSS size budget | An invalid sheet weighs the same as a valid one. |
| `_minify()`'s own guard | Checked balance and data-URI count — both of which survived. |

Every one asked whether a string was *present*. None asked whether a browser could
*use* it. That distinction is the same lesson as Run 8's — a test that checks what the
user sees is not a test that the system recorded it — pointed at the other end of the
pipeline.

## 15.3 — The fixes

- **`inject()` now uses `st.html`**, which exists for raw HTML and does no Markdown
  processing. A `st.markdown` fallback remains for older Streamlit.
- **`_minify()` strips leading indentation** from every line. Not cosmetic — it makes the
  payload safe even if a future call site sends it through Markdown again. CSS does not
  need the whitespace, and it saved a further 2 KB.
- **The 12 over-escaped brace lines and the one over-escaped interpolation are fixed.**
- **`* { box-shadow: none }` became `html * { … }`** in the print block. A line beginning
  with an asterisk and a space *is* a Markdown list item; the sheet must stay safe to
  hand to a parser even though it no longer is.

## 15.4 — `tests/test_styles.py`, the suite that should have existed

34 assertions targeting the **delivery mechanism and payload validity**, which is where
the failure actually lived:

- no line begins with whitespace; no blank lines; no line would parse as a Markdown
  block (list marker, fence, heading, blockquote, ordered item)
- no literal doubled braces; no unresolved f-string placeholder; braces balance; every
  declaration block contains at least one `prop: value`; no malformed selectors
- **each of the 11 blocks is checked individually**, not just the assembled sheet —
  both Phase 10 bugs lived in one block, and a whole-sheet assertion would have meant
  grepping 45 KB to find them
- `inject()` uses `st.html`, and after a real run **no markdown element carries the
  stylesheet** — asserted on the signed-in page and the sign-in page separately, since
  the sign-in page is where the failure was visible

Two of those assertions found further real problems on their first run: the unresolved
`{T.WEIGHT['semibold']}` placeholder, and the `* ` selector.

One of them was also wrong on its first run and worth recording: it rejected any line
starting with `-` or `*`, which flags `--hg-border: #D8DDE4;` and `* { … }` — both
ordinary CSS. A Markdown list marker is the character *followed by a space*. It reported
a failure with an empty detail string, which is how I noticed the test was wrong rather
than the stylesheet.

## 15.5 — Gate

```
27-path AppTest         27/27 routed, 0 exceptions
py_compile              clean on 17 modules
pyflakes                no new warnings vs baseline
test_tokens             0 failures     test_login             0 failures
test_brand              0 failures     test_diagnosis         0 failures
test_rail               0 failures     test_charts            0 failures
test_components         0 failures     test_performance_ia    0 failures
test_a11y               0 failures     test_styles            0 failures  (new, 34)
live server             starts clean, /_stcore/health 200, 0 errors in log
CSS                     45.0 KB / 60 KB   0 doubled braces   0 indented lines
```

## 15.6 — What this changes about the earlier claim

I said after Phase 10 that I could not claim "no UI errors" because no browser
automation exists and `AppTest` does not render CSS. This bug is exactly that gap
realised: the app was clean by every measure I had and visibly broken on first load.

The new suite closes the specific hole — a stylesheet that cannot reach the browser
intact is now a test failure rather than a surprise. It does **not** close the general
one. Layout, spacing, overlap and anything else that depends on how a browser lays out
correct CSS remain unverified, and the only way to check them is to look.
