from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from dca_service.database import get_session
from dca_service.services.dca_engine import calculate_dca_decision, DCADecision
from dca_service.models import DCATransaction
from dca_service.api.schemas import TransactionRead

router = APIRouter()

@router.get("/dca/preview", response_model=DCADecision)
def preview_dca(session: Session = Depends(get_session)):
    """
    Preview the DCA decision based on current strategy and metrics.
    Does NOT execute any transaction.
    """
    decision = calculate_dca_decision(session)
    return decision

@router.post("/dca/execute-simulated", response_model=dict)
def execute_simulated_dca(session: Session = Depends(get_session)):
    """
    Execute a simulated DCA transaction if conditions are met.
    Returns the decision and the created transaction (if any).
    """
    decision = calculate_dca_decision(session)
    
    if not decision.can_execute:
        return {
            "decision": decision,
            "transaction": None,
            "message": f"DCA skipped: {decision.reason}"
        }
    
    # Create simulated transaction
    btc_amount = decision.suggested_amount_usd / decision.price_usd if decision.price_usd > 0 else 0
    
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=decision.suggested_amount_usd,
        btc_amount=btc_amount,
        price=decision.price_usd,
        ahr999=decision.ahr999_value,
        notes="SIMULATED"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    return {
        "decision": decision,
        "transaction": transaction,
        "message": "Simulated DCA executed successfully"
    }
