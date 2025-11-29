"""
Authentication dependencies for FastAPI routes.

Provides:
- get_current_user: Extract user from session
- get_current_admin_user: Require admin role
- Custom exceptions for auth errors
"""
from fastapi import Request, Depends, HTTPException, status
from sqlmodel import Session, select
from dca_service.models import User
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
    3. User is active
    
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


# Convenience aliases
login_required = Depends(get_current_user)
admin_required = Depends(get_current_admin_user)
