from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from dca_service.database import get_session
from dca_service.models import DCATransaction, ColdWalletEntry
from dca_service.api.schemas import TransactionRead, SimulationRequest, UnifiedTransaction

router = APIRouter()

@router.get("/transactions", response_model=List[UnifiedTransaction])
def read_transactions(
    offset: int = 0,
    limit: int = Query(default=1000, le=5000),  # Default 1000, max 5000 for safety
    session: Session = Depends(get_session)
):
    # Fetch DCA transactions
    dca_txs = session.exec(select(DCATransaction)).all()
    
    # Fetch Manual transactions (Cold Wallet)
    manual_txs = session.exec(select(ColdWalletEntry)).all()
    
    unified_list = []
    
    for tx in dca_txs:
        unified_list.append(UnifiedTransaction(
            id=f"DCA-{tx.id}",
            timestamp=tx.timestamp,
            type="DCA",
            status=tx.status,
            btc_amount=tx.btc_amount,
            fiat_amount=tx.fiat_amount,
            price=tx.price,
            notes=tx.notes,
            source=tx.source or "SIMULATED",
            ahr999=tx.ahr999
        ))
        
    for tx in manual_txs:
        unified_list.append(UnifiedTransaction(
            id=f"MAN-{tx.id}",
            timestamp=tx.timestamp,
            type="MANUAL",
            status="COMPLETED",
            btc_amount=tx.btc_amount,
            fiat_amount=None,
            price=None,
            notes=tx.notes,
            source="LEDGER",
            fee_usdc=None
        ))
    
    # Sort by timestamp desc
    unified_list.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Apply offset and limit
    return unified_list[offset : offset + limit]

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
