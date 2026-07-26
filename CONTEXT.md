# HeartGuard AI — Engineering Context & Audit Register

> **Document type:** Working state of the codebase — what is broken, what was measured, what to do next, and which traps to avoid.
> For the system description (architecture, schema, pipeline, page inventory), see [PROJECT.md](PROJECT.md).
>
> **Audit date:** 2026-07-26 · **Auditor:** ML engineering review · **Codebase:** 4,746 LOC application code
> Every number in this document was **measured against the live artifacts**, not estimated. §7 gives reproduction commands.

---

## 1. Status snapshot

> **UPDATED 2026-07-26 (Run 3).** All 21 bugs in §2 have been **fixed and verified**. This section
> now reflects the post-fix state; the findings below are retained as the historical record of what
> was wrong and why, because the reasoning is what keeps them from being reintroduced.
> Full change log: [TASK.md](TASK.md) Run 3.

| Dimension | Before | Now | Notes |
|---|---|---|---|
| Application layer | 🟢 Solid | 🟢 **Solid** | Unchanged strengths; crash in Model Performance removed |
| ML data pipeline | 🔴 Broken | 🟢 **Correct** | 0-indexed encoding + retention guardrail; 68,645 of 70,000 rows retained |
| Inference path | 🔴 Broken | 🟢 **Correct** | Form and training share one encoding and one feature builder |
| Reported metrics | 🔴 Invalid | 🟢 **Valid** | Best AUC 0.7246 → **0.8000** on a 13,729-row honest holdout |
| Probability calibration | 🔴 Unsafe | 🟢 **Measured** | ECE 0.0103, mean predicted 0.4949 vs prevalence 0.4947 |
| Authentication | 🔴 Broken | 🟢 **Fixed** | Registration locked to Doctor; PBKDF2 hashing |
| Deserialization safety | 🔴 RCE | 🟢 **Hardened** | Allowlist + SHA-256 manifest verification |
| Methodology | 🟠 Weak | 🟢 **Sound** | All preprocessing fitted post-split; CV on training split only |
| Code hygiene | 🟠 Weak | 🟠 **Weak** | ~650 dead lines and the 1,480-line function remain; still no tests or VCS |

### The headline — what was wrong, and what fixing it bought

`train_models.py` filtered `cholesterol` and `gluc` to `{1,2,3}`, but this copy of the dataset encodes them as `{0,1,2}`. The filter therefore kept only patients with **both** elevated cholesterol **and** elevated glucose — 6,583 of 64,825 valid rows — shifting disease prevalence from 50.9% to 65.7%. Every model, metric and SHAP plot described that metabolic-syndrome sub-cohort. The Streamlit form compounded it by sending 1/2/3 to models trained on 0/1/2, so "Normal" scored as *above normal* and "Well Above Normal" landed outside the training range entirely.

**Fixed in Run 3.** Correcting the constant, adding a retention guardrail, and deduplicating before the age conversion recovered **68,645 training rows (10.4× more)**, restored population-representative prevalence (49.5%), and lifted best AUC from **0.7246 to 0.8000**. Mean predicted probability now lands within 0.0002 of true prevalence, so the under-prediction that made the tool clinically unsafe resolved without needing a calibration wrapper.

---

## 2. Findings register

Severity: **C** critical (blocks correctness or safety) · **H** high · **M** medium · **L** low.

### C1 — Category encoding mismatch discards 89.8% of the dataset

