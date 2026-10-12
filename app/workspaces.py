"""Workspaces and membership permissions."""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Membership, Organization, Project, User


def get_user_org_ids(db: Session, user_id: int) -> list[int]:
    """Return all organization IDs that the user is a member of."""
    return list(db.scalars(
        select(Membership.organization_id).where(Membership.user_id == user_id)
    ).all())


def get_user_role_in_org(db: Session, user_id: int, org_id: int) -> str | None:
    """Return 'owner', 'reviewer', 'viewer', or None."""
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.organization_id == org_id
        )
    )
    return membership.role if membership else None


def ensure_user_organization(db: Session, user: User) -> Organization:
    """Ensure user has at least one organization (personal workspace)."""
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
    )
    if membership:
        return membership.organization

    org_name = user.company if user.company else f"{user.name}'s Workspace"
    org = Organization(name=org_name)
    db.add(org)
    db.commit()
    db.refresh(org)

    new_mem = Membership(organization_id=org.id, user_id=user.id, role="owner")
    db.add(new_mem)
    db.commit()
    return org


def check_project_access(db: Session, project: Project, user: User, min_role: str = "viewer") -> str:
    """Verify that user has access to this project.
    
    If min_role is:
    - 'viewer': owner, reviewer, or viewer can view
    - 'reviewer': owner or reviewer (e.g. start reviews, edit RFCs)
    - 'owner': only owner (e.g. delete project, manage members)
    
    Raises 404 if project not accessible, 403 if role insufficient.
    Returns user's role in the organization.
    """
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    # If project has an organization
    if project.organization_id:
        role = get_user_role_in_org(db, user.id, project.organization_id)
        if not role:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

        role_hierarchy = {"owner": 3, "reviewer": 2, "viewer": 1}
        user_level = role_hierarchy.get(role, 0)
        required_level = role_hierarchy.get(min_role, 1)

        if user_level < required_level:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your role ({role}) does not have permission for this action ({min_role} required)."
            )
        return role

    # Fallback for projects without an org (check creator user_id)
    if project.user_id == user.id:
        return "owner"

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
