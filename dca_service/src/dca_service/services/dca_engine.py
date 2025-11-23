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
    remaining_budget: Optional[float] = None
    budget_resets: bool = False  # Whether budget resets monthly
    time_until_reset: Optional[str] = None  # Human-readable time until reset (e.g., "5 days")

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
        "metrics_source": {"backend": "unknown", "label": "Unknown"},
        "remaining_budget": None,
        "budget_resets": False,
        "time_until_reset": None
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

    # 3. Determine budget reset logic (needed for base amount calculation)
    now = datetime.now(timezone.utc)
    budget_resets = not strategy.allow_over_budget
    
    # 4. Calculate base amount based on budget and execution frequency
    # Base amount is the portion of the monthly budget allocated per execution period
    # This applies regardless of whether budget resets monthly or not
    if strategy.execution_frequency == "daily":
        # Approximate 30 days per month
        base_amount = strategy.total_budget_usd / 30.0
    elif strategy.execution_frequency == "weekly":
        # Approximately 4 weeks per month
        base_amount = strategy.total_budget_usd / 4.0
    else:
        # Fallback to daily if frequency is unknown
        base_amount = strategy.total_budget_usd / 30.0
    
    suggested_amount = base_amount * multiplier

    # 5. Calculate budget spent (with monthly reset logic)
    
    if budget_resets:
        # Calculate start of current month in UTC
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Only count transactions from current month
        total_spent = session.exec(
            select(DCATransaction.fiat_amount).where(
                DCATransaction.status == "SUCCESS",
                DCATransaction.timestamp >= month_start
            )
        ).all()
    else:
        # Count all transactions (no reset)
        total_spent = session.exec(
            select(DCATransaction.fiat_amount).where(DCATransaction.status == "SUCCESS")
        ).all()
    
    # Calculate total spent (handle empty list)
    total_spent_sum = sum(total_spent) if total_spent else 0.0
    remaining_budget = max(0.0, strategy.total_budget_usd - total_spent_sum)
    
    # Calculate time until reset (if applicable)
    time_until_reset = None
    if budget_resets:
        # Calculate next month start
        if now.month == 12:
            next_month_start = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month_start = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        time_diff = next_month_start - now
        days = time_diff.days
        hours = time_diff.seconds // 3600
        
        if days > 0:
            time_until_reset = f"{days} day{'s' if days != 1 else ''}"
        elif hours > 0:
            time_until_reset = f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            time_until_reset = "Less than an hour"

    # 5. Check Constraints
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
            "metrics_source": {"backend": source_backend, "label": source_label},
            "remaining_budget": remaining_budget,
            "budget_resets": budget_resets,
            "time_until_reset": time_until_reset
        })
        return DCADecision(**decision_data)

    # Check Budget
    if total_spent_sum + suggested_amount > strategy.total_budget_usd:
        if not strategy.allow_over_budget:
            reset_info = " (resets monthly)" if budget_resets else ""
            decision_data = base_decision.copy()
            decision_data.update({
                "can_execute": False,
                "reason": f"Over budget. Spent: ${total_spent_sum:.2f}, Budget: ${strategy.total_budget_usd:.2f}{reset_info}",
                "ahr999_value": ahr999,
                "ahr_band": band,
                "multiplier": multiplier,
                "base_amount_usd": base_amount,
                "suggested_amount_usd": suggested_amount,
                "price_usd": price,
                "metrics_source": {"backend": source_backend, "label": source_label},
                "remaining_budget": remaining_budget,
                "budget_resets": budget_resets,
                "time_until_reset": time_until_reset
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
        metrics_source={"backend": source_backend, "label": source_label},
        remaining_budget=remaining_budget,
        budget_resets=budget_resets,
        time_until_reset=time_until_reset
    )
