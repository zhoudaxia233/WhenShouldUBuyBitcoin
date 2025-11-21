from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime

from dca_service.database import get_session
from dca_service.models import DCAStrategy
from dca_service.api.schemas_strategy import StrategyCreate, StrategyRead, StrategyUpdate

router = APIRouter()

@router.get("/strategy", response_model=Optional[StrategyRead])
def get_strategy(session: Session = Depends(get_session)):
    # Singleton pattern: get the first strategy
    strategy = session.exec(select(DCAStrategy)).first()
    return strategy

@router.post("/strategy", response_model=StrategyRead)
def create_strategy(strategy_in: StrategyCreate, session: Session = Depends(get_session)):
    # Ensure only one strategy exists
    existing = session.exec(select(DCAStrategy)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Strategy already exists. Use PUT to update.")
    
    strategy = DCAStrategy.model_validate(strategy_in)
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy

@router.put("/strategy", response_model=StrategyRead)
def update_strategy(strategy_in: StrategyUpdate, session: Session = Depends(get_session)):
    strategy = session.exec(select(DCAStrategy)).first()
    if not strategy:
        # Auto-create if not exists (convenience)
        strategy = DCAStrategy.model_validate(strategy_in)
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
        return strategy
    
    # Update fields
    strategy_data = strategy_in.model_dump(exclude_unset=True)
    for key, value in strategy_data.items():
        setattr(strategy, key, value)
    
    strategy.updated_at = datetime.utcnow()
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy

@router.delete("/strategy")
def delete_strategy(session: Session = Depends(get_session)):
    strategy = session.exec(select(DCAStrategy)).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    session.delete(strategy)
    session.commit()
    return {"ok": True}
