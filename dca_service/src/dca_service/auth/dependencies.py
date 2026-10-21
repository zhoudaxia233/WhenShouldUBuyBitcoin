"""
Authentication dependencies for FastAPI routes.

Provides:
- get_current_user: Extract user from session
- get_current_admin_user: Require admin role
- get_session_or_read_token_user: Session or read-only token (wallet summary only)
- Custom exceptions for auth errors
"""
import hashlib
import secrets

from fastapi import Request, Depends, HTTPException, status
from sqlmodel import Session, select
from dca_service.models import ReadToken, User
from dca_service.database import get_session


class AuthenticationError(HTTPException):
    """Raised when user is not authenticated."""
    def __init__(self, detail: str = "Not authenticated"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class PermissionDeniedError(HTTPException):
    """Raised when user lacks required permissions."""
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def get_current_user(
    request: Request,
    db: Session = Depends(get_session)
) -> User:
    """
    Get the current authenticated user from the session.
    
    Checks:
    1. User ID exists in session
    2. User exists in database
    3. Session version matches (logout revokes all copies of the cookie)
    4. User is active
    
    Args:
        request: FastAPI Request with session
        db: Database session
        
    Returns:
        User object
        
    Raises:
        AuthenticationError: If not authenticated or user inactive
        
    Usage:
        @router.get("/protected")
        def protected_route(user: User = Depends(get_current_user)):
            return {"user_email": user.email}
    """
    # Check if user_id is in session
    user_id = request.session.get("user_id")
    if not user_id:
        raise AuthenticationError("Not authenticated")
    
    # Query user from database
    statement = select(User).where(User.id == user_id)
    user = db.exec(statement).first()
    
    if not user:
        # User was deleted or session is stale
        request.session.clear()
        raise AuthenticationError("User not found")
    
    if request.session.get("session_version") != user.session_version:
        # Revoked by logout, or signed before session versions existed
        request.session.clear()
        raise AuthenticationError("Session revoked")
    
    if not user.is_active:
        # User account is disabled
        request.session.clear()
        raise AuthenticationError("User account is disabled")
    
    return user


def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require that the current user has admin privileges.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        User object (with is_admin=True)
        
    Raises:
        PermissionDeniedError: If user is not an admin
        
    Usage:
        @router.post("/admin/sensitive-action")
        def admin_only(user: User = Depends(get_current_admin_user)):
            return {"message": "Admin action completed"}
    """
    if not current_user.is_admin:
        raise PermissionDeniedError("Admin access required")
    
    return current_user


def hash_read_token(token: str) -> str:
    """Tokens are 256-bit random values, so a plain SHA-256 is enough to store them."""
    return hashlib.sha256(token.encode()).hexdigest()


def bearer_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer <token>`, or None if the header is absent."""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def get_session_or_read_token_user(
    request: Request,
    db: Session = Depends(get_session)
) -> User:
    """
    Session login, or the read-only token for programs.

    Use only on read endpoints that the token is meant to open
    (GET /wallet/summary); every other route keeps get_current_user.
    """
    token = bearer_token(request)
    if token is None:
        return get_current_user(request, db)

    if token:
        digest = hash_read_token(token)
        # Few rows; compare every one so timing says nothing about a match
        match = None
        for row in db.exec(select(ReadToken)).all():
            if secrets.compare_digest(row.token_hash, digest):
                match = row
        if match:
            user = db.get(User, match.user_id)
            if user and user.is_active:
                return user

    raise AuthenticationError("Invalid token")


# Convenience aliases
login_required = Depends(get_current_user)
admin_required = Depends(get_current_admin_user)
