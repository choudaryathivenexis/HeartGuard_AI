"""
Chart images.

Charts are matplotlib figures rendered to PNG and served from a route, so a template
embeds one with a plain <img>. That keeps the pages free of any client-side charting
library — no JavaScript dependency, and the palette stays the one in shared/tokens.py.

Every figure is closed by `charts.to_png`. A long-lived server that leaks one figure
per request exhausts memory; under the old per-rerun model the same leak was merely
slower.

WHY THE RENDERED PNG IS CACHED
Rendering one chart takes ~0.2s, which is fine alone. Under load it is not: matplotlib
is CPU-bound and holds the GIL, so twelve concurrent dashboard loads serialise into a
2.7s wait for the last one — measured against the production server. The underlying
data changes only when an assessment is recorded or the models are retrained, so a
cache keyed on exactly that turns every repeat view into a dictionary lookup.

The key is a VERSION OF THE DATA, not a timer. A time-based cache shows a clinician a
stale risk mix for however long the window is; this one is stale for zero seconds,
because recording an assessment changes the key.
"""
from __future__ import annotations

import threading

from flask import Blueprint, Response, abort

from backend.ml import charts as ch
from backend.ml import versioning
from backend.services import analytics
from backend.services import auth as auth_service
from backend import repositories as db


bp = Blueprint("charts", __name__, url_prefix="/charts")

# no-store, deliberately. These images are scoped to the signed-in user — a Doctor's
# risk mix is their caseload — so they must not be written to a shared proxy or left
# in the browser cache of a shared clinical workstation. The server-side cache below
# gives the speed without that exposure.
_CACHE_HEADERS = {"Cache-Control": "no-store, private"}

_MAX_ENTRIES = 32
_cache: dict[tuple, bytes] = {}
_cache_lock = threading.Lock()
# One lock per cache key, so two different charts still render in parallel while two
# requests for the SAME chart do not. See the stampede note in `_cached_png`.
_build_locks: dict[tuple, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _build_lock(key: tuple) -> threading.Lock:
    with _build_locks_guard:
        lock = _build_locks.get(key)
        if lock is None:
            lock = _build_locks[key] = threading.Lock()
        return lock


def _data_version(user: dict | None = None) -> tuple:
    """
    A key that changes exactly when a chart's content would.

    Row count AND the highest id: a count alone is unchanged by a delete followed by
    an insert, which would serve the old image for a caseload that has genuinely moved
    on.
    """
    rows = (db.get_predictions(user_id=user["id"])
            if user and user["role"] == "Doctor" else db.get_predictions())
    highest = max((r["id"] for r in rows), default=0)
    return (len(rows), highest, versioning.model_version_info().get("version"))


def _cached_png(key: tuple, build) -> Response:
    """
    Serve a cached PNG, rendering it at most once per key.

    SINGLE-FLIGHT, NOT JUST A CACHE. A plain cache only helps the second viewer: with
    twelve dashboards loading at once every one of them finds the cache empty and
    renders its own copy, and because matplotlib holds the GIL they serialise anyway.
    Measured: twelve concurrent loads still cost 2.67s for the last one, barely better
    than the 2.75s with no cache at all.

    Holding a per-key lock across the build means the first request renders and the
    other eleven wait on it and get the finished bytes. The lock is PER KEY so two
    different charts still render concurrently.

    The cache is re-checked inside the lock: by the time a waiting thread acquires it,
    the first thread has already stored the result, and re-rendering it would defeat
    the point.
    """
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return Response(hit, mimetype="image/png", headers=_CACHE_HEADERS)

    with _build_lock(key):
        with _cache_lock:
            hit = _cache.get(key)
        if hit is None:
            hit = ch.to_png(build())
            with _cache_lock:
                # A plain dict with a size cap rather than an LRU: the working set is
                # one entry per chart per data-version, so it turns over on its own.
                # The cap only stops a long-running process accumulating old versions.
                if len(_cache) >= _MAX_ENTRIES:
                    _cache.clear()
                    _build_locks.clear()
                _cache[key] = hit
    return Response(hit, mimetype="image/png", headers=_CACHE_HEADERS)


# Full model names collide on a shared axis — "Support Vector Machine (SVM)" alone is
# wider than its bar, so adjacent labels overprint each other into an unreadable smear.
# Abbreviations are keyed by name, never by position.
SHORT_NAMES = {
    "Logistic Regression": "LR",
    "Support Vector Machine (SVM)": "SVM",
    "Decision Tree": "Tree",
    "Random Forest": "Forest",
    "XGBoost": "XGB",
    "Ensemble Voting": "Ensemble",
}


@bp.route("/model-discrimination.png")
@auth_service.login_required
def model_discrimination():
    rows = [r for r in analytics.model_leaderboard() if r["auc"] is not None]
    if not rows:
        abort(404)

    def build():
        fig, ax = ch.figure(width=6.4, height=3.0)
        names = [r["name"] for r in rows]
        values = [r["auc"] for r in rows]
        bars = ax.bar(range(len(rows)), values,
                  color=[ch.series_color(n) for n in names], width=.62)
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels([SHORT_NAMES.get(n, n) for n in names], fontsize=8.5)
        # Headroom above the tallest bar so the value label sits outside it rather than
        # printing over the fill.
        ax.set_ylim(0, min(1.0, max(values) * 1.18))
        ch.style_axes(ax, grid="y")
        ch.annotate_bars(ax, bars, fmt="{:.3f}", horizontal=False)
        return fig

    # This chart is identical for every user, so the key needs only the model version.
    return _cached_png(("discrimination",
                        versioning.model_version_info().get("version")), build)


@bp.route("/risk-mix.png")
@auth_service.login_required
def risk_mix():
    user = auth_service.current_user()
    mix = analytics.risk_mix(user)

    def build():
        fig, ax = ch.figure(width=6.0, height=2.9)
        labels = list(mix.keys())
        values = list(mix.values())
        keys = ["low", "borderline", "intermediate", "high"]
        bars = ax.bar(range(len(labels)), values,
                  color=[ch.risk_color(k) for k in keys], width=.6)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels([l.title() for l in labels], fontsize=8)
        ch.style_axes(ax, grid="y")
        ch.annotate_bars(ax, bars, fmt="{:.0f}", horizontal=False)
        return fig

    # Scoped per user: a Doctor's mix is their own caseload, so the key carries their
    # id. Sharing one entry across users would show one clinician another's figures.
    return _cached_png(("risk-mix", user["id"], _data_version(user)), build)


@bp.route("/activity.png")
@auth_service.login_required
def activity():
    user = auth_service.current_user()
    series = analytics.activity_series(user)
    if not series:
        abort(404)

    def build():
        fig, ax = ch.figure(width=6.4, height=2.6)
        xs = range(len(series))
        ax.plot(list(xs), [c for _d, c in series], color=ch.color("primary"),
            marker="o", markersize=3.5, linewidth=1.8)
        ax.set_xticks(list(xs)[::max(1, len(series) // 7)])
        ax.set_xticklabels([d[5:] for d, _c in series][::max(1, len(series) // 7)],
                       fontsize=8)
        ch.style_axes(ax, grid="y")
        return fig

    return _cached_png(("activity", user["id"], _data_version(user)), build)
