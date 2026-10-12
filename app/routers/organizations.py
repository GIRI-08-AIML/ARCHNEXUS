"""Organizations and workspace membership router."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import Membership, Organization, User
from app.schemas import InviteMemberRequest, MembershipRead, OrganizationRead
from app.workspaces import ensure_user_organization

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=list[OrganizationRead])
def my_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List organizations the current user belongs to."""
    ensure_user_organization(db, user)
    mems = db.scalars(
        select(Membership).where(Membership.user_id == user.id)
    ).all()
    return [m.organization for m in mems]


@router.get("/{org_id}/members", response_model=list[MembershipRead])
def list_members(
    org_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List members of an organization."""
    # Check caller is a member
    mem = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user.id
        )
    )
    if not mem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")

    return db.scalars(
        select(Membership).where(Membership.organization_id == org_id).order_by(Membership.id)
    ).all()


@router.post("/{org_id}/invites", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
def invite_member(
    org_id: int,
    payload: InviteMemberRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Owner invites a member by email to the organization."""
    caller_mem = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == user.id
        )
    )
    if not caller_mem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    if caller_mem.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only organization owners can invite members")

    target_user = db.scalar(select(User).where(User.email == payload.email))
    if not target_user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No account found with email '{payload.email}'. The user must register first.",
        )

    existing = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.user_id == target_user.id
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This user is already a member of the organization"
        )

    new_mem = Membership(
        organization_id=org_id,
        user_id=target_user.id,
        role=payload.role.value,
    )
    db.add(new_mem)
    db.commit()
    db.refresh(new_mem)
    return new_mem
