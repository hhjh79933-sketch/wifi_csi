from __future__ import annotations

from datetime import datetime

from app.extensions import db


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=True, index=True)
    device = db.relationship("Device", back_populates="events")

    recv_ts_ms = db.Column(db.BigInteger, nullable=False, index=True)
    src_ip = db.Column(db.String(64), nullable=False)
    src_port = db.Column(db.Integer, nullable=False)

    type = db.Column(db.String(32), nullable=True, index=True)

    # hb fields
    count = db.Column(db.Integer, nullable=True)
    uptime_ms = db.Column(db.BigInteger, nullable=True)

    # csi_evt fields
    seq = db.Column(db.Integer, nullable=True)
    state = db.Column(db.Integer, nullable=True)
    prev = db.Column(db.Integer, nullable=True)
    feat = db.Column(db.Text, nullable=True)
    delta = db.Column(db.Text, nullable=True)
    samples = db.Column(db.Text, nullable=True)
    win_ms = db.Column(db.Integer, nullable=True)
    step_ms = db.Column(db.Integer, nullable=True)
    t_ms = db.Column(db.Integer, nullable=True)

    parse_ok = db.Column(db.Boolean, nullable=False, default=False)
    raw_or_json = db.Column(db.Text, nullable=False)
    note = db.Column(db.Text, nullable=True)

    created_at = db.Column(
        db.DateTime(), nullable=False, default=datetime.now
    )

    __table_args__ = (
        db.Index("ix_events_type_recv_ts", "type", "recv_ts_ms"),
        db.Index("ix_events_device_created_at", "device_id", "created_at"),
    )

    def to_dict(self, include_raw: bool = False) -> dict:
        data = {
            "id": self.id,
            "device_id": self.device_id,
            "device_mac": self.device.mac if self.device else None,
            "recv_ts_ms": self.recv_ts_ms,
            "src_ip": self.src_ip,
            "src_port": self.src_port,
            "type": self.type,
            "count": self.count,
            "uptime_ms": self.uptime_ms,
            "seq": self.seq,
            "state": self.state,
            "prev": self.prev,
            "feat": self.feat,
            "delta": self.delta,
            "samples": self.samples,
            "win_ms": self.win_ms,
            "step_ms": self.step_ms,
            "t_ms": self.t_ms,
            "parse_ok": self.parse_ok,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_raw:
            data["raw_or_json"] = self.raw_or_json
        if self.note:
            data["note"] = self.note
        return data
