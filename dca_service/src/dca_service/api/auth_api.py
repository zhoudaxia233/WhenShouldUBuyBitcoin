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
from dca_service.auth.password import hash_password, verify_password
from dca_service.auth.csrf import get_csrf_token, validate_csrf
from dca_service.core.logging import logger
from dca_service.config import settings
from dca_service.static_files import asset_url

# Setup templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_url"] = asset_url

router = APIRouter(prefix="/auth", tags=["auth"])

# Checked against when the email is unknown, so both cases take bcrypt time
# and response timing does not reveal which emails have accounts.
_UNKNOWN_USER_PASSWORD_HASH = hash_password("unknown-user-timing-equalizer")


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
        request=request,
        name="login.html",
        context={
            "csrf_token": csrf_token,
            "error": None,
            "project_name": settings.PROJECT_NAME,
            "app_version": settings.APP_VERSION,
            "app_commit_sha": settings.APP_COMMIT_SHA,
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
            request=request,
            name="login.html",
            context={
                "csrf_token": csrf_token,
                "error": "Security check failed. Please try again.",
                "project_name": settings.PROJECT_NAME,
                "app_version": settings.APP_VERSION,
                "app_commit_sha": settings.APP_COMMIT_SHA,
            },
            status_code=403
        )
    
    # Look up user by email
    statement = select(User).where(User.email == email)
    user = db.exec(statement).first()
    
    # Verify password (always run bcrypt, see _UNKNOWN_USER_PASSWORD_HASH)
    password_hash = user.password_hash if user else _UNKNOWN_USER_PASSWORD_HASH
    if not verify_password(password, password_hash) or not user:
        logger.warning(f"Failed login attempt for email: {email}")
        csrf_token = get_csrf_token(request)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": csrf_token,
                "error": "Invalid email or password",
                "project_name": settings.PROJECT_NAME,
                "app_version": settings.APP_VERSION,
                "app_commit_sha": settings.APP_COMMIT_SHA,
            },
            status_code=401
        )
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"Login attempt for inactive user: {email}")
        csrf_token = get_csrf_token(request)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "csrf_token": csrf_token,
                "error": "Account is disabled",
                "project_name": settings.PROJECT_NAME,
                "app_version": settings.APP_VERSION,
                "app_commit_sha": settings.APP_COMMIT_SHA,
            },
            status_code=403
        )
    
    # Create session
    request.session["user_id"] = user.id
    request.session["session_version"] = user.session_version
    logger.info(f"User logged in: {user.email}")
    
    # Redirect to dashboard/home
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_session)):
    """
    Log out the current user.
    
    Bumps the user's session version, which revokes every copy of the session
    cookie (other devices included), then clears this browser's session.
    No CSRF check required for logout (following OWASP guidelines).
    """
    user_id = request.session.get("user_id")
    if user_id:
        user = db.get(User, user_id)
        if user and request.session.get("session_version") == user.session_version:
            user.session_version += 1
            db.add(user)
            db.commit()
        logger.info(f"User logged out: user_id={user_id}")
    
    # Clear session
    request.session.clear()
    
    # Redirect to login
    return RedirectResponse(url="/api/auth/login", status_code=303)
