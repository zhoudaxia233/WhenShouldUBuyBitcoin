"""
Authentication API routes.

Provides:
- GET /auth/login: Display login form
- POST /auth/login: Process login
- POST /auth/logout: Log out user
"""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from pathlib import Path

from dca_service.models import User
from dca_service.database import get_session
from dca_service.auth.password import verify_password
from dca_service.auth.csrf import get_csrf_token, validate_csrf
from dca_service.core.logging import logger

# Setup templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    Display the login form.
    
    If user is already logged in, redirect to dashboard.
    Otherwise, render login.html with CSRF token.
    """
    # Check if already logged in
    if "user_id" in request.session:
        return RedirectResponse(url="/", status_code=303)
    
    csrf_token = get_csrf_token(request)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "csrf_token": csrf_token,
            "error": None
        }
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_session)
):
    """
    Process login form submission.
    
    Steps:
    1. Validate CSRF token
    2. Look up user by email
    3. Verify password
    4. Check user is active
    5. Create session
    6. Redirect to dashboard
    
    On failure: Re-render login form with error message
    """
    # Validate CSRF token
    try:
        validate_csrf(request, csrf_token)
    except Exception as e:
        logger.warning(f"CSRF validation failed: {e}")
        csrf_token = get_csrf_token(request)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "csrf_token": csrf_token,
                "error": "Security check failed. Please try again."
            },
            status_code=403
        )
    
    # Look up user by email
    statement = select(User).where(User.email == email)
    user = db.exec(statement).first()
    
    # Verify password
    if not user or not verify_password(password, user.password_hash):
        logger.warning(f"Failed login attempt for email: {email}")
        csrf_token = get_csrf_token(request)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "csrf_token": csrf_token,
                "error": "Invalid email or password"
            },
            status_code=401
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {email}")
        csrf_token = get_csrf_token(request)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "csrf_token": csrf_token,
                "error": "Account is disabled"
            },
            status_code=403
        )
    
    # Create session
    request.session["user_id"] = user.id
    logger.info(f"User logged in: {user.email}")
    
    # Redirect to dashboard/home
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    """
    Log out the current user.
    
    Clears the session and redirects to login page.
    No CSRF check required for logout (following OWASP guidelines).
    """
    # Log the action
    user_id = request.session.get("user_id")
    if user_id:
        logger.info(f"User logged out: user_id={user_id}")
    
    # Clear session
    request.session.clear()
    
    # Redirect to login
    return RedirectResponse(url="/api/auth/login", status_code=303)
