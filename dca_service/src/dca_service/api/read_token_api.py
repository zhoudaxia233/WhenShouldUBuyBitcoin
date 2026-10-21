"""
Read-only API token.

Lets another program read GET /api/wallet/summary with
`Authorization: Bearer <token>`. One active token per user: creating a new one
replaces the old one. Only the hash is stored; the token is returned once.
Managing the token itself needs the session login.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from dca_service.auth.dependencies import get_current_user, hash_read_token
from dca_service.core.logging import logger
from dca_service.database import get_session
from dca_service.models import ReadToken, User

router = APIRouter(prefix="/read-token", tags=["read-token"])


def _utc_iso(value: datetime) -> str:
    # SQLite returns naive datetimes; they are stored as UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _user_tokens(session: Session, user: User) -> list[ReadToken]:
    return list(session.exec(select(ReadToken).where(ReadToken.user_id == user.id)).all())


@router.get("")
def get_read_token_status(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Whether a token exists and when it was created, never the token."""
    tokens = _user_tokens(session, current_user)
    if not tokens:
        return {"has_token": False, "created_at": None}
    return {"has_token": True, "created_at": _utc_iso(tokens[0].created_at)}


@router.post("")
def create_read_token(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a token, replacing any existing one. The response is the only time it is shown."""
    for old in _user_tokens(session, current_user):
        session.delete(old)
    token = "wsub_" + secrets.token_urlsafe(32)
    row = ReadToken(user_id=current_user.id, token_hash=hash_read_token(token))
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info("Read-only API token created")
    return {"token": token, "created_at": _utc_iso(row.created_at)}


@router.delete("")
def revoke_read_token(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    for old in _user_tokens(session, current_user):
        session.delete(old)
    session.commit()
    logger.info("Read-only API token revoked")
    return {"success": True}
