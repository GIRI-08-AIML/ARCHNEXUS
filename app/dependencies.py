from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal, get_db  # noqa: F401  (re-exported)
from app.llm import LLMClient
from app.llm import get_llm as _get_llm
from app.models import User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_llm() -> LLMClient:
    return _get_llm()


def get_session_factory() -> sessionmaker:
    return SessionLocal


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = None,
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Please sign in to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw_token = creds.credentials if creds else token
    if not raw_token:
        raise unauthorized
    user_id = decode_access_token(raw_token)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise unauthorized
    return user