**Location:** [train_models.py:211-213](train_models.py#L211-L213)

```python
for col in ["cholesterol", "gluc"]:
    if col in df.columns:
        masks.append(df[col].isin([1, 2, 3]))
```

**Root cause.** The canonical Kaggle Cardiovascular dataset encodes these ordinals as 1/2/3. *This* CSV has been re-encoded to 0/1/2 (as has `gender`, 0/1 rather than 1/2). The filter was written against the upstream convention and never revalidated.

**Measured impact.**

| | Rows | Prevalence |
|---|---:|---:|
| Valid after physiological filters | 64,825 | 50.9% |
| After `cholesterol.isin([1,2,3])` | 17,088 | — |
| After `gluc.isin([1,2,3])` | **6,583** | **65.7%** |

Retention: **10.2%**. Survivors have elevated cholesterol *and* elevated glucose — a metabolic-syndrome cohort, not a screening population. `scaler.mean_[6] = 1.590` confirms no normal-cholesterol patient was ever seen.

**Secondary damage.** Within the surviving cohort `cholesterol` and `gluc` have almost no variance, so the models learned to nearly ignore them — Random Forest assigns them 4.3% and 2.2% importance, below `height` (9.9%). Two of the strongest cardiovascular predictors in the data were rendered inert.

**Fix.** Change to `.isin([0, 1, 2])` and add a retention assertion (§4, step 1).

---

### C2 — Train/serve skew on the inference path

**Location:** [app.py:440-445](app.py#L440-L445) · compounded at [app.py:474](app.py#L474)

The diagnosis form emits 1/2/3; the models were trained on {1,2} of a 0-based scale.

| UI label | Value sent | z-score produced | Status |
|---|---:|---:|---|
| Normal | 1 | −1.20 | is actually *"above normal"* in dataset terms |
| Above Normal | 2 | +0.83 | maximum value ever observed in training |
| Well Above Normal | 3 | **+2.87** | **never seen — pure extrapolation** |

Training range is z ∈ [−1.20, +0.83]. Selecting the highest-risk option pushes the model 3.4σ beyond anything it has been fitted on.

`high_risk_flag = int(cholesterol >= 2 and ap_hi >= 140)` means "Above Normal or worse" against the form's scale but "Well Above Normal only" against the training data — the flag fires on a different population at serve time than at train time.

**Measured probability shift** (65yo male, 165 cm, 95 kg, BP 170/100, smoker, inactive): ensemble 84.9% as coded vs 83.9% correctly encoded. The shift looks small **only because C1 already destroyed the models' sensitivity to these features.** Fix C1 alone and this delta grows sharply — **C1 and C2 must be fixed in the same commit.**

---

### C3 — Public registration grants SuperAdmin

**Location:** [app.py:345-348](app.py#L345-L348)

```python
r_role = st.selectbox("Login As", ["Doctor", "Admin", "SuperAdmin"], ...)
```

The unauthenticated Register tab lets a visitor choose their own role. `register_user()` writes it verbatim ([auth_db.py:100](auth_db.py#L100)) with no server-side check.

**Confirmed exploited in the live database:** three accounts hold `SuperAdmin` — `superadmin` (seeded), plus `doctor` and `zarqa`, both self-elevated. `page_role_permissions` displays a capability matrix that this path bypasses entirely, and the `allow_registration` setting that ought to gate it is never read (M3).

**Fix.** Hard-code `"Doctor"` at registration; elevation only via [pages_ext.py:646](pages_ext.py#L646).

---

### C4 — Pickle deserialization RCE via Backup & Restore

**Location:** [pages_ext.py:795-801](pages_ext.py#L795-L801) → [app.py:213-216](app.py#L213-L216)

```python
for member in members:
    if member.startswith("backup/models/"):
        fname = member.split("/")[-1]          # path traversal blocked …
        dest = os.path.join(MODELS_DIR, fname) # … but content is unvalidated
        with zf.open(member) as src, open(dest, "wb") as dst:
            dst.write(src.read())
```

Filenames are sanitised, but any `.pkl` written here is later `pickle.load`ed by `load_models()`. A crafted `__reduce__` executes arbitrary code on the next model load. **Chained with C3 this is unauthenticated remote code execution**: register as SuperAdmin → upload a zip → visit any page.

**Fix.** Allowlist the six known filenames, migrate to `joblib` with a manifest of SHA-256 digests written at train time, and refuse any artifact whose digest is unknown.

---

### C5 — Systematic under-prediction of risk

The shipped `.pkl` files scored against all 64,825 valid patients:

| Model | AUC | Accuracy | Brier | Mean predicted risk | Flagged high |
|---|---:|---:|---:|---:|---:|
| Logistic Regression | 0.7824 | 0.6616 | 0.2171 | **36.0%** | 26.1% |
| SVM | 0.7820 | 0.7163 | 0.1924 | 48.7% | 42.8% |
| Decision Tree | 0.7497 | 0.7011 | 0.2126 | 42.3% | 38.4% |
| Random Forest | 0.7928 | 0.7274 | 0.1900 | 44.0% | 40.1% |
| XGBoost | 0.7852 | 0.7199 | 0.1921 | 44.9% | 41.1% |
| **Ensemble (app default)** | **0.7950** | 0.7219 | 0.1915 | **43.2%** | 38.2% |

True prevalence is **50.9%**. The ensemble under-states population risk by **7.7 points**; Logistic Regression by **14.9**.

The UI renders this as `Risk Probability: 43.2%` next to *"No significant cardiovascular risk patterns detected."* **For a screening tool, under-prediction is the harmful direction** — it produces false reassurance.

**Causes, in order:** C1's cohort selection; `class_weight='balanced'` on four of five models deliberately distorting probabilities; no calibration stage; `cholesterol=0` inputs mapping to z = −3.23, far below anything in training, dragging linear models down hard.

**Fix.** After C1, wrap the final estimator in `CalibratedClassifierCV(method='isotonic', cv=5)` on a held-out slice and add a reliability diagram to Tab 7.

---

### H1 — Preprocessing fitted before the train/test split

Steps 5, 6 and 8 run on the full frame; the split happens at step 9.

| Step | Line | Leak |
|---|---|---|
| IQR winsorization | [train_models.py:363-366](train_models.py#L363-L366) | Quantiles computed over test rows |
| Median imputation | [train_models.py:368-369](train_models.py#L368-L369) | Medians computed over test rows |
| Correlation pruning | [train_models.py:375-376](train_models.py#L375-L376) | Feature selection sees test labels' covariates |

Measured impact on this data is small — but it is the first thing an examiner will circle, and it invalidates the holdout as an unbiased estimate. **Fix:** move all three into an `sklearn.Pipeline` fitted inside the split.

---

### H2 — K-fold cross-validation is not independent

**Location:** [train_models.py:493-512](train_models.py#L493-L512)

```python
X_all_s = scaler.transform(X)          # scaler was fit on X_train
... cross_validate(mobj, X_all_s, y.values, cv=skf, ...)
```

Two defects: the scaler was fitted on 80% of the rows that now appear in CV *test* folds, and every fold's test set overlaps the original training split. `cross_validate` refits the estimator per fold, so the damage is bounded — CV AUC 0.7240 vs holdout 0.7245 — but Tab 7 presents this as independent evidence of generalisation, which it is not.

**Fix.** Cross-validate a `Pipeline` (scaler + estimator) over the **training split only**.

---

### H3 — Winsorization destroys the strongest clinical signal

**Location:** [train_models.py:229-247](train_models.py#L229-L247), applied at [:363](train_models.py#L363)

Measured clipping on the 6,583-row cohort:

| Column | IQR bounds applied | Rows altered | True range |
|---|---|---:|---|
| `ap_hi` | [90, 170] | 190 | 70–220 |
| `ap_lo` | [65, 105] | 301 | 40–182 |
| `weight` | [36, 120] | 140 | 31–183 |
| `height` | [142, 186] | 51 | 120–198 |
| `age` | [40, 72] | 22 | 39–65 |

**181 patients with true systolic BP above 170 — carrying an 89.0% cardio rate — are flattened to the cap.** In a cardiovascular dataset, blood-pressure outliers *are the disease*, not noise. Step 4 already bounds these fields to physiologically plausible ranges; step 5 then deletes the signal inside those bounds.

**Fix.** Drop IQR winsorization for `ap_hi`, `ap_lo`, `weight`. Step 4's domain rules are sufficient.

---

### H4 — Age rounding fabricates 3,821 duplicates

**Location:** [train_models.py:167-168](train_models.py#L167-L168) runs before [:179](train_models.py#L179)

Converting age from days to whole years collapses patients who differ only by days into identical rows, which `drop_duplicates()` then deletes.

| | Duplicates |
|---|---:|
| Before age rounding | **24** |
| After age rounding | **3,821** |

**3,797 distinct patients deleted for no reason.**

**Fix.** Deduplicate first, then convert age — or keep age in days and let the model use the finer resolution.

---

### H5 — Median imputation is a silent no-op under pandas 3

**Location:** [train_models.py:261](train_models.py#L261)

```python
df[col].fillna(med, inplace=True)
```

Under pandas 3.0.3 (installed) this raises `ChainedAssignmentError` and **never writes** — verified experimentally: NaN count unchanged after the call. Harmless on `heart.csv` (no missing values), but any dataset uploaded through Dataset Management that contains NaNs will pass them straight into `StandardScaler.fit`.

**Compounding factor:** `warnings.filterwarnings("ignore")` at [train_models.py:26](train_models.py#L26) suppresses the diagnostic. That line is actively hiding bugs and should be removed.

**Fix.** `df[col] = df[col].fillna(med)`.

---

### H6 — Every published metric describes the wrong population

A leak-free pipeline over the full 64,825 rows (no chol/gluc truncation, no BP winsorization, scaler inside the split), evaluated on an honest 12,965-row holdout:

| Model | Shipped (reported in UI) | Corrected | Δ AUC |
|---|---:|---:|---:|
| Logistic Regression | 0.7245 | **0.7899** | +0.065 |
| Random Forest | 0.7159 | **0.7994** | +0.084 |
| XGBoost | 0.7152 | **0.7997** | +0.085 |

Corrected Brier scores land at 0.181 against the shipped 0.19–0.22. **Fixing C1 improves every metric while multiplying training data tenfold** — the current numbers under-sell the project.

---

### H7 — Unsalted SHA-256 password hashing

**Location:** [auth_db.py:10-11](auth_db.py#L10-L11)

```python
return hashlib.sha256(password.encode()).hexdigest()
```

No salt, no key-derivation, no work factor. Identical passwords produce identical digests; rainbow tables break this instantly. Registration enforces only a 6-character minimum ([app.py:353](app.py#L353)). All three default credentials are printed on the login page ([app.py:307-315](app.py#L307-L315)).

**Fix.** `bcrypt` or `argon2-cffi`, with a one-time migration that re-hashes on next successful login.

---

### M1 — "Top Risk Factors" is global importance mislabelled as patient explanation

**Location:** [app.py:543-597](app.py#L543-L597)

The chart beside a patient's individual result renders `model.feature_importances_` — a static, model-level ranking **identical for every patient**. It is captioned "Top Risk Factors (model-based importance)" directly under that patient's risk score, which reads as personalised reasoning.

`shap 0.52.0` is installed and a working `TreeExplainer` already exists at [app.py:2364](app.py#L2364). **Fix:** replace with a per-patient SHAP waterfall.

---

### M2 — SHAP background distribution ≠ training distribution

**Location:** [app.py:2333-2357](app.py#L2333-L2357)

The background sample is drawn from raw `heart.csv` with no domain filter, so ~80% of it carries `cholesterol=0` / `gluc=0` — values no model ever saw. SHAP attributions are therefore computed over a distribution disjoint from the training manifold.

---

### M3 — Configured settings are never enforced

**Location:** [pages_ext.py:662-724](pages_ext.py#L662-L724)

`system_settings.json` is written, read back and displayed — but no consumer exists anywhere in the codebase:

| Setting | Enforced? | Reality |
|---|---|---|
| `risk_threshold` | ❌ | Hardcoded `>= 0.5` at [app.py:488](app.py#L488) |
| `max_predictions_per_day` | ❌ | No rate limiting exists |
| `session_timeout_min` | ❌ | No expiry; sessions live until browser close |
| `allow_registration` | ❌ | Register tab always rendered |

Verified by grep: these keys appear only in the settings page itself. This is UI theatre and will not survive a demo question.

---

### M4 — Ensemble averages incommensurable probabilities

**Location:** [app.py:487](app.py#L487)

`np.mean()` over an isotonic-calibrated SVM, a depth-7 tree emitting coarse leaf frequencies, and three other uncalibrated estimators. Unweighted averaging assumes comparable calibration; none of them are. Weight by validation AUC, or calibrate all members first.

---

### M5 — Two different decision rules

Ensemble path thresholds `mean_prob >= 0.5`; single-model path calls `model.predict()`. The same patient can be scored by different rules depending on a dropdown. Unify on an explicit, configurable threshold (which also resolves half of M3).

---

### M6 — `subprocess.run(["python", ...])` instead of `sys.executable`

**Location:** [app.py:1003](app.py#L1003)

Resolves `python` from PATH. Launched outside an activated venv, this hits a system interpreter that may lack XGBoost — training silently degrades to `GradientBoostingClassifier` — or lack scikit-learn entirely and fail. **Fix:** `sys.executable`.

---

### M7 — No artifact provenance

Nothing records which dataset, code revision or library versions produced a given `.pkl`. `preprocess_report.txt` still shows `C:\Users\Ariha\Desktop\self project\HeartGuard FYP\heart.csv` — a path from a different machine — so the committed artifacts cannot be traced to a reproducible run. Training overwrites all artifacts in place with no backup.

**Fix.** Emit `models/manifest.json` at train time: dataset SHA-256, row count, timestamp, library versions, git revision, per-artifact digest.

---

### M8 — Stored XSS via profile fields

**Location:** [app.py:375-378](app.py#L375-L378)

```python
st.sidebar.markdown(f"""
<div ...>{user['fullname']}</div>
<div ...>@{user['username']}</div>
<div ...>{user.get('email', '')}</div>
""", unsafe_allow_html=True)
```

All three fields are user-controlled at registration and in Profile Settings, and are interpolated into raw HTML without escaping. The codebase uses `unsafe_allow_html` **86 times** (55 in `app.py`, 31 in `pages_ext.py`). Streamlit strips `<script>` in current versions, but attribute-based vectors are not reliably filtered. **Fix:** `html.escape()` on every interpolated user-supplied value.

---

### M9 — Repository hygiene

`heartguard.db` (8 real accounts including password hashes), `__pycache__/` with mixed cpython-313/314 bytecode, and an 11 MB `random_forest.pkl` all sit in the working tree. `heart_bg_b64.txt` (68 KB) is unreferenced — `get_bg_b64()` looks for `heart_bg.png`, which does not exist, so it always returns `None`.

---

### L1–L5 — Lower priority

- **L1** ~650 lines of dead code: `pages_ext.page_model_performance` (353 L, shadowed), `app.page_help` (38 L, unrouted), `app.page_admin_users` (66 L, unrouted), and four one-shot scripts (`check.py`, `fix_indent.py`, `fix_all_indent.py`, `fix_unicode.py`, 193 L).
- **L2** `page_model_performance` is a single **1,480-line function** ([app.py:1157-2640](app.py#L1157-L2640)).
- **L3** Zero tests. No `pytest`, no fixtures, no CI.
- **L4** Not a git repository — no history, no branches, no rollback.
- **L5** Documentation errors in the unrouted `page_help`: claims Random Forest uses 150 trees (code trains 200); risk bands "Low (<50%) / Borderline (40–59%) / High (≥60%)" overlap at 40–49% and leave 50–59% unclassified while the code thresholds hard at 50%.
- **L6** `PRAGMA foreign_keys` is never enabled, so the `ON DELETE CASCADE` on `predictions.user_id` does nothing — deleting a user orphans their prediction rows.
- **L7** The Patient ID field is required by the form but never persisted; only `patient_name` reaches the database.

---

## 3. Severity roll-up

| | Count | IDs |
|---|---:|---|
| 🔴 Critical | 5 | C1 C2 C3 C4 C5 |
| 🟠 High | 7 | H1 H2 H3 H4 H5 H6 H7 |
| 🟡 Medium | 9 | M1–M9 |
| ⚪ Low | 7 | L1–L7 |
| **Total** | **28** | |

**Two exploit chains:**
- `C3 → C4` = unauthenticated remote code execution.
- `C1 → C2 → C5` = clinically unsafe risk scores presented as authoritative percentages.

---

## 4. Remediation roadmap

Ordered by leverage. Steps 1 and 2 are what change the project's standing.

### Step 1 — Fix the data contract *(≈1 hour, highest payoff)*

**1a.** [train_models.py:213](train_models.py#L213)
```python
masks.append(df[col].isin([0, 1, 2]))
```

**1b.** Add a retention guard immediately after the mask combination in `_domain_filter` — this single assertion would have caught the bug on day one:
```python
retained = len(df) / max(before, 1)
assert retained > 0.80, (
    f"Domain filter dropped {1-retained:.1%} of rows — check categorical encodings"
)
```

**1c.** [app.py:440-445](app.py#L440-L445)
```python
cholesterol = st.selectbox("Cholesterol Level",
    [(0, "Normal"), (1, "Above Normal"), (2, "Well Above Normal")],
    format_func=lambda x: x[1])[0]
gluc = st.selectbox("Glucose Level",
    [(0, "Normal"), (1, "Above Normal"), (2, "Well Above Normal")],
    format_func=lambda x: x[1])[0]
```

**1d.** Update `high_risk_flag` to the 0-based threshold in **all three** copies — [train_models.py:296](train_models.py#L296), [app.py:474](app.py#L474), [app.py:2349](app.py#L2349) — and the label map at [app.py:608](app.py#L608) to `{0:'Normal', 1:'Above Normal', 2:'Well Above Normal'}`.

**1e.** Retrain. Expect ~64,800 rows, ~50.9% prevalence, AUC ≈ 0.80.

> ⚠ Steps 1a and 1c must ship together. Fixing the filter without the form leaves the app sending `3` to a model whose maximum is now `2`.

### Step 2 — Close the security holes *(≈2 hours)*

- **C3:** replace the role selectbox with a fixed `"Doctor"`.
- **C4:** allowlist restore filenames; add digest verification.
- **H7:** move to `bcrypt`; re-hash on next login.
- **M8:** `html.escape()` on every user-controlled interpolation.

### Step 3 — Rebuild the pipeline honestly *(≈3 hours)*

- **H1:** wrap steps 5/6/8 in `sklearn.Pipeline`, fitted inside the split.
- **H3:** drop IQR winsorization for `ap_hi`, `ap_lo`, `weight`.
- **H4:** deduplicate before converting age.
- **H5:** `df[col] = df[col].fillna(med)`; delete `warnings.filterwarnings("ignore")`.
- **H2:** cross-validate the pipeline over the training split only.
- **M6:** `sys.executable`.

### Step 4 — Calibrate *(≈2 hours — strong report material)*

Wrap the final estimator in `CalibratedClassifierCV(method='isotonic', cv=5)`, add a reliability diagram and Expected Calibration Error to Tab 7, and re-measure mean predicted risk against true prevalence. **For a clinical tool, calibration matters more than accuracy** — and a before/after reliability plot is a compelling dissertation figure.

### Step 5 — Patient-level explanations *(≈2 hours)*

Replace the global importance chart (M1) with a per-patient SHAP waterfall. Apply the domain filter to the SHAP background (M2).

### Step 6 — Wire up or remove the fake settings *(≈1 hour)*

Make `risk_threshold` and `allow_registration` real (M3), unify the decision rule (M5). Delete anything that stays decorative.

### Step 7 — Hygiene *(≈1 hour)*

`git init` with a `.gitignore` covering `*.db`, `__pycache__/`, `*.pkl`, `.venv/`, `custom_dataset.csv`. Delete the four `fix_*` scripts, the shadowed `page_model_performance`, and the unrouted `page_help` / `page_admin_users`. Emit `models/manifest.json` (M7).

**Total: ~12 focused hours to move from "broken ML core behind a good UI" to a defensible clinical decision-support prototype.**

---

## 5. Traps for future work

Read this before touching anything.

1. **The dataset is 0-indexed.** `cholesterol`/`gluc` ∈ {0,1,2}; `gender` 0 = female, 1 = male. Every reference to "1/2/3" in this codebase is a bug, not a convention.
2. **Feature engineering exists in three unsynchronised copies** — [train_models.py:269](train_models.py#L269), [app.py:461](app.py#L461), [app.py:2339](app.py#L2339). Changing one and not the others silently corrupts predictions. Extract to a shared module.
3. **Feature order is positional and unvalidated.** `models/features.json` is the contract. Nothing at inference verifies it — `scaler.transform` accepts any 15-vector.
4. **Model artifacts are a matched set.** The scaler and five estimators come from one run. A partial restore produces plausible-looking garbage with no error.
5. **`import auth_db` creates the database.** Any script that imports it touches `heartguard.db`.
6. **`warnings.filterwarnings("ignore")`** at [train_models.py:26](train_models.py#L26) is hiding real errors, including H5. Remove it before debugging anything in the pipeline.
7. **Training overwrites all artifacts in place**, with no backup and no versioning. Copy `models/` before retraining.
8. **`config.json` keys must match `load_models()` labels byte-for-byte**, including `"Support Vector Machine (SVM)"` with its parenthetical.
9. **`results.json` keys drive all eight evaluation tabs.** Renaming a model breaks the entire Model Performance page.
10. **pandas 3.0.3 is installed** while `requirements.txt` says `>=2.0`. Chained-assignment idioms that worked in pandas 2 are no-ops now.
11. **Python 3.14.6 is installed** while the requirements header claims 3.11–3.13 tested.
12. **There is no version control.** Back up manually before any large refactor.

---

## 6. Decisions and open questions

### Settled by evidence

| Question | Answer |
|---|---|
| Is `isin([1,2,3])` intentional filtering? | **No.** It is an encoding bug. 89.8% attrition with no assertion, and the code comment says "encoded as 1-3 (not outside range)" — the author believed it was a no-op guard. |
| Do the models actually perform badly? | **No.** They score AUC 0.78–0.79 on the full population. The *reported* 0.72 is an artefact of evaluating on a range-restricted cohort. |
| Is the encoding shift (C2) numerically severe today? | **Not yet** — C1 already suppressed the models' sensitivity to these features. It becomes severe the moment C1 is fixed. |
| Is the SQL layer injectable? | **No.** All statements are parameterised throughout `auth_db.py`. |
| Is the RBAC row-scoping sound? | **Yes.** `get_predictions(user_id=...)` scoping is applied consistently. The weakness is role *assignment* (C3), not enforcement. |

### Open — need the project owner's call

1. **Retrain now or after Step 3?** Retraining after Step 1 alone gives correct data with a leaky pipeline; after Step 3 gives publishable methodology. Recommendation: retrain after Step 1 to confirm the ~0.80 AUC, then again after Step 3 for final numbers.
2. **Keep five models?** They span only 0.75–0.79 AUC. A tuned XGBoost plus Logistic Regression as an interpretable baseline would be a stronger, more defensible story — but the comparison table is good FYP material. Recommendation: keep all five for the report, deploy the calibrated best.
3. **Operating threshold?** 0.5 is arbitrary for screening. Cardiovascular triage normally favours sensitivity — a threshold near 0.35–0.40 would be defensible and should be justified explicitly in the report.
4. **Scope of the clinical disclaimer.** The downloadable report carries one; the on-screen verdict card does not.

---

## 7. Reproducing the measurements

Run from the project root with the venv interpreter (`.\.venv\Scripts\python.exe`).

**C1 — row attrition**
```python
import pandas as pd, numpy as np
d = pd.read_csv('heart.csv').drop(columns=['Unnamed: 0','id'])
d['age'] = (d['age']/365.25).round(0).astype(int)
d = d.drop_duplicates().reset_index(drop=True)
m = ((d.ap_hi.between(60,250)) & (d.ap_lo.between(40,200)) & (d.ap_hi>d.ap_lo)
     & (d.height.between(100,250)) & (d.weight.between(20,300)))
print('valid:', m.sum(), 'prevalence:', d.cardio[m].mean())
m2 = m & d.cholesterol.isin([1,2,3]) & d.gluc.isin([1,2,3])
print('after chol/gluc filter:', m2.sum(), 'prevalence:', d.cardio[m2].mean())
```
Expect `64825 / 0.509` then `6583 / 0.657`.

**C5 — calibration on the full population**
Rebuild the 15 features on all valid rows, `scaler.transform`, then compare `predict_proba(...)[:,1].mean()` against `y.mean()`. Expect ensemble 43.2% vs 50.9%.

**H4 — fabricated duplicates**
```python
d = pd.read_csv('heart.csv').drop(columns=['Unnamed: 0','id'])
print('before rounding:', d.duplicated().sum())          # 24
d['age'] = (d['age']/365.25).round(0).astype(int)
print('after rounding: ', d.duplicated().sum())          # 3821
```

**H5 — silent imputation failure**
```python
d = pd.DataFrame({'a':[1.0, None, 3.0]})
d['a'].fillna(d['a'].median(), inplace=True)
print('NaNs remaining:', d['a'].isna().sum())            # 1 → no-op confirmed
```

**H6 — corrected baseline**
Full 64,825 rows, no chol/gluc truncation, no winsorization, `Pipeline([StandardScaler(), estimator])`, `train_test_split(test_size=0.2, random_state=42, stratify=y)`. Expect LR 0.7899 · RF 0.7994 · XGB 0.7997.

---

## 8. Change log

| Date | Run | Change |
|---|---|---|
| 2026-07-26 | 1 | Initial full audit. 28 findings across 4,746 LOC. All measurements verified against live artifacts. No source files modified. |
| 2026-07-26 | 2 | Runtime bug hunt via `streamlit.testing.v1.AppTest` — executed all 27 page×role paths. Found BUG-01, a hard crash killing the Model Performance page for every role. 24/27 passing. |
| 2026-07-26 | 3 | **All 22 bugs fixed and verified** (21 audited + BUG-22 surfaced during post-fix probing: the retention guardrail could not detect a 1-indexed dataset). New `feature_engineering.py` module owns the encoding contract and auto-normalises 1/2/3 inputs; `train_models.py` rewritten leak-free; models retrained (AUC 0.7246 → 0.8000 on 68,645 rows); PBKDF2 auth; restore hardened with allowlist + digest verification; 27/27 page×role paths passing. See [TASK.md](TASK.md) Run 3. |

### Status of the original 28 findings

| Group | Status |
|---|---|
| C1–C5, H1–H7, M3–M9, L5–L7 (the 21 tracked bugs) | ✅ **Fixed in Run 3** |
| M1 — global importance mislabelled as patient explanation | ⏳ Open — needs per-patient SHAP waterfall |
| M2 — SHAP background ≠ training distribution | ✅ Fixed in Run 3 (domain filter now applied) |
| M7 — no artifact provenance | ✅ Fixed — `models/manifest.json` |
| L1 — ~650 dead lines | ⏳ Open |
| L2 — 1,480-line function | ⏳ Open |
| L3 — no tests | ⏳ Open |
| L4 — no version control | ⏳ Open |

---

**Next action:** the correctness and security work is done. Remaining value is in §4 Steps 5–7 — per-patient SHAP explanations (M1), dead-code removal (L1), and `git init` (L4).
