from __future__ import annotations

import signal
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

import click
from flask import Blueprint, current_app

from app.extensions import db
from app.models.event import Event
from app.models.user import User
from app.services.ingest import persist_event


bp = Blueprint("ingest", __name__)


@bp.cli.command("udp")
@click.option("--bind", "bind_", default=None, help="Override UDP_BIND")
@click.option("--port", "port_", default=None, type=int, help="Override UDP_PORT")
def udp_ingest(bind_: str | None, port_: int | None) -> None:
    """Listen UDP and persist incoming JSON/raw text as Event."""

    bind_addr = bind_ or current_app.config.get("UDP_BIND", "0.0.0.0")
    port = int(port_ or current_app.config.get("UDP_PORT", 9000))

    click.echo(f"[udp-ingest] listening on {bind_addr}:{port}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_addr, port))
    sock.settimeout(1.0)

    stop = {"flag": False}

    def _stop(*args: Any, **kwargs: Any) -> None:
        stop["flag"] = True

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except Exception:
        # Some platforms may not support SIGTERM in certain contexts.
        pass

    while not stop["flag"]:
        try:
            payload, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            if stop["flag"]:
                break
            raise

        src_ip, src_port = addr[0], int(addr[1])
        try:
            persist_event(src_ip=src_ip, src_port=src_port, payload=payload)
        except Exception as exc:
            current_app.logger.exception("udp ingest failed")
            click.echo(f"[udp-ingest][warn] failed: {exc}", err=True)


@bp.cli.command("init-admin")
def init_admin() -> None:
    """Create initial admin user from env ADMIN_USERNAME/ADMIN_PASSWORD (idempotent)."""

    username = current_app.config.get("ADMIN_USERNAME")
    password = current_app.config.get("ADMIN_PASSWORD")

    if not username or not password:
        click.echo(
            "ADMIN_USERNAME and ADMIN_PASSWORD are required to init admin.", err=True
        )
        raise click.Abort()

    existing = User.query.filter_by(username=username).first()
    if existing:
        click.echo("Admin already exists; nothing to do.")
        return

    user = User(username=username, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    click.echo(f"Created admin user: {username}")


@bp.cli.command("cleanup")
@click.option("--days", default=14, type=int, help="Delete non-hb events older than DAYS (default: 14)")
@click.option("--dry-run", is_flag=True, help="Only show what would be deleted")
def cleanup_old_events(days: int, dry_run: bool) -> None:
    """Delete non-hb events older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = Event.query.filter(Event.type != "hb", Event.created_at < cutoff)
    count = query.count()

    if dry_run:
        click.echo(f"[cleanup] Would delete {count} events older than {days} days (before {cutoff.isoformat()})")
        return

    if count == 0:
        click.echo(f"[cleanup] No events to delete (older than {days} days).")
        return

    try:
        query.delete(synchronize_session="fetch")
        db.session.commit()
        click.echo(f"[cleanup] Deleted {count} non-hb events older than {days} days.")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("cleanup failed")
        click.echo(f"[cleanup] Failed: {exc}", err=True)
        raise click.Abort()
