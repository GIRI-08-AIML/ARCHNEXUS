"""finding status and resolution

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("status", sa.String(20), nullable=False, server_default="open"))
    op.add_column("findings", sa.Column("status_reason", sa.Text(), nullable=True))
    op.create_index("ix_findings_status", "findings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_findings_status", table_name="findings")
    op.drop_column("findings", "status_reason")
    op.drop_column("findings", "status")
