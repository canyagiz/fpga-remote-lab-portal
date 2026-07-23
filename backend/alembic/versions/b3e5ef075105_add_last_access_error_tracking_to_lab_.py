"""add last access error tracking to lab deployments

Revision ID: b3e5ef075105
Revises: 99aa7a7332c9
Create Date: 2026-07-23 15:05:45.751384

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3e5ef075105'
down_revision: Union[str, None] = '99aa7a7332c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lab_deployments", sa.Column("last_access_error", sa.String(), nullable=True))
    op.add_column("lab_deployments", sa.Column("last_access_error_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("lab_deployments", "last_access_error_at")
    op.drop_column("lab_deployments", "last_access_error")
