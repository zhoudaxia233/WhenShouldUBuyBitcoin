from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from datetime import datetime, timezone

from dca_service.database import get_session
from dca_service.models import ColdWalletEntry
from dca_service.api.schemas import ColdWalletEntryCreate, ColdWalletEntryRead

router = APIRouter(prefix="/cold_wallet", tags=["cold_wallet"])

@router.post("", response_model=ColdWalletEntryRead)
def create_cold_wallet_entry(
    entry: ColdWalletEntryCreate,
    session: Session = Depends(get_session)
):
    # Validation
    if entry.btc_amount == 0:
        raise HTTPException(status_code=400, detail="BTC amount cannot be zero")
    
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
    
    return db_entry
