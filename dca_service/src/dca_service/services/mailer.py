"""
Email notification service for DCA executions

Provides a simple, robust email sending capability with graceful error handling.
Email failures do not affect DCA execution.

Reads settings from database first, falls back to environment variables.
"""
import smtplib
from email.message import EmailMessage
from typing import Optional
from sqlmodel import Session, select

from dca_service.config import settings
from dca_service.database import engine
from dca_service.models import EmailSettings, GlobalSettings, DCATransaction, DCAStrategy
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


def _get_total_btc_balance(session: Session) -> float:
    """
    Calculate total BTC balance (Cold + Hot).
    Reuses logic from wallet_api but adapted for synchronous execution.
    """
    try:
        # 1. Get Cold Wallet Balance
        settings_obj = session.get(GlobalSettings, 1)
        cold_balance = settings_obj.cold_wallet_balance if settings_obj else 0.0
        
        # 2. Get Hot Wallet Balance (Binance)
        # Note: This is a synchronous call, so we can't easily use the async BinanceClient
        # For now, we will just use the cold wallet balance + sum of all successful DCA transactions as an approximation
        # OR we could try to fetch from Binance if we had a sync client.
        # Given the constraints, let's use the database record of transactions as a proxy for "Hot Wallet" 
        # if we can't reach Binance synchronously.
        # BETTER APPROACH: Just use the cold wallet balance + all successful buys in DB.
        
        txs = session.exec(
            select(DCATransaction)
            .where(
                DCATransaction.status == "SUCCESS",
                DCATransaction.source != "SIMULATED"
            )
        ).all()
        
        hot_balance_approx = sum(tx.btc_amount or 0.0 for tx in txs)
        
        # Note: This approximation doesn't account for withdrawals or manual trades not in DB.
        # But it's better than blocking on async calls or adding complex sync dependencies.
        # If the user has "Incremental Trade Sync" enabled (Phase 7), the DB should be accurate!
        
        return cold_balance + hot_balance_approx
        
    except Exception as e:
        logger.warning(f"Error calculating total BTC balance: {e}")
        return 0.0


def _get_goal_progress(session: Session, total_btc: float) -> str:
    """
    Calculate progress towards BTC goal (e.g., "1.5000 / 2.0000 BTC (75.00%)").
    """
    try:
        strategy = session.exec(select(DCAStrategy)).first()
        if not strategy or not strategy.target_btc_amount:
            return "N/A (No target set)"
            
        target = strategy.target_btc_amount
        percentage = (total_btc / target) * 100.0
        
        return f"{total_btc:.4f} / {target:.4f} BTC ({percentage:.2f}%)"
        
    except Exception as e:
        logger.warning(f"Error calculating goal progress: {e}")
        return "N/A"


def send_dca_notification(transaction, decision=None, total_btc: Optional[float] = None):
    """
    Send a standardized email notification for a DCA execution.
    
    Args:
        transaction: The DCATransaction object
        decision: Optional DCADecision object (for extra context)
        total_btc: Optional total BTC balance (if already fetched from Binance)
    """
    # Build email subject
    subject = f"DCA Executed: ${transaction.fiat_amount:.2f} USDC for BTC"
    if transaction.source == "SIMULATED":
        subject = f"DCA Simulation: ${transaction.fiat_amount:.2f} USDC for BTC"
    
    # Format timestamp
    exec_time = transaction.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Get band info
    band_info = "N/A"
    if decision and hasattr(decision, 'ahr_band'):
        band_info = decision.ahr_band
    elif decision and hasattr(decision, 'band'): # Fallback
        band_info = decision.band
        
    # Calculate Stats
    try:
        with Session(engine) as session:
            # Use provided total_btc or calculate from DB (fallback)
            if total_btc is None:
                total_btc = _get_total_btc_balance(session)
            
            progress_str = _get_goal_progress(session, total_btc)
    except Exception as e:
        logger.error(f"Error fetching stats for email: {e}")
        if total_btc is None:
            total_btc = 0.0
        progress_str = "N/A"
    
    body = f"""DCA Transaction Executed Successfully

Execution Time: {exec_time}
AHR999 Value: {transaction.ahr999:.4f}
Decision Band: {band_info}

Amount (USDC): ${transaction.fiat_amount:.2f}
Amount (BTC): {transaction.btc_amount:.8f}
Price (USD/BTC): ${transaction.price:.2f}

Portfolio Stats:
- Total BTC Balance: {total_btc:.8f} BTC
- Goal Progress: {progress_str}

Notes: {transaction.notes or 'None'}

---
This is an automated notification from your DCA Service.
"""
    
    send_email(subject, body)
