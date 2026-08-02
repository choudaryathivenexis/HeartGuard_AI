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

### Sign-in entrances

| path | admits | offers registration |
|---|---|---|
| `/login` | any role | yes, as Doctor |
| `/admin/login` | Admin | no |
| `/superadmin/login` | SuperAdmin | no |

Three doors onto one authentication path — the password check, the ban check, the
lockout counter and the audit entry are the same code at all three, so they cannot
drift into one door that forgets to rate-limit. The portal decides only which roles it
admits and what the page says.

**These are entrances, not a security boundary.** What a signed-in user may open is
decided by the role ACL in `backend/services/auth.py`, on every request, whichever door
they used. The URLs are in this repository and are not secret.

A correct password at the wrong door is refused with the byte-identical response a wrong
password gets — anything else confirms both the username and the password to whoever
typed them — and is written to the activity log, since only a genuine credential can
reach that branch. Roles are jobs rather than ranks here, so a SuperAdmin is refused at
`/admin/login`; every portal links to the other two so nobody is stuck at the wrong one.

Use `wsgi.py` for anything reachable by someone else. `app.py` runs Werkzeug's
development server, which is single-process and not hardened against malformed or slow
requests.

---

## Which database

The application speaks two, chosen by one environment variable:

```bash
# unset  -> SQLite, in heartguard.db beside the code. Every local run.
DATABASE_URL=postgresql://user:password@host/dbname   # -> Postgres
```

SQLite is right for a machine you can point at a file. It is wrong for a serverless
host, where the filesystem is read-only and each instance would hold a private copy of
the data anyway. The whole difference is confined to
[backend/repositories/dialect.py](backend/repositories/dialect.py) — placeholders,
timestamps, new-row ids and the row type — so every query above that layer is written
once.

Two things follow that are easy to miss:

- **Timestamps are TEXT on both backends.** Postgres would otherwise return `datetime`
  objects, and the analytics service slices the value as a string to group by day. That
  is a `TypeError`, not a formatting difference.
- **A backup is portable between them.** Download from a populated SQLite install and
  restore into a deployed Postgres one — that is the migration path off a laptop.

---

## Deploying

Four configurations ship with the project. None require a card; each trades something
else away, and the table says what.

| | card | always on | notes |
|---|---|---|---|
| **Vercel** (`vercel.json`) | no | **yes** | needs a Postgres URL; no dataset upload or retraining |
| GitHub Codespaces (`.devcontainer/`) | no | **no** | stops after 30 min idle; 60 core-hours/month |
| Hugging Face Spaces (`Dockerfile`) | no | yes | **needs free CPU quota, which not every account has** |
| Render (`render.yaml`) | **yes** | sleeps at 15 min | free plan asks for a card it does not charge |

### Vercel — the always-on option

[api/index.py](api/index.py) is the entry point and [vercel.json](vercel.json) routes
every path to it. Import the repository at <https://vercel.com/new>, then set two
environment variables in the project settings:

| variable | value |
|---|---|
| `DATABASE_URL` | a Postgres connection string — [Neon](https://neon.tech) has a free tier that needs no card |
| `HEARTGUARD_SECRET_KEY` | any long random string; `python -c "import secrets;print(secrets.token_hex(32))"` |

**`DATABASE_URL` is not optional here.** Without it the application falls back to SQLite
inside a read-only bundle, and the first write is the audit entry that sign-in makes —
so nobody could log in at all.

**Two administrative features cannot work on this host**, and the pages say so rather
than failing: replacing the training dataset, and retraining. Both write beside the
code, and the deployment is read-only. Everything else — screening, SHAP explanations,
PDF and CSV export, patients, reports, charts, user administration, settings, model
toggles, activity logs, and backup and restore — works exactly as it does locally.

Expect a slow first request after an idle period: a cold start imports scikit-learn,
xgboost, shap and matplotlib and unpickles five estimators.

### GitHub Codespaces — best for a demo or viva

`.devcontainer/devcontainer.json` builds the environment, installs the dependencies and
starts `wsgi.py` on every Codespace start. Making the forwarded port public gives a
`https://<name>-8000.app.github.dev` URL that works with your own machine switched off.

The catch is the idle stop, and it is a real one: **a stopped Codespace does not wake
when a visitor loads the URL** — they get an error page. Start it before it is looked at.
Full instructions and limits: [`.devcontainer/README.md`](.devcontainer/README.md).

### Hugging Face Spaces (check your quota first)

Create a Space with **SDK: Docker**, then push this repository to it:

```bash
git remote add hf https://huggingface.co/spaces/<your-user>/heartguard-ai
git push hf main
```

The `Dockerfile` and the YAML block at the top of this file are all the configuration
needed. Free CPU tier gives 2 vCPU and 16 GB RAM — comfortable, against a measured peak
of 333 MB with all five models loaded and a SHAP explanation computed.

**Confirm the account has free CPU quota before relying on this.** A Docker Space needs
a `cpu-basic` allocation, and an account with none gets a Space stuck in `PAUSED` with

```
Quota exceeded for flavor cpu-basic (requested=1): current=0, limit=0
```

The push succeeds and the build never starts, which reads like a broken Dockerfile and
is not one. Static Spaces are unaffected because they run no compute at all — that is
why they stay free regardless. Check with:

```bash
curl -s https://huggingface.co/api/spaces/<user>/<space> | python -m json.tool
```

One detail the Dockerfile handles and which is easy to miss elsewhere: xgboost's wheel
links against OpenMP at runtime, so `libgomp1` must be installed or the container builds
cleanly and then dies on first import.

### Render (free plan, but asks for a card)

`render.yaml` is a Blueprint: **New → Blueprint** in the dashboard, pick this
repository, Apply. Runtime, commands, health check and environment variables all come
from that file.

### Where the data actually lives

**This matters before you show it to anyone:**

| deployment | what happens to the data |
|---|---|
| Vercel + Postgres | it persists — the database is a separate managed service |
| Codespaces | it persists — `/workspaces` survives an idle stop; gone when the Codespace is deleted, automatic after 30 days unused |
| Hugging Face / Render, no `DATABASE_URL` | **recreated empty on every redeploy or restart** |

The last row is the trap. A container with SQLite inside it holds the database on the
container's own disk, and that disk is replaced with the container. Set `DATABASE_URL`
on those hosts too and the same free Postgres fixes it.

`HEARTGUARD_SECRET_KEY` should be set on any deployment. Without it the application
generates a key and stores it with the other settings — which is correct and survives a
restart, but two instances started against an empty database would each generate their
own, and each would then reject the other's session cookies.

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
