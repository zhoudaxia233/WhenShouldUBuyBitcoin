from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, col, delete
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import DCATransaction, BinanceCredentials, User
from dca_service.api.schemas import TransactionRead, SimulationRequest, UnifiedTransaction
from dca_service.services.binance_client import BinanceClient
from dca_service.services.security import decrypt_text
from dca_service.core.logging import logger
from dca_service.auth.dependencies import get_current_user

router = APIRouter()
_static_generation_process = None
_static_generation_last_result = None


def _try_collect_static_generation_status() -> Optional[dict]:
    """
    Best-effort status probe for current background process.
    Returns None if no process or probe fails.
    """
    global _static_generation_process
    if _static_generation_process is None:
        return None
    try:
        from dca_service.services.static_generator import check_static_generation_status
        return check_static_generation_status(_static_generation_process)
    except Exception as e:
        logger.warning(f"Failed to probe static generation process status, resetting state: {e}")
        _static_generation_process = None
        return None


def _get_binance_client(session: Session) -> Optional[BinanceClient]:
    """Get authenticated Binance client (READ_ONLY preferred)"""
    # Try READ_ONLY first
    creds = session.query(BinanceCredentials).filter(
        BinanceCredentials.credential_type == "READ_ONLY"
    ).first()
    
    # Fallback to TRADING
    if not creds:
        creds = session.query(BinanceCredentials).filter(
            BinanceCredentials.credential_type == "TRADING"
        ).first()
    
    if not creds:
        return None
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
        return BinanceClient(api_key, api_secret)
    except Exception:
        return None


