from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    mac = db.Column(db.String(32), unique=True, nullable=False, index=True)
    alias = db.Column(db.String(64), nullable=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_hb_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    events = db.relationship("Event", back_populates="device", lazy=True)
    area_bindings = db.relationship(
        "DeviceAreaBinding", back_populates="device", lazy=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "mac": self.mac,
            "alias": self.alias,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "last_hb_at": self.last_hb_at.isoformat() if self.last_hb_at else None,
        }

    def heartbeat_status(self, timeout_seconds: int, *, now: datetime | None = None) -> str:
        if timeout_seconds <= 0 or not self.last_hb_at:
            return "异常"

        current_time = now or datetime.now(timezone.utc)
        elapsed_seconds = (current_time - self.last_hb_at).total_seconds()
        return "正常" if elapsed_seconds <= timeout_seconds else "异常"

    def status(self, timeout_seconds: int, now: datetime | None = None, current_binding: object | None = None) -> str:
        """Return one of: 停用, 正常, 异常.

        Rules:
        - If there is no current binding (current_binding is None), status is 停用.
        - Else use heartbeat_status to determine 正常/异常.
        """
        # If no binding, device considered disabled
        if not current_binding:
            return "停用"

        # If binding exists but area is not active, consider device disabled
        try:
            area = getattr(current_binding, "area", None)
            if area is not None and not getattr(area, "is_active", True):
                return "停用"
        except Exception:
            # be conservative: if we can't determine area active state, treat as enabled
            pass

        return self.heartbeat_status(timeout_seconds, now=now)
