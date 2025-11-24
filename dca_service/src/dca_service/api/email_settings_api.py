"""
Email Settings API
Handles saving/retrieving email SMTP configuration with encryption
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import EmailSettings
from dca_service.services.security import encrypt_text, decrypt_text

router = APIRouter()


class EmailSettingsRequest(BaseModel):
    """Request model for saving email settings"""
    is_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: Optional[str] = None  # Optional for updates
    email_to: str


@router.post("/email/settings")
def save_email_settings(
    settings: EmailSettingsRequest,
    session: Session = Depends(get_session)
):
    """
    Save email SMTP settings with encrypted password.
    Creates new record or updates existing one.
    Password is optional - if not provided, keeps existing password.
    """
    # Check if settings exist
    existing = session.exec(select(EmailSettings)).first()
    
    # For new configs, password is required
    if not existing and not settings.smtp_password:
        raise HTTPException(
            status_code=400,
            detail="Password is required for new email configuration"
        )
    
    # Encrypt password if provided
    encrypted_password = None
    if settings.smtp_password:
        encrypted_password = encrypt_text(settings.smtp_password)
    
    if existing:
        # Update existing
        existing.is_enabled = settings.is_enabled
        existing.smtp_host = settings.smtp_host
        existing.smtp_port = settings.smtp_port
        existing.smtp_user = settings.smtp_user
        # Only update password if provided
        if encrypted_password:
            existing.smtp_password_encrypted = encrypted_password
        # Use smtp_user as email_from (Gmail ignores custom From anyway)
        existing.email_from = settings.smtp_user
        existing.email_to = settings.email_to
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
    else:
        # Create new
        new_settings = EmailSettings(
            is_enabled=settings.is_enabled,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password_encrypted=encrypted_password,
            email_from=settings.smtp_user,  # Use smtp_user as sender
            email_to=settings.email_to
        )
        session.add(new_settings)
    
    session.commit()
    
    return {"success": True, "message": "Email settings saved successfully"}


@router.get("/email/settings/status")
def get_email_settings_status(session: Session = Depends(get_session)):
    """
    Get status of email settings (whether configured, masked values).
    Does not return the password.
    """
    settings = session.exec(select(EmailSettings)).first()
    
    if not settings:
        return {
            "has_settings": False,
            "is_enabled": False
        }
    
    # Mask SMTP user/email for display
    def mask_email(email: str) -> str:
        if "@" in email:
            local, domain = email.split("@", 1)
            if len(local) > 4:
                masked = local[:2] + "****" + local[-2:]
            else:
                masked = local[0] + "****"
            return f"{masked}@{domain}"
        return "****"
    
    return {
        "has_settings": True,
        "is_enabled": settings.is_enabled,
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "smtp_user_masked": mask_email(settings.smtp_user),
        "email_from_masked": mask_email(settings.email_from),
        "email_to_masked": mask_email(settings.email_to),
        "updated_at": settings.updated_at.isoformat()
    }


class EmailToggleRequest(BaseModel):
    """Request model for toggling email status"""
    is_enabled: bool


@router.post("/email/settings/toggle")
def toggle_email_settings(
    toggle: EmailToggleRequest,
    session: Session = Depends(get_session)
):
    """
    Enable or disable email notifications without changing other settings.
    """
    settings = session.exec(select(EmailSettings)).first()
    
    if not settings:
        raise HTTPException(
            status_code=404,
            detail="Email settings not configured. Please configure settings first."
        )
    
    settings.is_enabled = toggle.is_enabled
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    
    status = "enabled" if toggle.is_enabled else "disabled"
    return {"success": True, "message": f"Email notifications {status}"}
