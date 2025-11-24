"""
Email notification service for DCA executions

Provides a simple, robust email sending capability with graceful error handling.
Email failures do not affect DCA execution.

Reads settings from database first, falls back to environment variables.
"""
import smtplib
import logging
from email.message import EmailMessage
from typing import Optional
from sqlmodel import Session, select

from dca_service.config import settings
from dca_service.database import engine
from dca_service.models import EmailSettings

logger = logging.getLogger(__name__)


def _get_email_config() -> Optional[dict]:
    """
    Get email configuration from database first, fallback to environment variables.
    
    Returns:
        dict with email config or None if disabled/not configured
    """
    # Try database first
    try:
        with Session(engine) as session:
            db_settings = session.exec(select(EmailSettings)).first()
            if db_settings and db_settings.is_enabled:
                # Decrypt password
                from dca_service.services.security import decrypt_text
                decrypted_password = decrypt_text(db_settings.smtp_password_encrypted)
                
                return {
                    "enabled": True,
                    "smtp_host": db_settings.smtp_host,
                    "smtp_port": db_settings.smtp_port,
                    "smtp_user": db_settings.smtp_user,
                    "smtp_password": decrypted_password,
                    "email_from": db_settings.smtp_user,  # Always use smtp_user as sender
                    "email_to": db_settings.email_to,
                    "source": "database"
                }
    except Exception as e:
        logger.debug(f"Could not load email settings from database: {e}")
    
    # Fallback to environment variables
    if not settings.EMAIL_ENABLED:
        return None
    
    if not all([
        settings.EMAIL_SMTP_HOST,
        settings.EMAIL_SMTP_USER,
        settings.EMAIL_SMTP_PASSWORD,
        settings.EMAIL_FROM,
        settings.EMAIL_TO
    ]):
        return None
    
    return {
        "enabled": True,
        "smtp_host": settings.EMAIL_SMTP_HOST,
        "smtp_port": settings.EMAIL_SMTP_PORT,
        "smtp_user": settings.EMAIL_SMTP_USER,
        "smtp_password": settings.EMAIL_SMTP_PASSWORD,
        "email_from": settings.EMAIL_FROM,
        "email_to": settings.EMAIL_TO,
        "source": "environment"
    }


def send_email(subject: str, body: str) -> None:
    """
    Send an email notification.
    
    This function is designed to fail gracefully - any errors are logged
    but not raised, ensuring that email failures don't affect the main
    application flow.
    
    Args:
        subject: Email subject line
        body: Email body (plain text)
        
    Returns:
        None (fire-and-forget)
    """
    # Get configuration (DB or env)
    config = _get_email_config()
    
    if not config:
        logger.debug("Email notifications are disabled or not configured")
        return
    
    try:
        # Create message
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = config['email_from']
        msg['To'] = config['email_to']
        msg.set_content(body)
        
        # Connect to SMTP server with TLS
        with smtplib.SMTP(config['smtp_host'], config['smtp_port'], timeout=10) as server:
            server.starttls()
            server.login(config['smtp_user'], config['smtp_password'])
            server.send_message(msg)
        
        logger.info(
            f"Email sent successfully: '{subject}' to {config['email_to']} "
            f"(source: {config['source']})"
        )
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed for {config['smtp_host']}: {e}")
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email to {config['email_to']}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}", exc_info=True)
