"""area/tag/bindings

Revision ID: c2f6a9d1e3b4
Revises: 7aca60f75e74
Create Date: 2026-04-18

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c2f6a9d1e3b4"
down_revision = "7aca60f75e74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_areas_is_active"), "areas", ["is_active"], unique=False)
    op.create_index(op.f("ix_areas_name"), "areas", ["name"], unique=False)

    op.create_table(
        "nfc_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uid", sa.String(length=128), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    op.create_index(op.f("ix_nfc_tags_area_id"), "nfc_tags", ["area_id"], unique=False)
    op.create_index(op.f("ix_nfc_tags_is_active"), "nfc_tags", ["is_active"], unique=False)
    op.create_index(op.f("ix_nfc_tags_uid"), "nfc_tags", ["uid"], unique=False)

    op.create_table(
        "device_area_bindings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("area_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("nfc_uid", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"]),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_device_area_bindings_area_id"),
        "device_area_bindings",
        ["area_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_area_bindings_device_id"),
        "device_area_bindings",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_area_bindings_effective_from"),
        "device_area_bindings",
        ["effective_from"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_area_bindings_effective_to"),
        "device_area_bindings",
        ["effective_to"],
        unique=False,
    )
    op.create_index(
        "ix_bind_device_to",
        "device_area_bindings",
        ["device_id", "effective_to"],
        unique=False,
    )
    op.create_index(
        "ix_bind_device_from",
        "device_area_bindings",
        ["device_id", "effective_from"],
        unique=False,
    )
    op.create_index(
        "ix_bind_area_from",
        "device_area_bindings",
        ["area_id", "effective_from"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bind_area_from", table_name="device_area_bindings")
    op.drop_index("ix_bind_device_from", table_name="device_area_bindings")
    op.drop_index("ix_bind_device_to", table_name="device_area_bindings")
    op.drop_index(op.f("ix_device_area_bindings_effective_to"), table_name="device_area_bindings")
    op.drop_index(op.f("ix_device_area_bindings_effective_from"), table_name="device_area_bindings")
    op.drop_index(op.f("ix_device_area_bindings_device_id"), table_name="device_area_bindings")
    op.drop_index(op.f("ix_device_area_bindings_area_id"), table_name="device_area_bindings")
    op.drop_table("device_area_bindings")

    op.drop_index(op.f("ix_nfc_tags_uid"), table_name="nfc_tags")
    op.drop_index(op.f("ix_nfc_tags_is_active"), table_name="nfc_tags")
    op.drop_index(op.f("ix_nfc_tags_area_id"), table_name="nfc_tags")
    op.drop_table("nfc_tags")

    op.drop_index(op.f("ix_areas_name"), table_name="areas")
    op.drop_index(op.f("ix_areas_is_active"), table_name="areas")
    op.drop_table("areas")
