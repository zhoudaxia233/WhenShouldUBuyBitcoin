from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, col
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import DCATransaction, BinanceCredentials
from dca_service.api.schemas import TransactionRead, SimulationRequest, UnifiedTransaction
from dca_service.services.binance_client import BinanceClient
from dca_service.services.security import decrypt_text
from dca_service.core.logging import logger

router = APIRouter()


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
    session: Session = Depends(get_session)
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
async def sync_transactions(session: Session = Depends(get_session)):
    """
    Trigger manual synchronization of trades from Binance.
    Fetches only new trades since the last sync.
    """
    from dca_service.services.sync_service import TradeSyncService
    
    service = TradeSyncService(session)
    count = await service.sync_trades()
    
    return {"success": True, "new_trades_count": count}

@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def read_transaction(transaction_id: int, session: Session = Depends(get_session)):
    transaction = session.get(DCATransaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction

@router.post("/transactions/simulate", response_model=TransactionRead)
def simulate_transaction(
    request: SimulationRequest,
    session: Session = Depends(get_session)
):
    # Simulate a successful buy
    # In a real scenario, this would call Binance API
    
    # Calculate dummy BTC amount
    btc_amount = request.fiat_amount / request.price if request.price > 0 else 0
    
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=request.fiat_amount,
        btc_amount=btc_amount,
        price=request.price,
        ahr999=request.ahr999,
        notes=request.notes or "Simulated transaction",
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction

@router.post("/transactions/clear-simulated")
def clear_simulated_transactions(session: Session = Depends(get_session)):
    """
    Clear all simulated transactions while preserving manual/ledger entries.
    Only works in DRY_RUN mode.
    
    Returns:
        dict: Success status, number of deleted transactions, and message
    """
    # Import here to avoid circular dependency
    from dca_service.api.strategy_api import get_execution_mode
    
    # Check execution mode
    execution_mode = get_execution_mode(session)
    if execution_mode != "DRY_RUN":
        raise HTTPException(
            status_code=400,
            detail="Cannot clear simulated history in LIVE mode. Switch to DRY_RUN mode first."
        )
    
    # Delete only SIMULATED transactions (and any with NULL source that aren't manual entries)
    # We need to be careful to preserve LEDGER (manual) entries only
    # Delete transactions where:
    # 1. source == "SIMULATED" explicitly
    # 2. source is NULL or empty (legacy transactions that should be treated as simulated)
    # But NEVER delete source == "LEDGER" or "BINANCE"
    simulated_txs = session.exec(
        select(DCATransaction).where(
            (DCATransaction.source == "SIMULATED") | 
            (DCATransaction.source == None) |
            (DCATransaction.source == "")
        )
    ).all()
    
    deleted_count = len(simulated_txs)
    
    for tx in simulated_txs:
        session.delete(tx)
    
    session.commit()
    
    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Cleared {deleted_count} simulated transaction(s). Manual entries preserved."
    }


@router.post("/email/test")
def test_email():
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
