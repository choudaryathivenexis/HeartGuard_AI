---
title: HeartGuard AI
emoji: 🫀
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# HeartGuard AI

Cardiovascular risk screening. A Flask web application over five trained estimators,
with the model's operating point, applicability and reliability disclosed on every
result.

<!-- The YAML block above is Hugging Face Spaces configuration; it has to be the first
     thing in README.md and it has to live in this file, which is why it sits above the
     title. GitHub shows it as plain text at the top of the rendered page - the cosmetic
     cost of one repository serving as both the source and the Space. -->

> **Live demo:** deployed on Hugging Face Spaces. The database is recreated whenever the
> Space restarts or rebuilds, so it holds demonstration data only — see *Deploying* below.

---

## Running it

```bash
pip install -r requirements.txt
python app.py                      # development, http://localhost:5000
python wsgi.py                     # production (waitress), port 8000
```

Seed accounts are printed to the console the first time the database is created. They
are never shown in the browser.

Use `wsgi.py` for anything reachable by someone else. `app.py` runs Werkzeug's
development server, which is single-process and not hardened against malformed or slow
requests.

---

## Deploying

Two configurations ship with the project. **Hugging Face Spaces needs no payment
details**; Render's free plan now asks for a card even though it does not charge one.

### Hugging Face Spaces (no card required)

Create a Space with **SDK: Docker**, then push this repository to it:

```bash
git remote add hf https://huggingface.co/spaces/<your-user>/heartguard-ai
git push hf main
```

The `Dockerfile` and the YAML block at the top of this file are all the configuration
needed. Free CPU tier gives 2 vCPU and 16 GB RAM — comfortable, against a measured peak
of 333 MB with all five models loaded and a SHAP explanation computed.

One detail the Dockerfile handles and which is easy to miss elsewhere: xgboost's wheel
links against OpenMP at runtime, so `libgomp1` must be installed or the container builds
cleanly and then dies on first import.

### Render (free plan, but asks for a card)

`render.yaml` is a Blueprint: **New → Blueprint** in the dashboard, pick this
repository, Apply. Runtime, commands, health check and environment variables all come
from that file.

### Either way: there is no persistent disk

**This matters before you show it to anyone:**

| | behaviour |
|---|---|
| First boot | schema created, three seed accounts printed to the Render log |
| While running | assessments save and behave normally |
| After a redeploy or restart | **the database is recreated empty** |
| After 15 minutes idle | instance sleeps; next request takes 30–60s to unpickle the models |

That is the right trade for a demonstration URL and the wrong one for real records. To
make data persist, the database has to move off the container — free managed Postgres
(Neon, Supabase) is the usual answer, and `backend/repositories/` is the only package
that would change.

`HEARTGUARD_SECRET_KEY` is generated once by Render and held thereafter, so sessions
survive a restart. Without it the application falls back to a key written into
`system_settings.json`, which lives on the ephemeral disk — a new key on every boot, and
every user silently signed out.

Verified against a simulated fresh container (no database, no settings file): boots,
seeds, signs in, scores a patient, and serves the PDF and both charts.

---

## Structure

The one rule: **dependencies point inwards.** `web` knows about `services`, `services`
know about `domain`/`ml`/`repositories`, and nothing below `web` imports Flask except
`services/auth`, which owns the session. That is what keeps the clinical logic callable
from a script or a test with no web context — and it is what makes the route tests
possible.

```
app.py                      launcher; builds the app and runs it

backend/
  config.py                 EVERY path in the project, resolved once
  __init__.py               the application factory

  domain/                   what the numbers MEAN — no I/O, no framework
    risk.py                 thresholds, the four risk bands, the verdict
    artifacts.py            readers for the files training produced
    baselines.py            clinical reference model

  repositories/             data access, one module per stored thing
    connection.py           opening the database, creating the schema
    security.py             password hashing and verification
    users.py                accounts, authentication, roles
    patients.py             patient entities and their timeline
    predictions.py          assessments and recorded outcomes
    audit.py                activity log and training runs

  ml/                       one module per question it answers
    features.py             encode indicators into the model's feature row
    registry.py             load the scaler and estimators once per process
    versioning.py           which artifacts are loaded
    applicability.py        is this patient inside the training envelope?
    percentile.py           where this estimate sits among peers
    explain.py              per-patient SHAP attribution
    figures.py              the SHAP waterfall figure
    counterfactuals.py      what would change this estimate
    pdf.py                  the multi-page clinical report
    charts.py               palette, axes styling, PNG output

  services/                 orchestration — what a route actually calls
    auth.py                 sign-in, session, role-based access control
    screening.py            score a patient, explain it, persist it
    reporting.py            PDF and text reports, rebuilt from the stored row
    analytics.py            dashboard and analytics aggregations

  web/                      routes ONLY; no logic, no SQL
    auth, dashboard, screening, patients, reports,
    performance, admin, system, account, charts

frontend/
  templates/                base layout, 17 pages, shared macros
  static/css/app.css        generated — do not edit by hand
  design/                   brand lockup, icons, illustrations, CSS builder

shared/                     used by both sides
  tokens.py                 THE definition of every colour and size
  formatting.py             number and clinical-vocabulary formatters

tests/                      plain scripts: `python tests/test_routes.py`
train_models.py             offline training; writes models/
```

---

## Two conventions worth knowing before editing

**Paths.** No module derives a path from its own `__file__`. Everything resolves from
`PROJECT_ROOT` in `backend/config.py`. Deriving paths locally is what once made the
data layer create an empty database beside itself after being moved — silently, and it
looked exactly like data loss.

**Colour.** `shared/tokens.py` is the only place a colour is defined. The stylesheet is
generated from it:

```bash
python -m frontend.design.build_css      # rewrites frontend/static/css/app.css
```

Editing `app.css` directly means the next build silently discards your change.

---

## Clinical behaviour that is deliberate

- **The decision threshold is not 0.5.** It comes from the holdout ROC, taken as the
  highest threshold still achieving 85% sensitivity. Screening triages rather than
  diagnoses, so a missed case costs far more than a false alarm — at 0.50 the model
  missed 31% of diseased patients.
- **Thresholds are age-stratified.** A single cut-point gives 63% sensitivity for
  under-45s while flagging 95% of over-60s. Framingham, SCORE2 and QRISK3 all stratify
  by age for the same reason.
- **Impossible measurements are refused, not scored.** A 90/180 blood pressure is not a
  patient outside the training range, it is not a blood pressure.
- **Extrapolation is disclosed and the peer comparison is withheld** when an indicator
  falls outside the fitted range. Ranking an 82-year-old against 60-65 year-olds and
  reporting them as typical is worse than reporting nothing.
- **Counterfactuals are scored with the monotonic XGBoost**, never the ensemble.
  Averaging it with unconstrained members reintroduces the paradoxical rows the
  constraint exists to prevent.
