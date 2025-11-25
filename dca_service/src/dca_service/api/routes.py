from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
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
    Fetch unified list of all transactions:
    - DCA transactions (SIMULATED or LIVE via bot)
    - Manual Binance trades (not triggered by bot)
    """
    # 1. Fetch DCA transactions from database
    dca_txs = session.exec(select(DCATransaction)).all()
    dca_order_ids = {tx.binance_order_id for tx in dca_txs if tx.binance_order_id}
    
    # 2. Fetch all Binance trades
    binance_trades = []
    try:
        client = _get_binance_client(session)
        if client:
            trades_response = await client.get_all_btc_trades()
            await client.close()
            binance_trades = trades_response
    except Exception as e:
        logger.warning(f"Could not fetch Binance trades: {e}")
    
    # 3. Convert to unified format
    unified_list = []
    
    # Add DCA transactions
    for tx in dca_txs:
        # Determine badge: SIMULATED or DCA
        badge = "SIMULATED" if tx.source == "SIMULATED" else "DCA"
        
        # Ensure timestamp is timezone-aware
        tx_timestamp = tx.timestamp
        if tx_timestamp.tzinfo is None:
            tx_timestamp = tx_timestamp.replace(tzinfo=timezone.utc)
        
        unified_list.append(UnifiedTransaction(
            id=tx.id,
            timestamp=tx_timestamp,
            type="DCA",
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
    
    # Add manual Binance trades (not triggered by DCA bot)
    for trade in binance_trades:
        trade_id = trade.get("orderId")
        
        # Skip if this trade was executed by the DCA bot
        if trade_id in dca_order_ids:
            continue
        
        # Only show buy trades
        if not trade.get("isBuyer"):
            continue
        
        # Convert timestamp (milliseconds to datetime, UTC aware)
        ts = datetime.fromtimestamp(trade["time"] / 1000, tz=timezone.utc)
        
        qty = float(trade["qty"])
        price = float(trade["price"])
        total_usd = qty * price
        
        # Extract fee information and convert to USD
        fee_amount_raw = float(trade.get("commission", 0.0))
        fee_asset = trade.get("commissionAsset", "")
        
        # Convert fee to USD value
        fee_usd = 0.0
        if fee_asset == "BTC":
            fee_usd = fee_amount_raw * price  # Use trade price for BTC
        elif fee_asset in ["USDC", "USDT", "USD"]:
            fee_usd = fee_amount_raw
        # For other assets (BNB, etc.), we'd need price data - skip for now
        
        unified_list.append(UnifiedTransaction(
            id=trade_id,
            timestamp=ts,
            type="MANUAL",
            status="SUCCESS",
            btc_amount=qty,
            fiat_amount=total_usd,
            price=price,
            notes=None,  # No notes needed, badge is sufficient
            source="MANUAL",
            ahr999=None,
            fee_amount=fee_usd,  # Fee in USD
            fee_asset="USD"  # Always report as USD
        ))
    
    # Sort by timestamp descending (all timestamps are now timezone-aware)
    unified_list.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Log fee asset summary for debugging
    manual_trades = [tx for tx in unified_list if tx.source == "MANUAL"]
    if manual_trades:
        fee_assets = {}
        for tx in manual_trades:
            # Get original fee asset from Binance trade data
            matching_trade = next((t for t in binance_trades if t.get("orderId") == tx.id), None)
            if matching_trade:
                asset = matching_trade.get("commissionAsset", "Unknown")
                fee_assets[asset] = fee_assets.get(asset, 0) + 1
        
        logger.info(f"Manual trades fee assets: {fee_assets}")
    
    # Apply offset and limit
    return unified_list[offset:offset + limit]

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
