from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.area import Area
from app.models.device import Device
from app.models.device_area_binding import DeviceAreaBinding
from app.models.event import Event
from app.models.nfc_tag import NfcTag


_HEX_RE = re.compile(r"[0-9a-fA-F]")


def now_utc() -> datetime:
    return datetime.now()


def normalize_nfc_uid(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip()
    hex_chars = "".join(ch for ch in s if _HEX_RE.match(ch))
    # Typical NFC UID is hex. If we have something meaningful, store as pure hex.
    if len(hex_chars) >= 4:
        return hex_chars
    return s


def get_tag_by_uid(uid: str) -> NfcTag | None:
    return (
        NfcTag.query.options(joinedload(NfcTag.area))
        .filter_by(uid=uid, is_active=True)
        .first()
    )


def resolve_area_for_device_at(*, device_id: int, at: datetime) -> Area | None:
    binding = (
        DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
        .filter(DeviceAreaBinding.device_id == device_id)
        .filter(DeviceAreaBinding.effective_from <= at)
        .filter(
            (DeviceAreaBinding.effective_to.is_(None))
            | (DeviceAreaBinding.effective_to > at)
        )
        .order_by(DeviceAreaBinding.effective_from.desc())
        .first()
    )
    if not binding:
        return None
    return binding.area


def resolve_area_for_event(event: Event) -> Area | None:
    if not event.device_id:
        return None
    at = datetime.fromtimestamp(event.recv_ts_ms / 1000.0)
    return resolve_area_for_device_at(device_id=event.device_id, at=at)


def bind_device_mac_to_area(
    *,
    mac: str,
    area: Area,
    source: str,
    actor: str | None = None,
    nfc_uid: str | None = None,
    effective_from: datetime | None = None,
) -> tuple[Device, DeviceAreaBinding, bool]:
    """Bind a device (by mac) to an area from now on.

    Returns: (device, binding, changed)
    - changed=False when the device is already bound to the same area.
    """

    if source not in {"app", "web"}:
        raise ValueError("invalid_source")

    ts = effective_from or now_utc()

    device = Device.query.filter_by(mac=mac).with_for_update().first()
    if device is None:
        device = Device(mac=mac)
        db.session.add(device)
        db.session.flush()

    open_bindings = (
        DeviceAreaBinding.query.filter_by(device_id=device.id, effective_to=None)
        .with_for_update()
        .order_by(DeviceAreaBinding.effective_from.desc())
        .all()
    )

    if open_bindings and open_bindings[0].area_id == area.id:
        db.session.commit()
        return device, open_bindings[0], False

    for b in open_bindings:
        b.effective_to = ts

    binding = DeviceAreaBinding(
        device_id=device.id,
        area_id=area.id,
        effective_from=ts,
        effective_to=None,
        source=source,
        actor=actor,
        nfc_uid=nfc_uid,
    )
    db.session.add(binding)
    db.session.flush()
    db.session.commit()

    return device, binding, True
