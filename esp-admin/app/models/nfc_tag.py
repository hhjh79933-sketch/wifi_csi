from __future__ import annotations

from datetime import datetime

from app.extensions import db


class NfcTag(db.Model):
    __tablename__ = "nfc_tags"

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(128), unique=True, nullable=False, index=True)

    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"), nullable=False, index=True)
    area = db.relationship("Area", back_populates="tags")

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uid": self.uid,
            "area_id": self.area_id,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
