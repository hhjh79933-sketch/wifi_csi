from __future__ import annotations

import os
from pathlib import Path

from flask import Flask


def apply_config(app: Flask) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        # Default to SQLite in instance/.
        db_path = Path(app.instance_path) / "esp_admin.sqlite"
        database_url = f"sqlite:///{db_path.as_posix()}"
    else:
        # Be friendly to common MySQL DATABASE_URL formats.
        # If user provides mysql://..., default driver to PyMySQL.
        if database_url.startswith("mysql://"):
            database_url = "mysql+pymysql://" + database_url[len("mysql://") :]

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        APP_API_KEY=os.environ.get("APP_API_KEY"),
        HEARTBEAT_TIMEOUT_SECONDS=int(os.environ.get("HEARTBEAT_TIMEOUT_SECONDS", "180")),
        DEVICE_AUTO_REGISTER=os.environ.get("DEVICE_AUTO_REGISTER", "true").lower() not in ("false", "0", "no"),
        UDP_BIND=os.environ.get("UDP_BIND", "0.0.0.0"),
        UDP_PORT=int(os.environ.get("UDP_PORT", "9000")),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
    )
