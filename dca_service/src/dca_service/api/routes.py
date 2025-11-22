from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from dca_service.database import get_session
from dca_service.models import DCATransaction, ManualTransaction
from dca_service.api.schemas import TransactionRead, SimulationRequest, UnifiedTransaction

router = APIRouter()

@router.get("/transactions", response_model=List[UnifiedTransaction])
def read_transactions(
    offset: int = 0,
    limit: int = Query(default=100, le=100),
    session: Session = Depends(get_session)
):
    # Fetch DCA transactions
    dca_txs = session.exec(select(DCATransaction)).all()
    
    # Fetch Manual transactions
    manual_txs = session.exec(select(ManualTransaction)).all()
    
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
            type=tx.type,
            status="COMPLETED",
            btc_amount=tx.btc_amount,
            fiat_amount=tx.fiat_amount,
            price=tx.price_usd,
            notes=tx.notes,
            source="MANUAL",
            fee_usdc=tx.fee_usdc
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
