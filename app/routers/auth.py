from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import get_current_user, get_db
from app.login_limiter import login_limiter
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserRead
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(
        email=payload.email,
        name=payload.name,
        company=payload.company,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Provision workspace/organization
    from app.models import Membership, Organization
    org_name = user.company if user.company else f"{user.name}'s Workspace"
    org = Organization(name=org_name)
    db.add(org)
    db.commit()
    db.refresh(org)

    membership = Membership(organization_id=org.id, user_id=user.id, role="owner")
    db.add(membership)
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id), user=user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    cfg = get_settings()
    ip = request.client.host if request.client else "unknown"
    email = payload.email.strip().lower()

    wait = login_limiter.blocked_for(
        ip,
        email,
        max_per_account=cfg.login_max_failures,
        max_per_ip=cfg.login_ip_max_failures,
        window=cfg.login_lockout_seconds,
    )
    if wait:
        minutes = max(1, round(wait / 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed sign-in attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(payload.password, user.password_hash if user else None)
    if not user or not ok:
        login_limiter.record_failure(ip, email, window=cfg.login_lockout_seconds)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    login_limiter.reset(ip, email)
    return TokenResponse(access_token=create_access_token(user.id), user=user)


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user