@router.get("/transactions", response_model=List[UnifiedTransaction])
async def read_transactions(
    offset: int = 0,
    limit: int = Query(default=1000, le=5000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Fetch list of all transactions from LOCAL DATABASE only.
    Includes both DCA transactions and synced manual trades.
    """
    # Fetch all transactions from database (DCA + Manual)
    # Sort by timestamp descending
    statement = select(DCATransaction).order_by(col(DCATransaction.timestamp).desc()).offset(offset).limit(limit)
    transactions = session.exec(statement).all()
    
    unified_list = []
    
    for tx in transactions:
        # Determine badge
        if tx.is_manual:
            badge = "MANUAL"
            tx_type = "MANUAL"
        elif tx.source == "SIMULATED":
            badge = "SIMULATED"
            tx_type = "DCA"
        else:
            badge = "DCA"
            tx_type = "DCA"
            
        # Ensure timestamp is timezone-aware
        tx_timestamp = tx.timestamp
        if tx_timestamp.tzinfo is None:
            tx_timestamp = tx_timestamp.replace(tzinfo=timezone.utc)
            
        unified_list.append(UnifiedTransaction(
            id=tx.binance_order_id or tx.id,  # Use Binance Order ID if available, else DB ID
            timestamp=tx_timestamp,
            type=tx_type,
            status=tx.status,
            btc_amount=tx.executed_amount_btc or tx.btc_amount or 0.0,
            fiat_amount=tx.executed_amount_usd or tx.fiat_amount or 0.0,
            price=tx.avg_execution_price_usd or tx.price or 0.0,
            notes=tx.notes,
            source=badge,
            ahr999=tx.ahr999,
            fee_amount=tx.fee_amount or 0.0,
            fee_asset=tx.fee_asset or "USDC"
        ))
    
    return unified_list


@router.post("/transactions/sync")
async def sync_transactions(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Trigger manual synchronization of trades from Binance.
    Fetches only new trades since the last sync.
    """
    from dca_service.services.sync_service import TradeSyncService
    
    service = TradeSyncService(session)
    count = await service.sync_trades()
    
    return {"success": True, "new_trades_count": count}

@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def read_transaction(
    transaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    transaction = session.get(DCATransaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction



@router.post("/transactions/clear-simulated")
async def clear_simulated_transactions(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)  # 认证保护
):
    """
    Reset transaction history and re-sync from Binance.
    Deletes ALL local transactions and fetches fresh data from Binance.
    
    Returns:
        dict: Success status and sync result
    """
    # Delete ALL transactions
    # Note: We use delete() with where(True) or just delete(DCATransaction) depending on SQLModel version
    # But session.exec(delete(DCATransaction)) is the standard way
    statement = delete(DCATransaction)
    session.exec(statement)
    session.commit()
    
    # Trigger sync from scratch
    from dca_service.services.sync_service import TradeSyncService
    
    service = TradeSyncService(session)
    count = await service.sync_trades(start_from_scratch=True)
    
    return {
        "success": True,
        "deleted_count": "ALL",
        "synced_count": count,
        "message": f"History reset. Synced {count} trades from Binance."
    }


@router.post("/email/test")
def test_email(current_user: User = Depends(get_current_user)):  # Authentication required
    """
    Test email configuration by sending a test message.
    Checks database settings first, then environment variables.
    
    Returns:
        dict: {"success": true} on success, {"success": false, "error": "..."} on failure
    """
    from dca_service.services.mailer import send_email, _get_email_config
    from dca_service.config import settings
    
    # Check if email is configured (DB or env)
    config = _get_email_config()
    
    if not config:
        return {
            "success": False,
            "error": "Email is not configured. Please fill in SMTP settings and enable email notifications."
        }
    
    try:
        # Send test email
        subject = "DCA Service Email Test"
        body = f"""If you received this, email configuration works!

Configuration Details:
- SMTP Host: {config['smtp_host']}
- SMTP Port: {config['smtp_port']}
- From: {config['email_from']}
- To: {config['email_to']}
- Source: {config['source']}

This is a test message from your DCA Service."""
        
        send_email(subject, body)
        
        return {"success": True}
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/static/regenerate")
async def regenerate_static_files(
    current_user: User = Depends(get_current_user)  # Authentication required
):
    """
    Manually trigger regeneration of static files (charts, data, etc.).
    
    Runs main.py as a background process to update all analysis files.
    This is the same process that runs automatically after DCA transactions.
    
    Returns:
        dict: {"success": true, "message": "...", "background": true} on success
    """
    global _static_generation_process, _static_generation_last_result
    try:
        from dca_service.services.static_generator import (
            trigger_static_generation,
        )

        if _static_generation_process is not None:
            status = _try_collect_static_generation_status()
            if status and status.get("running"):
                return {
                    "success": True,
                    "message": "Static generation is already running.",
                    "background": True,
                    "pid": _static_generation_process.pid,
                    "running": True,
                }
            if status:
                _static_generation_last_result = status
                _static_generation_process = None

        process = trigger_static_generation(background=True)
        _static_generation_process = process
        _static_generation_last_result = None

        return {
            "success": True,
            "message": "Static file generation started in background. This may take 30-120 seconds.",
            "background": True,
            "pid": process.pid if process else None,
            "running": True,
        }
    except FileNotFoundError as e:
        logger.error(f"Failed to trigger static generation: {e}")
        return {
            "success": False,
            "error": "main.py not found. Check server configuration."
        }
    except Exception as e:
        logger.error(f"Error triggering static generation: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/static/regenerate/status")
async def regenerate_static_files_status(
    current_user: User = Depends(get_current_user)
):
    """
    Check current static regeneration task status.

    Returns running/completed/failed state with brief output.
    """
    global _static_generation_process, _static_generation_last_result

    if _static_generation_process is not None:
        status = _try_collect_static_generation_status()
        if status and status.get("running"):
            return {
                "success": True,
                "running": True,
                "completed": False,
                "exit_code": None,
                "message": "Static generation is running.",
            }

        if status:
            _static_generation_last_result = status
            _static_generation_process = None

    if _static_generation_last_result is None:
        return {
            "success": True,
            "running": False,
            "completed": False,
            "exit_code": None,
            "message": "No static generation task has run yet in this server process.",
        }

    exit_code = _static_generation_last_result.get("exit_code")
    stderr = (_static_generation_last_result.get("stderr") or "").strip()
    stdout = (_static_generation_last_result.get("stdout") or "").strip()
    failed = exit_code not in (0, None)

    return {
        "success": not failed,
        "running": False,
        "completed": True,
        "exit_code": exit_code,
        "message": "Static generation completed successfully." if not failed else "Static generation failed.",
        "stderr_preview": stderr[-500:] if stderr else "",
        "stdout_preview": stdout[-500:] if stdout else "",
    }
