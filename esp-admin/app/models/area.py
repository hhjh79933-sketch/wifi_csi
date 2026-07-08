from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Area(db.Model):
    __tablename__ = "areas"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )

    tags = db.relationship("NfcTag", back_populates="area", lazy=True)
    bindings = db.relationship("DeviceAreaBinding", back_populates="area", lazy=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "note": self.note,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
