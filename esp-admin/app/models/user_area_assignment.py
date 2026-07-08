from __future__ import annotations

from datetime import datetime

from app.extensions import db


class UserAreaAssignment(db.Model):
    __tablename__ = "user_area_assignments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"), nullable=False, index=True)
    assigned_by = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )

    user = db.relationship("User", lazy=True)
    area = db.relationship("Area", lazy=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "area_id": self.area_id,
            "assigned_by": self.assigned_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
