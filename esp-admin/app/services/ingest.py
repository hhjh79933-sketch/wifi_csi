from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from flask import current_app

from app.extensions import db
from app.models.device import Device
from app.models.event import Event


_HEX_RE = re.compile(r"[0-9a-fA-F]")


def now_utc() -> datetime:
    return datetime.now()


def now_ms() -> int:
    return int(now_utc().timestamp() * 1000)


def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip().lower()
    # Keep only hex chars and format as aa:bb:cc:dd:ee:ff if possible.
    hex_chars = "".join(ch for ch in s if _HEX_RE.match(ch))
    if len(hex_chars) == 12:
        return ":".join(hex_chars[i : i + 2] for i in range(0, 12, 2))
    return s


def pretty_json_text(text: str) -> str:
    try:
        obj = json.loads(text)
    except Exception:
        return text
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return text


def _json_dumps_maybe(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def parse_datagram(payload: bytes) -> tuple[bool, dict[str, Any] | None, str]:
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return False, None, ""
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return False, None, text
        return True, obj, text
    except Exception:
        return False, None, text


def persist_event(*, src_ip: str, src_port: int, payload: bytes) -> Event:
    recv_ts_ms = now_ms()
    parse_ok, obj, raw_text = parse_datagram(payload)

    event_type: str | None = None
    mac: str | None = None

    fields: dict[str, Any] = {}

    if parse_ok and obj is not None:
        raw_type = obj.get("type")
        event_type = str(raw_type) if raw_type is not None else None
        mac = normalize_mac(obj.get("mac"))

        if event_type == "hb":
            fields["count"] = _safe_int(obj.get("count"))
            fields["uptime_ms"] = _safe_int(obj.get("uptime_ms"))
        elif event_type == "csi_evt":
            fields["seq"] = _safe_int(obj.get("seq"))
            fields["state"] = _safe_int(obj.get("state"))
            fields["prev"] = _safe_int(obj.get("prev"))
            fields["feat"] = _json_dumps_maybe(obj.get("feat"))
            fields["delta"] = _json_dumps_maybe(obj.get("delta"))
            fields["samples"] = _json_dumps_maybe(obj.get("samples"))
            fields["win_ms"] = _safe_int(obj.get("win_ms"))
            fields["step_ms"] = _safe_int(obj.get("step_ms"))
            fields["t_ms"] = _safe_int(obj.get("t_ms"))

    device: Device | None = None
    if mac:
        device = Device.query.filter_by(mac=mac).first()
        if device is None:
            auto_register = current_app.config.get("DEVICE_AUTO_REGISTER", True)
            if auto_register:
                device = Device(mac=mac)
                db.session.add(device)
            else:
                # 白名单模式：未知 MAC 直接丢弃
                return None  # type: ignore[return-value]
        device.last_seen_at = now_utc()
        if parse_ok and event_type == "hb":
            device.last_hb_at = now_utc()

    event = Event(
        device=device,
        recv_ts_ms=recv_ts_ms,
        src_ip=src_ip,
        src_port=src_port,
        type=event_type,
        parse_ok=parse_ok,
        raw_or_json=raw_text,
        **fields,
    )

    db.session.add(event)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("DB commit failed")
        raise

    return event


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None
