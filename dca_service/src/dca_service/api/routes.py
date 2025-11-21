from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from dca_service.database import get_session
from dca_service.models import DCATransaction
from dca_service.api.schemas import TransactionRead, SimulationRequest

router = APIRouter()

@router.get("/transactions", response_model=List[TransactionRead])
def read_transactions(
    offset: int = 0,
    limit: int = Query(default=100, le=100),
    session: Session = Depends(get_session)
):
    transactions = session.exec(select(DCATransaction).offset(offset).limit(limit).order_by(DCATransaction.timestamp.desc())).all()
    return transactions

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
        notes=request.notes or "Simulated transaction"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    return transaction
