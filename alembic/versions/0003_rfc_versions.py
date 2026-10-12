"""rfc versions and review comparison

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Project RFC versions
    op.create_table(
        "project_rfc_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("rfc_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_rfc_versions_project_id", "project_rfc_versions", ["project_id"])

    # 2. Add rfc_version_id, rfc_text snapshot, and previous_review_id to reviews
    op.add_column("reviews", sa.Column("rfc_version_id", sa.Integer(), nullable=True))
    op.add_column("reviews", sa.Column("rfc_text", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("previous_review_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_reviews_rfc_version_id",
        "reviews",
        "project_rfc_versions",
        ["rfc_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_reviews_previous_review_id",
        "reviews",
        "reviews",
        ["previous_review_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_reviews_previous_review_id", "reviews", type_="foreignkey")
    op.drop_constraint("fk_reviews_rfc_version_id", "reviews", type_="foreignkey")
    op.drop_column("reviews", "previous_review_id")
    op.drop_column("reviews", "rfc_text")
    op.drop_column("reviews", "rfc_version_id")
    op.drop_index("ix_project_rfc_versions_project_id", table_name="project_rfc_versions")
    op.drop_table("project_rfc_versions")
