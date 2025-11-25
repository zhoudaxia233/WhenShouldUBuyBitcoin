"""
Email notification service for DCA executions

Provides a simple, robust email sending capability with graceful error handling.
Email failures do not affect DCA execution.

Reads settings from database first, falls back to environment variables.
"""
import smtplib
import smtplib
from email.message import EmailMessage
from typing import Optional
from sqlmodel import Session, select

from dca_service.config import settings
from dca_service.database import engine
from dca_service.models import EmailSettings
from dca_service.core.logging import logger


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


def send_trade_failure_notification(transaction, decision, error_msg: str):
    """
    Send email notification for a failed LIVE trade.
    
    Args:
        transaction: The failed DCATransaction record
        decision: The DCADecision that was attempted
        error_msg: User-friendly error message
    """
    config = _get_email_config()
    if not config:
        logger.debug("Email not configured, skipping failure notification")
        return
    
    subject = f"⚠ DCA Trade FAILED - {error_msg[:50]}"
    
    body = f"""
LIVE DCA Trade Failed

An attempt to execute a LIVE trade on Binance has failed.

===== TRADE DETAILS =====
Status: FAILED
Attempted Amount: ${transaction.intended_amount_usd:.2f}
Expected BTC: ~{decision.suggested_amount_usd / decision.price_usd:.8f}
BTC Price: ${decision.price_usd:.2f}
AHR999: {decision.ahr999_value:.4f}
Time: {transaction.timestamp}

===== ERROR =====
{error_msg}

===== TROUBLESHOOTING =====
Common issues:
1. Invalid API Key or Secret - Check Binance settings
2. Insufficient trading permissions - Enable "Spot & Margin Trading" in Binance API settings
3. Insufficient funds - Ensure you have USDC/USDT in Spot wallet
4. Network issues - Temporary connectivity problem

===== NEXT STEPS =====
1. Review the error message above
2. Check your Binance settings at: http://localhost:8000/settings/binance
3. The system will retry on the next scheduled run
4. No funds were spent in this failed attempt

---
Bitcoin DCA Service
Trade safely and HODL wisely!
"""
    
    send_email(subject, body)


def send_dca_notification(transaction, decision=None):
    """
    Send a standardized email notification for a DCA execution.
    
    Args:
        transaction: The DCATransaction object
        decision: Optional DCADecision object (for extra context)
    """
    # Build email subject
    subject = f"DCA Executed: ${transaction.fiat_amount:.2f} USDC for BTC"
    if transaction.source == "SIMULATED":
        subject = f"DCA Simulation: ${transaction.fiat_amount:.2f} USDC for BTC"
    
    # Format timestamp
    exec_time = transaction.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Get band info if available
    band_info = "N/A"
    if decision and hasattr(decision, 'band'):
        band_info = decision.band
    
    body = f"""DCA Transaction Executed Successfully

Execution Time: {exec_time}
AHR999 Value: {transaction.ahr999:.4f}
Decision Band: {band_info}

Amount (USDC): ${transaction.fiat_amount:.2f}
Amount (BTC): {transaction.btc_amount:.8f}
Price (USD/BTC): ${transaction.price:.2f}

Transaction Details:
- Transaction ID: {transaction.id}
- Source: {transaction.source}
- Status: {transaction.status}

Notes: {transaction.notes or 'None'}

---
This is an automated notification from your DCA Service.
"""
    
    send_email(subject, body)
