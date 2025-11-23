from datetime import datetime, timezone
from typing import Optional, Dict
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.metrics_provider import get_latest_metrics
from whenshouldubuybitcoin.strategies.dynamic_ahr999 import (
    calculate_buy_amount,
    DynamicAhr999Params,
    DynamicAhr999Config,
)


class DCADecision(BaseModel):
    can_execute: bool
    reason: str
    ahr999_value: float
    ahr_band: str  # "low", "mid", "high"
    multiplier: float
    base_amount_usd: float
    suggested_amount_usd: float
    price_usd: float
    timestamp: datetime
    metrics_source: Dict[str, str]  # {"backend": "csv"|"realtime", "label": "..."}
    remaining_budget: Optional[float] = None
    budget_resets: bool = False  # Whether budget resets monthly
    time_until_reset: Optional[str] = (
        None  # Human-readable time until reset (e.g., "5 days")
    )


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
        "time_until_reset": None,
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
    # peak180 might be missing if using old metrics provider mock in tests
    peak180 = metrics.get("peak180", price)
    source_backend = metrics.get("source", "unknown")
    source_label = metrics.get("source_label", "Unknown")

    # 2. Determine Band & Multiplier
    if strategy.strategy_type == "dynamic_ahr999":
        # Dynamic Strategy Logic

        # Construct Config from Strategy Model
        # Use defaults if fields are None
        config = DynamicAhr999Config(
            base_amount=strategy.total_budget_usd
            / 30.0,  # Default base amount, will be overridden if we want
            max_multiplier=(
                strategy.dynamic_max_multiplier
                if strategy.dynamic_max_multiplier is not None
                else 10.0
            ),
            min_multiplier=(
                strategy.dynamic_min_multiplier
                if strategy.dynamic_min_multiplier is not None
                else 0.0
            ),
            gamma=strategy.dynamic_gamma if strategy.dynamic_gamma is not None else 2.0,
            a_low=(
                strategy.dynamic_a_low if strategy.dynamic_a_low is not None else 0.45
            ),
            a_high=(
                strategy.dynamic_a_high if strategy.dynamic_a_high is not None else 1.0
            ),
            enable_drawdown_boost=(
                strategy.dynamic_enable_drawdown_boost
                if strategy.dynamic_enable_drawdown_boost is not None
                else True
            ),
            # Use unified budget enforcement: monthly_cap comes from total_budget_usd if enforce_monthly_cap is True
            enable_monthly_cap=strategy.enforce_monthly_cap,
            monthly_cap=strategy.total_budget_usd,  # Use total_budget_usd as monthly cap
        )

        # For base_amount, we need to respect the execution frequency logic
        # But the dynamic strategy takes base_amount in config.
        # Let's calculate it first based on budget/frequency
        if strategy.execution_frequency == "daily":
            base_amount_calc = strategy.total_budget_usd / 30.0
        elif strategy.execution_frequency == "weekly":
            base_amount_calc = strategy.total_budget_usd / 4.0
        else:
            base_amount_calc = strategy.total_budget_usd / 30.0

        config.base_amount = base_amount_calc

        # Calculate month spent for cap
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_spent_txs = session.exec(
            select(DCATransaction.fiat_amount).where(
                DCATransaction.status == "SUCCESS",
                DCATransaction.timestamp >= month_start,
            )
        ).all()
        month_spent = sum(month_spent_txs) if month_spent_txs else 0.0

        # Call Strategy Module
        params = DynamicAhr999Params(
            ahr999=ahr999,
            price=price,
            peak180=peak180,
            month_spent=month_spent,
            config=config,
        )

        result = calculate_buy_amount(params)

        # Map result to local variables
        multiplier = (
            result.multiplier
        )  # Final multiplier (includes boost, may be clipped)
        base_multiplier = result.base_multiplier  # Base multiplier (before boost)
        multiplier_before_clip = (
            result.multiplier_before_clip
        )  # Multiplier before max_multiplier clipping
        suggested_amount = result.buy
        base_amount = base_amount_calc
        band = "DYNAMIC"  # Placeholder for dynamic strategy

        # Calculate expected uncapped amount (before monthly cap)
        uncapped_amount = base_amount * multiplier

        if result.capped and suggested_amount == 0:
            reason = "Monthly Cap Exceeded"
        else:
            # Build a clear, step-by-step formula showing the complete calculation chain
            # Use newlines for better readability in UI
            lines = []

            # Step 1: Show inputs
            lines.append(
                f"AHR999 = {ahr999:.4f} (thresholds: a_low={config.a_low:.2f}, a_high={config.a_high:.2f})"
            )

            # Step 2: Calculate cheapness
            cheapness_calc = f"Cheapness = ({config.a_high:.2f} - {ahr999:.4f}) / ({config.a_high:.2f} - {config.a_low:.2f}) = {result.cheapness:.4f}"
            lines.append(cheapness_calc)

            # Step 3: Calculate base multiplier
            mult_base_calc = f"Mult_base = {config.min_multiplier:.1f} + ({config.max_multiplier:.1f} - {config.min_multiplier:.1f}) × ({result.cheapness:.4f} ^ {config.gamma:.1f}) = {base_multiplier:.2f}x"
            lines.append(mult_base_calc)

            # Step 4: Drawdown and boost (if enabled)
            if config.enable_drawdown_boost:
                drawdown_pct = result.drawdown * 100
                lines.append(
                    f"Drawdown = {drawdown_pct:.1f}% → Boost = {result.drawdown_factor:.2f}x"
                )

                # Step 5: Calculate final multiplier (clear formula)
                if result.multiplier_clipped:
                    mult_final_calc = f"Mult_final = {base_multiplier:.2f}x × {result.drawdown_factor:.2f}x = {multiplier_before_clip:.2f}x [CLIPPED to {multiplier:.2f}x]"
                else:
                    mult_final_calc = f"Mult_final = {base_multiplier:.2f}x × {result.drawdown_factor:.2f}x = {multiplier:.2f}x"
                lines.append(mult_final_calc)
            else:
                lines.append(
                    f"Mult_final = Mult_base = {multiplier:.2f}x (boost disabled)"
                )

            # Step 6: Calculate buy amount (clear formula)
            if result.capped or abs(suggested_amount - uncapped_amount) > 0.01:
                buy_calc = f"Buy = ${base_amount:.2f} × {multiplier:.2f}x = ${uncapped_amount:.2f} [CAPPED to ${suggested_amount:.2f}]"
                lines.append(buy_calc)

                # Add monthly cap details if capped
                if config.enable_monthly_cap:
                    remaining_budget = config.monthly_cap - month_spent
                    lines.append(
                        f"Monthly Cap: ${month_spent:.2f} spent / ${config.monthly_cap:.2f} limit, remaining: ${remaining_budget:.2f}"
                    )
            else:
                buy_calc = f"Buy = ${base_amount:.2f} × {multiplier:.2f}x = ${suggested_amount:.2f}"
                lines.append(buy_calc)

                # Show monthly cap status even if not capped
                if config.enable_monthly_cap:
                    remaining_budget = config.monthly_cap - month_spent
                    lines.append(
                        f"Monthly Cap: ${month_spent:.2f} spent / ${config.monthly_cap:.2f} limit, remaining: ${remaining_budget:.2f}"
                    )

            # Join with separator (UI will convert to newlines)
            reason = " | ".join(lines)

        # Determine band for UI (approximate)
        if ahr999 < config.a_low:
            band = "low"
        elif ahr999 > config.a_high:
            band = "high"
        else:
            band = "mid"

        # If capped by monthly cap in strategy, we should respect that
        # The strategy module already capped 'buy', so suggested_amount is correct.

    else:
        # Legacy Band Strategy Logic
        if ahr999 < 0.45:
            band = "low"
            multiplier = strategy.ahr999_multiplier_low
        elif ahr999 <= 1.2:
            band = "mid"
            multiplier = strategy.ahr999_multiplier_mid
        else:
            band = "high"
            multiplier = strategy.ahr999_multiplier_high

        # Base amount calculation for legacy is done below, but we need it here for structure consistency
        # We'll let the legacy flow continue, but we need to handle the divergence
        reason = "Conditions met"

    # 3. Determine budget reset logic (needed for base amount calculation)
    now = datetime.now(timezone.utc)
    budget_resets = (
        strategy.enforce_monthly_cap
    )  # Budget resets monthly if enforcement is enabled

    # 4. Calculate base amount based on budget and execution frequency
    # Only needed if not already calculated by dynamic strategy
    if strategy.strategy_type != "dynamic_ahr999":
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
                DCATransaction.timestamp >= month_start,
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
            next_month_start = now.replace(
                year=now.year + 1,
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            next_month_start = now.replace(
                month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
            )

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
        decision_data.update(
            {
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
                "time_until_reset": time_until_reset,
            }
        )
        return DCADecision(**decision_data)

    # Append calculation details to reason if it's just "Conditions met"
    if reason == "Conditions met":
        reason = f"Conditions met (Base ${base_amount:.2f} × Mult {multiplier:.2f}x)"

    # Check Budget
    if total_spent_sum + suggested_amount > strategy.total_budget_usd:
        if strategy.enforce_monthly_cap:
            reset_info = " (resets monthly)" if budget_resets else ""
            decision_data = base_decision.copy()
            decision_data.update(
                {
                    "can_execute": False,
                    "reason": f"Over budget. Spent: ${total_spent_sum:.2f}, Budget: ${strategy.total_budget_usd:.2f}{reset_info}",
                    "ahr999_value": ahr999,
                    "ahr_band": band,
                    "multiplier": multiplier,
                    "base_amount_usd": base_amount,
                    "suggested_amount_usd": suggested_amount,
                    "price_usd": price,
                    "metrics_source": {
                        "backend": source_backend,
                        "label": source_label,
                    },
                    "remaining_budget": remaining_budget,
                    "budget_resets": budget_resets,
                    "time_until_reset": time_until_reset,
                }
            )
            return DCADecision(**decision_data)

    return DCADecision(
        can_execute=True,
        reason=reason,
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
        time_until_reset=time_until_reset,
    )
