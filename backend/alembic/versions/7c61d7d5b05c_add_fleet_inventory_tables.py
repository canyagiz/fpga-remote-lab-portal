"""add fleet inventory tables

Revision ID: 7c61d7d5b05c
Revises: 376d82ee7cce
Create Date: 2026-07-21 14:42:09.437004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c61d7d5b05c'
down_revision: Union[str, None] = '376d82ee7cce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shuttles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("role", sa.Enum("master", "worker", name="shuttlerole"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("agent_version", sa.String(length=32), nullable=True),
        sa.Column("last_report_at", sa.DateTime(), nullable=True),
        sa.Column("enrolled_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["enrolled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive uniqueness on the label, same pattern as users and
    # admin_emails - "Shuttle A" and "shuttle a" must not be two nodes.
    op.create_index(
        "ix_shuttles_name_lower", "shuttles", [sa.text("lower(name)")], unique=True
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shuttle_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("usb_vendor_id", sa.String(length=8), nullable=False),
        sa.Column("usb_product_id", sa.String(length=8), nullable=False),
        sa.Column("usb_serial", sa.String(length=128), nullable=True),
        sa.Column("product", sa.String(length=255), nullable=True),
        sa.Column("manufacturer", sa.String(length=255), nullable=True),
        sa.Column("sysfs_path", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=64), nullable=True),
        sa.Column("jtag_chain", sa.JSON(), nullable=True),
        sa.Column("has_video_signal", sa.Boolean(), nullable=True),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shuttle_id"], ["shuttles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Both lookups the ingest path performs on every report: match by
    # serial first, fall back to port path for devices without one.
    op.create_index("ix_devices_shuttle_serial", "devices", ["shuttle_id", "usb_serial"])
    op.create_index("ix_devices_shuttle_path", "devices", ["shuttle_id", "sysfs_path"])


def downgrade() -> None:
    op.drop_index("ix_devices_shuttle_path", table_name="devices")
    op.drop_index("ix_devices_shuttle_serial", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_shuttles_name_lower", table_name="shuttles")
    op.drop_table("shuttles")
    # Postgres keeps an enum type behind after its table is gone; SQLite
    # has no such type to drop.
    sa.Enum(name="shuttlerole").drop(op.get_bind(), checkfirst=True)
