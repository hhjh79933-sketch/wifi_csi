from __future__ import annotations

from datetime import datetime

from app.extensions import db


class DeviceAreaBinding(db.Model):
    __tablename__ = "device_area_bindings"

    id = db.Column(db.Integer, primary_key=True)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False, index=True)
    device = db.relationship("Device", back_populates="area_bindings")

    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"), nullable=False, index=True)
    area = db.relationship("Area", back_populates="bindings")

    effective_from = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    effective_to = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    source = db.Column(db.String(16), nullable=False)  # app | web
    actor = db.Column(db.String(128), nullable=True)
    nfc_uid = db.Column(db.String(128), nullable=True)

    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )

    __table_args__ = (
        db.Index("ix_bind_device_to", "device_id", "effective_to"),
        db.Index("ix_bind_device_from", "device_id", "effective_from"),
        db.Index("ix_bind_area_from", "area_id", "effective_from"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "device_id": self.device_id,
            "area_id": self.area_id,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "source": self.source,
            "actor": self.actor,
            "nfc_uid": self.nfc_uid,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
