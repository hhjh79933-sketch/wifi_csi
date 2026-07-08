from __future__ import annotations

from flask import Blueprint, current_app, g, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload
from sqlalchemy import case

from app.extensions import db
from app.models.area import Area
from app.models.device import Device
from app.models.device_area_binding import DeviceAreaBinding
from app.models.event import Event
from app.models.nfc_tag import NfcTag
from app.models.user import User
from app.models.user_area_assignment import UserAreaAssignment
from app.services.auth import admin_required
from app.services.binding import bind_device_mac_to_area, normalize_nfc_uid, resolve_area_for_event
from app.services.ingest import normalize_mac


bp = Blueprint("admin", __name__)


@bp.get("/")
@admin_required
def dashboard():  # type: ignore[no-untyped-def]
    from datetime import datetime, timezone

    heartbeat_timeout_seconds = int(current_app.config.get("HEARTBEAT_TIMEOUT_SECONDS", 180))
    device_total = Device.query.count()
    event_total = Event.query.count()

    last_hb = (
        Event.query.filter(Event.type == "hb")
          .order_by(case((Event.state.is_(None), 0), else_=1), Event.created_at.desc())
        .limit(1)
        .first()
    )
    last_csi = (
        Event.query.filter(Event.type == "csi_evt")
        .order_by(Event.created_at.desc())
        .limit(1)
        .first()
    )

    # Device status stats
    now = datetime.now(timezone.utc)
    ok_count = 0
    warn_count = 0
    off_count = 0
    for d in Device.query.all():
        b = (
            DeviceAreaBinding.query.filter_by(device_id=d.id, effective_to=None).first()
        )
        st = d.status(heartbeat_timeout_seconds, now=now, current_binding=b)
        if st == "正常":
            ok_count += 1
        elif st == "异常":
            warn_count += 1
        else:
            off_count += 1

    return render_template(
        "admin/dashboard.html",
        device_total=device_total,
        event_total=event_total,
        last_hb_at=last_hb.created_at if last_hb else None,
        last_csi_at=last_csi.created_at if last_csi else None,
        ok_count=ok_count,
        warn_count=warn_count,
        off_count=off_count,
    )


@bp.get("/devices")
@admin_required
def devices():  # type: ignore[no-untyped-def]
    heartbeat_timeout_seconds = int(current_app.config.get("HEARTBEAT_TIMEOUT_SECONDS", 180))
    items = Device.query.order_by(Device.last_seen_at.desc(), Device.id.desc()).all()

    device_ids = [d.id for d in items]
    binding_by_device_id: dict[int, DeviceAreaBinding] = {}
    if device_ids:
        bindings = (
            DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
            .filter(DeviceAreaBinding.device_id.in_(device_ids))
            .filter(DeviceAreaBinding.effective_to.is_(None))
            .all()
        )
        binding_by_device_id = {b.device_id: b for b in bindings}

    return render_template(
        "admin/devices.html",
        devices=items,
        current_bindings=binding_by_device_id,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        current_bindings_map=binding_by_device_id,
    )


@bp.post("/devices/add")
@admin_required
def device_add():  # type: ignore[no-untyped-def]
    mac_raw = (request.form.get("mac") or "").strip()
    mac = normalize_mac(mac_raw) if mac_raw else None

    if not mac:
        return redirect(url_for("admin.devices"))

    existing = Device.query.filter_by(mac=mac).first()
    if not existing:
        db.session.add(Device(mac=mac))
        db.session.commit()

    return redirect(url_for("admin.devices"))


