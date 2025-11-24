from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import ColdWalletEntry
from dca_service.api.schemas import ColdWalletEntryCreate, ColdWalletEntryRead
from dca_service.core.logging import logger

router = APIRouter(prefix="/cold_wallet", tags=["cold_wallet"])

@router.post("", response_model=ColdWalletEntryRead)
def create_cold_wallet_entry(
    entry: ColdWalletEntryCreate,
    session: Session = Depends(get_session)
):
    # Validation
    if entry.btc_amount == 0:
        raise HTTPException(status_code=400, detail="BTC amount cannot be zero")
    
    # Calculate previous total for logging
    previous_total = session.exec(select(func.sum(ColdWalletEntry.btc_amount))).one() or 0.0
    
    # Create model
    db_entry = ColdWalletEntry(
        timestamp=entry.timestamp,
        btc_amount=entry.btc_amount,
        fee_btc=entry.fee_btc,
        notes=entry.notes
    )
    
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    
    new_total = previous_total + entry.btc_amount
    logger.info(
        f"Manual Cold Wallet Entry: {entry.btc_amount} BTC "
        f"(Total: {previous_total:.8f} -> {new_total:.8f} BTC) - {entry.notes}"
    )
    
    return db_entry
