from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import ManualTransaction
from dca_service.api.schemas import ManualTransactionCreate, ManualTransactionRead

router = APIRouter(prefix="/manual_transaction", tags=["manual"])

@router.post("", response_model=ManualTransactionRead)
def create_manual_transaction(
    tx: ManualTransactionCreate,
    session: Session = Depends(get_session)
):
    # Validation
    if tx.btc_amount == 0:
        raise HTTPException(status_code=400, detail="BTC amount cannot be zero")
    
    if tx.type == "BUY" and (tx.fiat_amount is None or tx.fiat_amount <= 0):
        raise HTTPException(status_code=400, detail="Fiat amount required for BUY")
        
    # Enforce Price and Fiat for all types as per user request
    if tx.price_usd is None or tx.price_usd <= 0:
        raise HTTPException(status_code=400, detail="Price (USD) is required")
        
    if tx.fiat_amount is None or tx.fiat_amount <= 0:
        # Note: For TRANSFER, fiat_amount might represent value at time of transfer
        raise HTTPException(status_code=400, detail="Fiat Amount (USD) is required")

    # Create model
    db_tx = ManualTransaction(
        timestamp=tx.timestamp or datetime.now(timezone.utc),
        type=tx.type,
        btc_amount=tx.btc_amount,
        fiat_amount=tx.fiat_amount,
        price_usd=tx.price_usd,
        fee_usdc=tx.fee_usdc,
        notes=tx.notes
    )
    
    session.add(db_tx)
    session.commit()
    session.refresh(db_tx)
    
    return db_tx