@bp.get("/devices/<int:device_id>")
@admin_required
def device_detail(device_id: int):  # type: ignore[no-untyped-def]
    heartbeat_timeout_seconds = int(current_app.config.get("HEARTBEAT_TIMEOUT_SECONDS", 180))
    device = Device.query.get_or_404(device_id)

    areas = (
        Area.query.filter_by(is_active=True)
        .order_by(Area.name.asc(), Area.id.asc())
        .all()
    )

    current_binding = (
        DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
        .filter_by(device_id=device.id, effective_to=None)
        .order_by(DeviceAreaBinding.effective_from.desc())
        .first()
    )

    bindings = (
        DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
        .filter_by(device_id=device.id)
        .order_by(DeviceAreaBinding.effective_from.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "admin/device_detail.html",
        device=device,
        areas=areas,
        current_binding=current_binding,
        bindings=bindings,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        current_binding_obj=current_binding,
    )


@bp.post("/devices/<int:device_id>/bind")
@admin_required
def device_bind(device_id: int):  # type: ignore[no-untyped-def]
    device = Device.query.get_or_404(device_id)
    area_id_raw = request.form.get("area_id")
    try:
        area_id = int(area_id_raw or 0)
    except Exception:
        area_id = 0

    if area_id <= 0:
        return redirect(url_for("admin.device_detail", device_id=device.id))

    area = Area.query.get_or_404(area_id)
    actor = getattr(getattr(g, "user", None), "username", None)

    bind_device_mac_to_area(mac=device.mac, area=area, source="web", actor=actor)
    return redirect(url_for("admin.device_detail", device_id=device.id))


@bp.post("/devices/<int:device_id>/unbind")
@admin_required
def device_unbind(device_id: int):  # type: ignore[no-untyped-def]
    from datetime import datetime, timezone

    device = Device.query.get_or_404(device_id)
    binding = (
        DeviceAreaBinding.query.filter_by(device_id=device.id, effective_to=None).first()
    )
    if binding:
        binding.effective_to = datetime.now(timezone.utc)
        db.session.commit()
    return redirect(url_for("admin.device_detail", device_id=device.id))


@bp.get("/events")
@admin_required
def events():  # type: ignore[no-untyped-def]
    items = (
        Event.query.options(joinedload(Event.device))
        .filter(Event.type != "hb")
        .order_by(Event.created_at.desc())
        .limit(200)
        .all()
    )

    # 加载设备当前区域
    device_ids = [e.device_id for e in items if e.device_id]
    area_map: dict[int, str] = {}
    if device_ids:
        bindings = (
            DeviceAreaBinding.query.options(joinedload(DeviceAreaBinding.area))
            .filter(DeviceAreaBinding.device_id.in_(device_ids), DeviceAreaBinding.effective_to.is_(None))
            .all()
        )
        area_map = {b.device_id: b.area.name for b in bindings if b.area}

    return render_template("admin/events.html", events=items, area_map=area_map)


@bp.get("/events/<int:event_id>")
@admin_required
def event_detail(event_id: int):  # type: ignore[no-untyped-def]
    event = Event.query.get_or_404(event_id)
    area = resolve_area_for_event(event)
    return render_template("admin/event_detail.html", event=event, area=area)


@bp.get("/areas")
@admin_required
def areas():  # type: ignore[no-untyped-def]
    # Stable ordering: don't reorder rows when toggling active.
    items = Area.query.order_by(Area.id.desc()).all()
    return render_template("admin/areas.html", areas=items, error=None)


@bp.post("/areas")
@admin_required
def areas_create():  # type: ignore[no-untyped-def]
    name = (request.form.get("name") or "").strip()
    note = (request.form.get("note") or "").strip() or None

    if not (1 <= len(name) <= 128):
        items = Area.query.order_by(Area.id.desc()).all()
        return render_template(
            "admin/areas.html", areas=items, error="区域名长度不合法"
        )

    existing = Area.query.filter_by(name=name).first()
    if existing:
        items = Area.query.order_by(Area.id.desc()).all()
        return render_template(
            "admin/areas.html", areas=items, error="区域名已存在"
        )

    area = Area(name=name, note=note, is_active=True)
    db.session.add(area)
    db.session.commit()

    return redirect(url_for("admin.areas"))


@bp.post("/areas/<int:area_id>/toggle")
@admin_required
def area_toggle(area_id: int):  # type: ignore[no-untyped-def]
    area = Area.query.get_or_404(area_id)
    area.is_active = not bool(area.is_active)
    db.session.commit()
    return redirect(url_for("admin.areas"))


@bp.post("/areas/<int:area_id>/delete")
@admin_required
def area_delete(area_id: int):  # type: ignore[no-untyped-def]
    area = Area.query.get_or_404(area_id)

    if area.is_active:
        items = Area.query.order_by(Area.id.desc()).all()
        return render_template(
            "admin/areas.html",
            areas=items,
            error="请先停用区域再删除",
        )

    tag_count = NfcTag.query.filter_by(area_id=area.id).count()
    binding_count = DeviceAreaBinding.query.filter_by(area_id=area.id, effective_to=None).count()
    assignment_count = UserAreaAssignment.query.filter_by(area_id=area.id).count()
    if tag_count or binding_count or assignment_count:
        items = Area.query.order_by(Area.id.desc()).all()
        return render_template(
            "admin/areas.html",
            areas=items,
            error=(
                f"该区域仍有活跃引用，无法删除（活跃标签={tag_count}, 活跃绑定={binding_count}, 活跃分配={assignment_count}）。"
                "请先清理后再试。"
            ),
        )

    # 清理历史绑定记录（已关闭的），否则外键约束阻止删除
    DeviceAreaBinding.query.filter_by(area_id=area.id).delete()
    NfcTag.query.filter_by(area_id=area.id).delete()
    UserAreaAssignment.query.filter_by(area_id=area.id).delete()
    db.session.flush()

    db.session.delete(area)
    db.session.commit()
    return redirect(url_for("admin.areas"))

@bp.get("/areas/<int:area_id>")
@admin_required
def area_detail(area_id: int):  # type: ignore[no-untyped-def]
    area = Area.query.get_or_404(area_id)

    assignments = (
        UserAreaAssignment.query.options(joinedload(UserAreaAssignment.user))
        .filter_by(area_id=area.id)
        .order_by(UserAreaAssignment.created_at.desc())
        .limit(100)
        .all()
    )

    current_users = User.query.filter_by(current_area_id=area.id).all()

    tags = NfcTag.query.filter_by(area_id=area.id).order_by(NfcTag.id.desc()).all()

    return render_template(
        "admin/area_detail.html",
        area=area,
        assignments=assignments,
        current_users=current_users,
        tags=tags,
    )

@bp.get("/tags")
@admin_required
def tags():  # type: ignore[no-untyped-def]
    tags = (
        NfcTag.query.options(joinedload(NfcTag.area))
        # Stable ordering: don't reorder rows when toggling active.
        .order_by(NfcTag.id.desc())
        .all()
    )
    areas = Area.query.order_by(Area.is_active.desc(), Area.name.asc()).all()
    return render_template(
        "admin/tags.html", tags=tags, areas=areas, error=None
    )


@bp.post("/tags")
@admin_required
def tags_upsert():  # type: ignore[no-untyped-def]
    uid = normalize_nfc_uid(request.form.get("uid"))
    area_id_raw = request.form.get("area_id")
    try:
        area_id = int(area_id_raw or 0)
    except Exception:
        area_id = 0

    tags = (
        NfcTag.query.options(joinedload(NfcTag.area))
        .order_by(NfcTag.id.desc())
        .all()
    )
    areas = Area.query.order_by(Area.is_active.desc(), Area.name.asc()).all()

    if not uid:
        return render_template(
            "admin/tags.html",
            tags=tags,
            areas=areas,
            error="UID 不合法",
        )
    if area_id <= 0:
        return render_template(
            "admin/tags.html",
            tags=tags,
            areas=areas,
            error="请选择区域",
        )

    area = Area.query.get(area_id)
    if not area:
        return render_template(
            "admin/tags.html",
            tags=tags,
            areas=areas,
            error="区域不存在",
        )

    tag = NfcTag.query.filter_by(uid=uid).first()
    if tag:
        tag.area_id = area.id
        tag.is_active = True
    else:
        tag = NfcTag(uid=uid, area_id=area.id, is_active=True)
        db.session.add(tag)

    db.session.commit()
    return redirect(url_for("admin.tags"))


@bp.post("/tags/<int:tag_id>/toggle")
@admin_required
def tag_toggle(tag_id: int):  # type: ignore[no-untyped-def]
    tag = NfcTag.query.get_or_404(tag_id)
    tag.is_active = not bool(tag.is_active)
    db.session.commit()
    return redirect(url_for("admin.tags"))


@bp.post("/tags/<int:tag_id>/delete")
@admin_required
def tag_delete(tag_id: int):  # type: ignore[no-untyped-def]
    tag = NfcTag.query.get_or_404(tag_id)
    if tag.is_active:
        tags = (
            NfcTag.query.options(joinedload(NfcTag.area))
            .order_by(NfcTag.id.desc())
            .all()
        )
        areas = Area.query.order_by(Area.is_active.desc(), Area.name.asc()).all()
        return render_template(
            "admin/tags.html",
            tags=tags,
            areas=areas,
            error="请先停用标签再删除",
        )

    db.session.delete(tag)
    db.session.commit()
    return redirect(url_for("admin.tags"))

@bp.get("/users")
@admin_required
def users():  # type: ignore[no-untyped-def]
    from werkzeug.security import generate_password_hash

    users = (
        User.query.options(joinedload(User.current_area))
        .order_by(User.id.asc())
        .all()
    )
    areas = Area.query.order_by(Area.is_active.desc(), Area.name.asc()).all()
    return render_template(
        "admin/users.html", users=users, areas=areas, error=None
    )


@bp.post("/users")
@admin_required
def users_create():  # type: ignore[no-untyped-def]
    from werkzeug.security import generate_password_hash

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    is_admin = request.form.get("is_admin") == "1"

    users = (
        User.query.options(joinedload(User.current_area))
        .order_by(User.id.asc())
        .all()
    )
    areas = Area.query.order_by(Area.is_active.desc(), Area.name.asc()).all()

    if not (1 <= len(username) <= 64):
        return render_template("admin/users.html", users=users, areas=areas, error="用户名长度不合法")
    if not (4 <= len(password) <= 128):
        return render_template("admin/users.html", users=users, areas=areas, error="密码至少 4 位")

    if User.query.filter_by(username=username).first():
        return render_template("admin/users.html", users=users, areas=areas, error="用户名已存在")

    user = User(username=username, is_admin=is_admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/area")
@admin_required
def users_set_area(user_id: int):  # type: ignore[no-untyped-def]
    user = User.query.get_or_404(user_id)
    area_id_raw = request.form.get("area_id")
    try:
        area_id = int(area_id_raw or 0) if area_id_raw else 0
    except Exception:
        area_id = 0

    user.current_area_id = area_id if area_id > 0 else None

    # 仅在分配实际区域时记录日志（取消分配不记录）
    if area_id > 0:
        assigned_by = getattr(getattr(g, "user", None), "username", None)
        log = UserAreaAssignment(
            user_id=user.id,
            area_id=area_id,
            assigned_by=assigned_by,
        )
        db.session.add(log)

    db.session.commit()
    return redirect(url_for("admin.users"))