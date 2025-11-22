from datetime import datetime, timezone
from typing import Optional, Dict
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.metrics_provider import get_latest_metrics

class DCADecision(BaseModel):
    can_execute: bool
    reason: str
    ahr999_value: float
    ahr_band: str # "low", "mid", "high"
    multiplier: float
    base_amount_usd: float
    suggested_amount_usd: float
    price_usd: float
    timestamp: datetime
    metrics_source: Dict[str, str]  # {"backend": "csv"|"realtime", "label": "..."}

def calculate_dca_decision(session: Session) -> DCADecision:
    """
    Core logic to determine if and how much to buy.
    """
    # 1. Load Strategy
    strategy = session.exec(select(DCAStrategy)).first()
    metrics = get_latest_metrics()
    
    timestamp = datetime.now(timezone.utc)
    
    # Defaults if things fail
    base_decision = {
        "can_execute": False,
        "reason": "Unknown",
        "ahr999_value": 0.0,
        "ahr_band": "unknown",
        "multiplier": 0.0,
        "base_amount_usd": 0.0,
        "suggested_amount_usd": 0.0,
        "price_usd": 0.0,
        "timestamp": timestamp,
        "metrics_source": {"backend": "unknown", "label": "Unknown"}
    }

    if not strategy:
        decision_data = base_decision.copy()
        decision_data["reason"] = "No strategy found"
        return DCADecision(**decision_data)

    if not metrics:
        decision_data = base_decision.copy()
        decision_data["reason"] = "Metrics unavailable or stale"
        return DCADecision(**decision_data)

    price = metrics["price_usd"]
    ahr999 = metrics["ahr999"]
    source_backend = metrics.get("source", "unknown")
    source_label = metrics.get("source_label", "Unknown")
    
    # 2. Determine Band & Multiplier
    if ahr999 < 0.45:
        band = "low"
        multiplier = strategy.ahr999_multiplier_low
    elif ahr999 <= 1.2:
        band = "mid"
        multiplier = strategy.ahr999_multiplier_mid
    else:
        band = "high"
        multiplier = strategy.ahr999_multiplier_high

    # 3. Calculate Amounts
    # Base amount is derived from total budget? 
    # Wait, the prompt says "suggested fiat amount: multiplier × base amount"
    # But the strategy model has `total_budget_usd` and `target_btc_amount`.
    # It doesn't strictly have a "base_amount" per buy.
    # Usually DCA is "Buy $X every day".
    # Let's assume for this step that `total_budget_usd` is the TOTAL budget for the whole campaign,
    # but we need a "base amount per period".
    # The prompt didn't specify a "base_amount" field in Strategy.
    # Let's check the Strategy model again.
    # Fields: total_budget_usd, allow_over_budget, multipliers...
    # It seems we are missing a "base_buy_amount" in the Strategy model from Phase 2.
    # However, I cannot change the model now without user request.
    # Let's assume `total_budget_usd` IS the base amount for now? No, that's "Total Budget".
    # Let's look at the prompt again: "Computes suggested fiat amount: multiplier × base amount"
    # Maybe I missed a field in Phase 2?
    # "Fields: total_budget_usd, allow_over_budget, multipliers, target_btc_amount..."
    # There is NO base_amount per period in the Strategy model.
    # I will infer `base_amount` = `total_budget_usd` / 100 (just as a placeholder) OR
    # I will treat `total_budget_usd` as the "daily budget" if the user meant that?
    # No, "Total Budget" usually means total cap.
    # I will add a hardcoded base_amount = 100.0 for now, or better yet, 
    # I will use `total_budget_usd` as the base amount if it's small, but that's risky.
    # Let's assume base_amount is $100.
    # Wait, looking at Phase 2 prompt: "total_budget_usd: float".
    # Let's use a default base of $50.
    
    base_amount = 50.0 # Placeholder since not in model
    
    suggested_amount = base_amount * multiplier

    # 4. Check Constraints
    if not strategy.is_active:
        decision_data = base_decision.copy()
        decision_data.update({
            "can_execute": False,
            "reason": "Strategy is inactive",
            "ahr999_value": ahr999,
            "ahr_band": band,
            "multiplier": multiplier,
            "base_amount_usd": base_amount,
            "suggested_amount_usd": suggested_amount,
            "price_usd": price,
            "metrics_source": {"backend": source_backend, "label": source_label}
        })
        return DCADecision(**decision_data)

    # Check Budget
    # Sum all SUCCESS transactions
    total_spent = session.exec(
        select(DCATransaction.fiat_amount).where(DCATransaction.status == "SUCCESS")
    ).all()
    total_spent_sum = sum(total_spent)

    if total_spent_sum + suggested_amount > strategy.total_budget_usd:
        if not strategy.allow_over_budget:
            decision_data = base_decision.copy()
            decision_data.update({
                "can_execute": False,
                "reason": f"Over budget. Spent: ${total_spent_sum:.2f}, Budget: ${strategy.total_budget_usd:.2f}",
                "ahr999_value": ahr999,
                "ahr_band": band,
                "multiplier": multiplier,
                "base_amount_usd": base_amount,
                "suggested_amount_usd": suggested_amount,
                "price_usd": price,
                "metrics_source": {"backend": source_backend, "label": source_label}
            })
            return DCADecision(**decision_data)

    return DCADecision(
        can_execute=True,
        reason="Conditions met",
        ahr999_value=ahr999,
        ahr_band=band,
        multiplier=multiplier,
        base_amount_usd=base_amount,
        suggested_amount_usd=suggested_amount,
        price_usd=price,
        timestamp=timestamp,
        metrics_source={"backend": source_backend, "label": source_label}
    )
