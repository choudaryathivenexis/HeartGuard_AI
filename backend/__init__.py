"""
HeartGuard AI — Flask application factory.

The factory pattern is used so the application can be built more than once with
different configuration: the test suite builds one against a temporary database, and
the entrypoint builds one against the real paths. A module-level `app = Flask(...)`
cannot do that, and makes every test share one global.

LAYERING, ENFORCED BY IMPORT DIRECTION
    backend/web          -> services -> domain / ml / repositories
    backend/services     -> domain / ml / repositories
    backend/domain, ml   -> repositories, config
    backend/repositories -> config
Nothing under backend/ imports from frontend/, and nothing under backend/ imports
Flask except backend/web and backend/services/auth (which owns the session). That is
what keeps the clinical logic callable from a script, a test, or a future API.
"""
from __future__ import annotations

from flask import Flask, render_template

from backend import config

__all__ = ["create_app"]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=config.TEMPLATE_DIR,
        static_folder=config.STATIC_DIR,
        static_url_path="/static",
    )
    app.config.from_object(config.Config)
    app.config["SECRET_KEY"] = config.secret_key()
    if test_config:
        app.config.update(test_config)

    # The schema is created on first run if the database file does not exist yet.
    from backend import repositories as db
    db.init_db()

    _ensure_static_assets()

    from backend.web.csrf import init_csrf
    from backend.web.hardening import init_hardening
    init_csrf(app)
    init_hardening(app)

    _register_blueprints(app)
    _register_context(app)
    _register_errors(app)
    return app


def _ensure_static_assets() -> None:
    """
    Generate the served assets if they are missing: the stylesheet and the favicon.

    Both are BUILD PRODUCTS of frontend/design, and both are committed, so a clone
    serves them with no build step. This is the safety net for when they are not — a
    checkout that excluded them, or a token change made without re-running the builder.

    Every failure here is swallowed. An unstyled page or a missing icon is worse than
    the alternative but far better than a server that refuses to start over a cosmetic
    asset.
    """
    import os

    from backend import config

    css = os.path.join(config.STATIC_DIR, "css", "app.css")
    if not os.path.exists(css):
        try:
            from frontend.design import build_css
            build_css.build()
        except Exception:
            pass

    # The templates request static/img/favicon.png; the generator writes to
    # assets/brand/. Without this bridge every page load 404s on its icon.
    try:
        from frontend.design import brand
        brand.ensure_static_favicon()
    except Exception:
        pass


def _register_blueprints(app: Flask) -> None:
    from backend.web import (account, admin, auth, charts, dashboard, patients,
                             performance, reports, screening, system)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(screening.bp)
    app.register_blueprint(patients.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(performance.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(system.bp)
    app.register_blueprint(account.bp)
    app.register_blueprint(charts.bp)


def _register_context(app: Flask) -> None:
    """
    Values and helpers every template needs, injected once.

    The design helpers are imported from frontend/design here rather than in each
    blueprint: a route decides WHAT to show, a template decides HOW, and neither should
    be importing SVG builders. This is the single seam where presentation helpers enter
    the template namespace.
    """
    from backend.ml import versioning
    from backend.services import auth as auth_service
    from frontend.design import brand, icons, illustrations
    from shared import formatting as fmt

    @app.context_processor
    def inject():
        user = auth_service.current_user()
        try:
            version = versioning.model_version_info().get("version")
        except Exception:
            version = None
        return {
            "current_user": user,
            "nav_groups": auth_service.nav_for(user),
            "app_version": "HeartGuard AI v2.1",
            "model_version": version,
            "fmt": fmt,
            # dark=None makes the lockup follow the CSS variables rather than baking a
            # colour, which is what kept it legible when the surface changed.
            "brand_lockup": lambda size=22, wordmark=16: brand.lockup(
                size=size, wordmark_size=wordmark, dark=None),
            # The sign-in panel is a fixed Ink surface in every theme, so its lockup
            # cannot follow the CSS variables — `var(--hg-text-heading)` is near-black
            # and vanishes against it, leaving only the crimson "AI" visible. A
            # single-colour lockup in Bone is the correct treatment on brand surface.
            "brand_lockup_mono": lambda size=30, wordmark=22: brand.lockup_mono(
                "#FFFFFF", size=size, wordmark_size=wordmark),
            # Fail-soft: an icon is decoration, and a mistyped name must not be able
            # to take a whole page down with a KeyError. It renders as nothing.
            "nav_icon": _safe_icon(icons),
            "heart_mark": illustrations.heart_pulse_mark,
            "ecg_strip": illustrations.ecg_strip,
            "vessel_watermark": illustrations.vessel_watermark,
        }


def _safe_icon(icons):
    def render(name: str, size: int = 17) -> str:
        try:
            return icons.to_svg(name, size=size)
        except Exception:
            return ""
    return render


def _register_errors(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(exc):
        # The CSRF check aborts with 400. Without a handler that renders as Werkzeug's
        # bare page, which reads as a crash rather than "your session expired" — and
        # the most common cause is exactly that: a form left open past a restart.
        message = getattr(exc, "description", None) or \
            "The form could not be accepted. Reload the page and try again."
        return render_template("errors/error.html", code=400,
                               title="Request could not be accepted",
                               message=message), 400

    @app.errorhandler(403)
    def forbidden(_exc):
        return render_template("errors/error.html", code=403,
                               title="Not permitted",
                               message="Your role does not have access to that page."), 403

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("errors/error.html", code=404,
                               title="Page not found",
                               message="That address does not exist."), 404

    @app.errorhandler(500)
    def server_error(_exc):
        # The message is deliberately generic. A stack trace in the browser is an
        # information leak, and this application holds patient records.
        app.logger.exception("Unhandled error")
        return render_template("errors/error.html", code=500,
                               title="Something went wrong",
                               message="The error has been logged."), 500
