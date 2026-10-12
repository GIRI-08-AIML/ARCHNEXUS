"""add quote and quote_valid to findings

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("quote", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("quote_valid", sa.Boolean(), nullable=False, server_default=sa.text("true")))


def downgrade() -> None:
    op.drop_column("findings", "quote_valid")
    op.drop_column("findings", "quote")
