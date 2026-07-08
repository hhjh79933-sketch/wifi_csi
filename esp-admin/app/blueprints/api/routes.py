from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.orm import joinedload
from sqlalchemy import case

from app.models.device import Device
from app.models.device_area_binding import DeviceAreaBinding
from app.models.event import Event
from app.services.binding import bind_device_mac_to_area, get_tag_by_uid, normalize_nfc_uid
from app.services.ingest import normalize_mac


bp = Blueprint("api", __name__, url_prefix="/api")


def _json_error(code: str, *, status: int):
    return jsonify({"error": code}), status


@bp.get("/devices")
def devices_list():  # type: ignore[no-untyped-def]
    heartbeat_timeout_seconds = int(current_app.config.get("HEARTBEAT_TIMEOUT_SECONDS", 180))
    items = Device.query.order_by(Device.last_seen_at.desc(), Device.id.desc()).all()
    devices_out = []
    for d in items:
        # find current binding for device (with area loaded)
        current_binding = (
            DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
            .filter_by(device_id=d.id, effective_to=None)
            .first()
        )
        devices_out.append(
            {
                **d.to_dict(),
                "heartbeat_status": d.heartbeat_status(heartbeat_timeout_seconds),
                "status": d.status(heartbeat_timeout_seconds, current_binding=current_binding),
            }
        )

    return jsonify({"devices": devices_out})


@bp.get("/devices/<int:device_id>")
def device_detail(device_id: int):  # type: ignore[no-untyped-def]
    heartbeat_timeout_seconds = int(current_app.config.get("HEARTBEAT_TIMEOUT_SECONDS", 180))
    device = Device.query.get_or_404(device_id)
    return jsonify(
        {
            "device": {
                **device.to_dict(),
                "heartbeat_status": device.heartbeat_status(heartbeat_timeout_seconds),
            }
        }
    )


@bp.get("/events")
def events_list():  # type: ignore[no-untyped-def]
    items = (
        Event.query.options(joinedload(Event.device))
        .filter(Event.type != "hb")
          .order_by(case((Event.state.is_(None), 0), else_=1), Event.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify({"events": [e.to_dict(include_raw=False) for e in items]})


@bp.get("/events/<int:event_id>")
def event_detail(event_id: int):  # type: ignore[no-untyped-def]
    event = Event.query.get_or_404(event_id)
    return jsonify({"event": event.to_dict(include_raw=True)})


@bp.post("/bind")
def bind_device_to_area():  # type: ignore[no-untyped-def]
    """Bind device->area by NFC UID (called by mobile App).

    Auth: X-API-Key: <APP_API_KEY>
    Body JSON: {"mac": "...", "nfc_uid": "...", "actor": "optional"}
    """

    expected_key = current_app.config.get("APP_API_KEY")
    if not expected_key:
        return _json_error("app_api_key_not_configured", status=503)

    provided_key = request.headers.get("X-API-Key")
    if not provided_key or provided_key != expected_key:
        return _json_error("unauthorized", status=401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("invalid_json", status=400)

    mac_raw = data.get("mac")
    uid_raw = data.get("nfc_uid") or data.get("uid") or data.get("tag_uid")
    actor = data.get("actor")

    mac = normalize_mac(str(mac_raw) if mac_raw is not None else None)
    uid = normalize_nfc_uid(str(uid_raw) if uid_raw is not None else None)

    if not mac:
        return _json_error("missing_or_invalid_mac", status=400)
    if not uid:
        return _json_error("missing_or_invalid_nfc_uid", status=400)

    tag = get_tag_by_uid(uid)
    if not tag or not tag.area:
        return _json_error("unknown_tag", status=404)
    if not getattr(tag.area, "is_active", True):
        return _json_error("area_inactive", status=409)

    device, binding, changed = bind_device_mac_to_area(
        mac=mac,
        area=tag.area,
        source="app",
        actor=str(actor) if actor is not None else None,
        nfc_uid=uid,
    )

    return (
        jsonify(
            {
                "ok": True,
                "changed": changed,
                "device": device.to_dict(),
                "area": tag.area.to_dict(),
                "tag": tag.to_dict(),
                "binding": binding.to_dict(),
            }
        ),
        200,
    )
