# Running HeartGuard AI in GitHub Codespaces

A Codespace runs the application on GitHub's machines, not yours, and gives it a public
HTTPS URL. Your laptop can be off.

## Read this first — what a Codespace does and does not give you

**A Codespace stops itself after 30 minutes of inactivity, and a stopped Codespace does
not restart when someone visits the URL.** The visitor gets an error page. Whoever is
looking at your link only sees the application if the Codespace is *running* at that
moment.

That makes this the right tool for a **live demo, viva, or supervised marking session**,
where you start it beforehand and it is watched while you are present. It is the wrong
tool for a URL submitted weeks ahead and clicked without warning.

The free allowance is **60 core-hours per month** on the 2-core machine this
configuration uses — that is 30 hours of wall-clock running time. A Codespace left
running continuously exhausts a month's allowance in a day and a quarter. It is also
deleted after 30 days with no use.

## Setup, once

1. Push this repository to GitHub (it already is: `choudaryathivenexis/HeartGuard_AI`).
2. On the repository page: **Code ▾ → Codespaces → Create codespace on main**.
3. Wait for the build. First time is several minutes — around 600 MB of scientific
   wheels are installed. The terminal shows the progress.
4. When it finishes, the server is already running: `devcontainer.json` starts
   `wsgi.py` on every Codespace start. A "port 8000 is available" notification appears.

## Make the URL public — this is the step that matters

By default the forwarded port is **private**: only you, signed in to GitHub, can open
it. A marker clicking the link would get a sign-in wall. Port visibility cannot be set
in `devcontainer.json`, so this is done by hand, once per Codespace:

- Open the **PORTS** tab in the Codespace terminal panel.
- Right-click the row for port **8000** → **Port Visibility** → **Public**.
- Copy the URL from the **Forwarded Address** column. It looks like
  `https://<codespace-name>-8000.app.github.dev`.

Or from the Codespace terminal:

```bash
gh codespace ports visibility 8000:public -c "$CODESPACE_NAME"
```

That URL is what you share. It survives stopping and restarting the Codespace — the
name does not change — so you can submit it and start the Codespace before it is
looked at.

## Before someone looks at your link

1. Open <https://github.com/codespaces> and press **▶** on the Codespace (or just open
   it in the browser — that starts it).
2. Give it about 30 seconds. `postStartCommand` relaunches the server automatically.
3. Check the URL yourself in a private browsing window — that proves it is reachable
   without your GitHub session, which is exactly what an outside visitor gets.

To stop it idling out mid-demo, raise the timeout: <https://github.com/settings/codespaces>
→ **Default idle timeout** → up to **240 minutes**. It costs allowance whether or not
anyone is using it, so put it back to 30 afterwards.

## Sign-in details

The database is seeded on first run inside the Codespace:

| Role       | Username     | Password        |
| ---------- | ------------ | --------------- |
| SuperAdmin | `superadmin` | `superadmin123` |
| Admin      | `admin`      | `admin123`      |
| Doctor     | `doctor`     | `doctor123`     |

Change these from **Account → Profile** before making the port public — a public URL
with published default passwords is an open door to the patient records held in the
demonstration database.

## If something is wrong

The server writes to a log inside the Codespace:

```bash
cat /tmp/heartguard.log     # startup output and tracebacks
python wsgi.py              # run it in the foreground to watch it live
```

If the page loads but signing in fails with a 400, check that `HEARTGUARD_HTTPS` is
still `1` and that you are on the `https://` URL — the session cookie is marked Secure
and a browser will not return it over plain HTTP.
