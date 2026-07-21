"""add lab deployments and shuttle address

Revision ID: 11747eff667e
Revises: 8f3c452fe5b4
Create Date: 2026-07-21 15:18:53.796065

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11747eff667e'
down_revision: Union[str, None] = '8f3c452fe5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shuttles", sa.Column("address", sa.String(length=255), nullable=True))

    op.create_table(
        "lab_deployments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lab_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # A lab is served by one board at a time; binding it twice would
        # make "where does this lab run" ambiguous.
        sa.ForeignKeyConstraint(["lab_id"], ["labs.id"], ondelete="CASCADE"),
        # RESTRICT, not CASCADE: deleting a template or a board that a
        # live deployment depends on should fail loudly rather than
        # silently unbind a lab students are currently using.
        sa.ForeignKeyConstraint(["template_id"], ["lab_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["board_id"], ["boards.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lab_id"),
    )


def downgrade() -> None:
    op.drop_table("lab_deployments")
    op.drop_column("shuttles", "address")
