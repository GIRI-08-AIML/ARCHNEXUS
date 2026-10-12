"""organizations memberships and finding comments

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""
from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Organizations
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 2. Memberships
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="viewer"),  # owner, reviewer, viewer
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memberships_org_user", "memberships", ["organization_id", "user_id"], unique=True)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # 3. Add organization_id to projects
    op.add_column("projects", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_projects_organization_id",
        "projects",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])

    # 4. Finding Comments
    op.create_table(
        "finding_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_finding_comments_finding_id", "finding_comments", ["finding_id"])

    # 5. Data Migration: For each user who owns projects or has an account, ensure they have a personal organization
    # Migrate existing projects so their organization_id points to the user's organization.
    bind = op.get_bind()
    users = bind.execute(sa.text("SELECT id, name, company FROM users")).fetchall()
    now = datetime.now(timezone.utc)

    for u in users:
        org_name = u[2] if u[2] else f"{u[1]}'s Workspace"
        res = bind.execute(
            sa.text("INSERT INTO organizations (name, created_at) VALUES (:name, :created_at) RETURNING id"),
            {"name": org_name, "created_at": now},
        )
        org_id = res.scalar()

        # Add as owner
        bind.execute(
            sa.text(
                "INSERT INTO memberships (organization_id, user_id, role, created_at) "
                "VALUES (:org_id, :user_id, 'owner', :created_at)"
            ),
            {"org_id": org_id, "user_id": u[0], "created_at": now},
        )

        # Update user's existing projects
        bind.execute(
            sa.text("UPDATE projects SET organization_id = :org_id WHERE user_id = :user_id"),
            {"org_id": org_id, "user_id": u[0]},
        )


def downgrade() -> None:
    op.drop_index("ix_finding_comments_finding_id", table_name="finding_comments")
    op.drop_table("finding_comments")
    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_constraint("fk_projects_organization_id", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_org_user", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("organizations")
