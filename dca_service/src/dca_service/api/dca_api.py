from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
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
    Returns metrics_source to show where data comes from.
    """
    decision = calculate_dca_decision(session)
    return decision

@router.post("/dca/execute-simulated", response_model=dict)
def execute_simulated_dca(
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session)
):
    """
    Execute a simulated DCA transaction if conditions are met.
    Returns both the decision and the created transaction (if any).
    
    Phase 6: Now populates intent vs. execution fields for future Binance integration.
    Phase 10: Sends email notification after successful execution.
    """
    decision = calculate_dca_decision(session)
    
    if not decision.can_execute:
        return {
            "decision": decision,
            "transaction": None,
            "message": f"DCA skipped: {decision.reason}"
        }
    
    # Calculate BTC amount
    btc_amount = decision.suggested_amount_usd / decision.price_usd if decision.price_usd > 0 else 0
    
    # Create simulated transaction
    transaction = DCATransaction(
        status="SUCCESS",
        # Legacy fields (backwards compatibility)
        fiat_amount=decision.suggested_amount_usd,
        btc_amount=btc_amount,
        price=decision.price_usd,
        ahr999=decision.ahr999_value,
        notes="Manual DCA simulation",
        # New Phase 6 fields: Intent vs. Execution
        intended_amount_usd=decision.suggested_amount_usd,
        executed_amount_usd=decision.suggested_amount_usd,  # For now, same as intended
        executed_amount_btc=btc_amount,
        avg_execution_price_usd=decision.price_usd,
        fee_amount=0.0,  # No fees in simulation
        fee_asset="USDC",
        source="SIMULATED"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    # Schedule email notification in background (non-blocking)
    background_tasks.add_task(
        _send_dca_email,
        transaction=transaction,
        decision=decision
    )
    
    return {
        "decision": decision,
        "transaction": transaction,
        "message": "Simulated DCA executed successfully"
    }


def _send_dca_email(transaction: DCATransaction, decision: any):
    """
    Send email notification for DCA execution.
    
    This runs in the background and does not block the HTTP response.
    """
    from dca_service.services.mailer import send_email
    from datetime import datetime, timezone
    
    # Build email subject
    subject = f"DCA Simulation Executed: ${transaction.fiat_amount:.2f} USDC for BTC"
    
    # Build email body
    exec_time = transaction.timestamp.strftime("%Y-%m-% d %H:%M:%S UTC")
    
    body = f"""DCA Simulation Executed Successfully

Execution Time: {exec_time}
AHR999 Value: {transaction.ahr999:.4f}
Decision Band: {decision.band if hasattr(decision, 'band') else 'N/A'}

Amount (USDC): ${transaction.fiat_amount:.2f}
Amount (BTC): {transaction.btc_amount:.8f}
Price (USD/BTC): ${transaction.price:.2f}

Transaction Details:
- Transaction ID: {transaction.id}
- Source: {transaction.source}
- Status: {transaction.status}

Notes: {transaction.notes or 'None'}

---
This is an automated notification from your DCA Service.
"""
    
    # Send email (failures are logged, not raised)
    send_email(subject, body)
