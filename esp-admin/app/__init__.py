from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from flask import Flask, g, request

from app.blueprints.admin.routes import bp as admin_bp
from app.blueprints.api.routes import bp as api_bp
from app.blueprints.auth.routes import bp as auth_bp
from app.blueprints.ingest.cli import bp as ingest_bp
from app.config import apply_config
from app.extensions import csrf, db, migrate
from app.services.auth import load_user_from_session


def create_app(config_overrides: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    apply_config(app)
    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY is required. Set environment variable SECRET_KEY before starting."
        )

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    @app.before_request
    def _load_user() -> None:
        g.user = load_user_from_session()

    @app.template_filter("dt")
    def _format_dt(value: datetime | None) -> str:
        if not value:
            return "-"
        return value.strftime("%Y-%m-%d %H:%M:%S")

    @app.template_filter("pretty_json")
    def _pretty_json(value: str | None) -> str:
        if not value:
            return ""
        from app.services.ingest import pretty_json_text

        return pretty_json_text(value)

    @app.template_filter("relative_time")
    def _relative_time(value: datetime | None) -> str:
        if not value:
            return "-"
        now = datetime.now()
        diff = now - value
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "刚刚"
        elif seconds < 3600:
            return f"{seconds // 60}分钟前"
        elif seconds < 86400:
            return f"{seconds // 3600}小时前"
        elif seconds < 2592000:
            return f"{seconds // 86400}天前"
        else:
            return value.strftime("%Y-%m-%d")

    # API blueprint uses X-API-Key auth, exempt from CSRF
    csrf.exempt(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(ingest_bp)

    register_error_handlers(app)

    return app


def register_error_handlers(app: Flask) -> None:
    from flask import jsonify, render_template
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _csrf_error(e):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            return jsonify({"error": "csrf_error"}), 400
        return render_template("errors/404.html"), 400

    @app.errorhandler(404)
    def _not_found(error):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found"}), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _server_error(error):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            return jsonify({"error": "internal_error"}), 500
        return render_template("errors/500.html"), 500
