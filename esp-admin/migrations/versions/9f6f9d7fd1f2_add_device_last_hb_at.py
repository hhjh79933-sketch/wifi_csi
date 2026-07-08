"""add device last hb at

Revision ID: 9f6f9d7fd1f2
Revises: c2f6a9d1e3b4
Create Date: 2026-06-22

"""

from alembic import op
import sqlalchemy as sa


revision = "9f6f9d7fd1f2"
down_revision = "c2f6a9d1e3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("last_hb_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_devices_last_hb_at"), "devices", ["last_hb_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_devices_last_hb_at"), table_name="devices")
    op.drop_column("devices", "last_hb_at")