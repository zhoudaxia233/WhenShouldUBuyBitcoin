"""
CSRF (Cross-Site Request Forgery) protection utilities.

Security notes:
- CSRF tokens are stored in the session
- Tokens are cryptographically random (secrets.token_urlsafe)
- All state-changing forms must include and validate CSRF tokens
- GET requests do not require CSRF protection (idempotent)
"""
import secrets
from fastapi import Request, HTTPException


CSRF_TOKEN_KEY = "_csrf_token"


def get_csrf_token(request: Request) -> str:
    """
    Get or generate a CSRF token for the current session.
    
    If a token already exists in the session, return it.
    Otherwise, generate a new cryptographically secure token,
    store it in the session, and return it.
    
    Args:
        request: FastAPI Request object with session
        
    Returns:
        CSRF token string
        
    Example in template:
        <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    """
    # Check if token exists in session
    if CSRF_TOKEN_KEY in request.session:
        return request.session[CSRF_TOKEN_KEY]
    
    # Generate new token (32 bytes = 256 bits of entropy)
    token = secrets.token_urlsafe(32)
    request.session[CSRF_TOKEN_KEY] = token
    return token


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    """
    Validate a CSRF token from a form submission.
    
    Compares the submitted token with the token stored in the session.
    Raises HTTPException(403) if:
    - No token was submitted
    - Token doesn't match the session token
    - No session token exists
    
    Args:
        request: FastAPI Request object with session
        submitted_token: The CSRF token from the form
        
    Raises:
        HTTPException: 403 Forbidden if validation fails
        
    Example in route:
        @router.post("/important-action")
        async def important_action(
            request: Request,
            csrf_token: str = Form(...)
        ):
            validate_csrf(request, csrf_token)
            # ... process action
    """
    session_token = request.session.get(CSRF_TOKEN_KEY)
    
    if not submitted_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing"
        )
    
    if not session_token:
        raise HTTPException(
            status_code=403,
            detail="No CSRF token in session"
        )
    
    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(submitted_token, session_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF token"
        )
