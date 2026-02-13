from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel
from sqlmodel import Session, select

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.metrics_provider import (
    get_latest_metrics,
    calculate_ahr999_percentile_thresholds,
    get_drawdown_percentile_snapshot,
    get_drawdown_context,
)
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
    peak_price_usd: Optional[float] = None
    drawdown_ratio: Optional[float] = None
    drawdown_percentile: Optional[float] = None
    drawdown_hist_date: Optional[str] = None
    drawdown_hist_peak_price_usd: Optional[float] = None
    drawdown_hist_price_usd: Optional[float] = None
    drawdown_context: Optional[Dict[str, Any]] = None


def _check_monthly_inflow(session: Session, strategy: DCAStrategy, now: datetime, month_spent: float):
    """
    Check if we need to add a new monthly budget inflow to savings.
    If last_monthly_inflow is None, initialize with current month's remaining budget.
    
    Budget behavior depends on enforce_monthly_cap flag:
    - Enforced (enforce_monthly_cap=True): Budget resets monthly (unspent funds are lost)
    - Not Enforced (enforce_monthly_cap=False): Budget accumulates monthly (unspent funds carry over)
    """
    # Initialize if needed
    if strategy.last_monthly_inflow is None:
        # First run of new logic.
        # Initialize savings with the REMAINDER of this month's budget.
        # Logic: savings = (TotalBudget - SpentThisMonth).
        strategy.accumulated_savings = max(0.0, strategy.total_budget_usd - month_spent)
        strategy.last_monthly_inflow = now
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
        return

    # Check for new month
    last_inflow = strategy.last_monthly_inflow.replace(tzinfo=timezone.utc) if strategy.last_monthly_inflow.tzinfo is None else strategy.last_monthly_inflow
    
    # Calculate months passed
    # Simple check: (now.year - last.year) * 12 + now.month - last_inflow.month
    months_diff = (now.year - last_inflow.year) * 12 + (now.month - last_inflow.month)

    if months_diff > 0:
        # Budget update depends on mode
        if not strategy.enforce_monthly_cap:
            # No Cap Mode: Accumulate budget for each month passed
            # User's unspent funds carry over to future months
            inflow_amount = months_diff * strategy.total_budget_usd
            strategy.accumulated_savings += inflow_amount
        else:
            # Enforced Cap Mode: Reset to current month's budget
            # Unspent budget from previous months is lost (resets monthly)
            # This matches the frontend backtest behavior where cashBalance is reset
            strategy.accumulated_savings = strategy.total_budget_usd
        
        strategy.last_monthly_inflow = now
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
    elif months_diff == 0 and strategy.enforce_monthly_cap:
        # Same month, but in Enforced Cap Mode: Check if budget was increased mid-month
        # Only adjust upward (when user increases budget), not downward (to preserve manual adjustments)
        expected_savings = max(0.0, strategy.total_budget_usd - month_spent)
        
        # Detect if this looks like a budget increase scenario:
        # Calculate what the old budget might have been
        implied_old_budget = strategy.accumulated_savings + month_spent
        budget_diff = strategy.total_budget_usd - implied_old_budget
        
        # Only adjust if:
        # 1. Expected savings is higher than current
        # 2. The difference looks like a deliberate budget increase (multiples of 50 or 100)
        # 3. The old implied budget was a reasonable value (at least 100)
        is_budget_increase = (
            expected_savings > strategy.accumulated_savings + 0.01 and
            implied_old_budget >= 100.0 and  # Old budget was reasonable
            budget_diff >= 50.0 and  # Increase is at least $50
            abs(budget_diff % 50) < 5.0  # Increase is close to a multiple of $50
        )
        
        if is_budget_increase:
            # Budget was increased mid-month, adjust accumulated_savings upward
            # This ensures budget increases take effect immediately
            strategy.accumulated_savings = expected_savings
            session.add(strategy)
            session.commit()
            session.refresh(strategy)


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
        "peak_price_usd": None,
        "drawdown_ratio": None,
        "drawdown_percentile": None,
        "drawdown_hist_date": None,
        "drawdown_hist_peak_price_usd": None,
        "drawdown_hist_price_usd": None,
        "drawdown_context": None,
    }

    if not strategy:
        decision_data = base_decision.copy()
        decision_data["reason"] = "No strategy found"
        return DCADecision(**decision_data)

    # 0. Check monthly inflow (accumulate savings)
    # Passed month_spent is not needed here as we query inside helper if needed?
    # Actually helper needs month_spent to init?
    # Let's calculate month_spent early or pass 0/query inside?
    # The helper needs 'month_spent' ONLY for initialization logic.
    # We can query it cheaply.
    
    # Query current month spent for initialization logic
    now_utc = datetime.now(timezone.utc)
    month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_spent_init = session.exec(
        select(DCATransaction.fiat_amount).where(
            DCATransaction.status == "SUCCESS",
            DCATransaction.timestamp >= month_start,
            DCATransaction.is_manual == False
        )
    ).all()
    month_spent_val = sum(month_spent_init) if month_spent_init else 0.0
    
    _check_monthly_inflow(session, strategy, now_utc, month_spent_val)

    if not metrics:
        decision_data = base_decision.copy()
        decision_data["reason"] = "Metrics unavailable or stale"
        return DCADecision(**decision_data)

    price = metrics["price_usd"]
    ahr999 = metrics["ahr999"]
    # peak180 might be missing if using old metrics provider mock in tests
    peak180 = metrics.get("peak180", price)
    drawdown_ratio = (peak180 - price) / peak180 if peak180 > 0 else 0.0
    drawdown_snapshot = get_drawdown_percentile_snapshot(price, peak180)
    drawdown_context = get_drawdown_context(price)
    source_backend = metrics.get("source", "unknown")
    source_label = metrics.get("source_label", "Unknown")

    # Keep strategy math pinned to provider metrics (peak180 above).
    # UI display may use richer multi-window context.
    display_peak_price = peak180
    display_drawdown_ratio = drawdown_ratio
    display_drawdown_snapshot = drawdown_snapshot

    context_180d = drawdown_context.get("180d") if drawdown_context else None
    if context_180d:
        nearest_180 = context_180d.get("nearest_match") or {}
        display_drawdown_ratio = context_180d.get("current_drawdown_ratio", display_drawdown_ratio)
        display_peak_price = context_180d.get("current_peak", display_peak_price)
        display_drawdown_snapshot = {
            "drawdown_percentile": context_180d.get("percentile_rank"),
            "historical_date": nearest_180.get("date"),
            "historical_peak": nearest_180.get("peak"),
            "historical_price": nearest_180.get("price"),
        }

    # 2. Determine Band & Multiplier
    if strategy.strategy_type == "dynamic_ahr999":
        # Dynamic Strategy Logic

        # Construct Config from Strategy Model
        # Use defaults if fields are None
        # Use 30.44 days per month (same as backtest framework) for consistency
        config = DynamicAhr999Config(
            base_amount=strategy.total_budget_usd
            / 30.44,  # Default base amount, will be overridden if we want
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
        # Use 30.44 days per month (same as backtest framework) for consistency
        if strategy.execution_frequency == "daily":
            base_amount_calc = strategy.total_budget_usd / 30.44
        elif strategy.execution_frequency == "weekly":
            base_amount_calc = strategy.total_budget_usd / 4.0
        else:
            base_amount_calc = strategy.total_budget_usd / 30.44

        config.base_amount = base_amount_calc

        # Calculate month spent for cap
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_spent_txs = session.exec(
            select(DCATransaction.fiat_amount).where(
                DCATransaction.status == "SUCCESS",
                DCATransaction.timestamp >= month_start,
                DCATransaction.is_manual == False,  # Exclude manual trades
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

        # Logic moved to end of function to support all strategies
        
        # Calculate budget limit based on mode
        available_cash = strategy.accumulated_savings
        monthly_remaining = max(0.0, strategy.total_budget_usd - month_spent)
        
        if not strategy.enforce_monthly_cap:
            # No Cap Mode: Limit is only available cash (accumulated savings)
            budget_limit = available_cash
            tx_capped_reason = f"Capped by Savings (${available_cash:.2f})"
        else:
            # Enforced Cap Mode: Limit is min(Monthly Remaining, Available Cash)
            budget_limit = min(monthly_remaining, available_cash)
            if monthly_remaining < available_cash:
                tx_capped_reason = f"Capped by Monthly Limit (${monthly_remaining:.2f})"
            else:
                tx_capped_reason = f"Capped by Savings (${available_cash:.2f})"
        
        # Apply strict budget limit to suggested amount
        original_suggested = suggested_amount
        suggested_amount = min(suggested_amount, budget_limit)
        
        # Determine if capped
        is_capped = suggested_amount < original_suggested
        
        if is_capped and suggested_amount == 0:
            reason = f"Budget Exhausted ({tx_capped_reason})"
        else:
            # Build a clear, step-by-step formula showing the complete calculation chain
            # Use newlines for better readability in UI
            lines = []

            # Step 1: Show inputs
            lines.append(
                f"AHR999 = {ahr999:.4f} (thresholds: a_low={config.a_low:.2f}, a_high={config.a_high:.2f})"
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

    elif strategy.strategy_type == "ahr999_fixed_range":
        # AHR999 Fixed Range Strategy Logic (8-range system matching backtest)
        # Uses fixed AHR999 value thresholds instead of historical percentiles
        # This provides deterministic behavior regardless of historical data
        
        # Fixed AHR999 thresholds (absolute values, not percentiles)
        thresholds = {
            "r045": 0.45,
            "r050": 0.50,
            "r060": 0.60,
            "r070": 0.70,
            "r080": 0.80,
            "r090": 0.90,
            "r100": 1.00
        }
        
        # Default multipliers matching backtest strategy
        def get_fixed_multiplier(field_name, default):
            """Get multiplier from field or default"""
            if hasattr(strategy, field_name):
                value = getattr(strategy, field_name)
                if value is not None:
                    return value
            return default
        
        multiplier_r045 = get_fixed_multiplier('ahr999_multiplier_r045', 5.0)
        multiplier_r050 = get_fixed_multiplier('ahr999_multiplier_r050', 3.0)
        multiplier_r060 = get_fixed_multiplier('ahr999_multiplier_r060', 2.0)
        multiplier_r070 = get_fixed_multiplier('ahr999_multiplier_r070', 1.0)
        multiplier_r080 = get_fixed_multiplier('ahr999_multiplier_r080', 0.5)
        multiplier_r090 = get_fixed_multiplier('ahr999_multiplier_r090', 0.0)
        multiplier_r100 = get_fixed_multiplier('ahr999_multiplier_r100', 0.0)
        multiplier_r999 = get_fixed_multiplier('ahr999_multiplier_r999', 0.0)
        
        # Determine which fixed range the current AHR999 falls into
        if ahr999 < thresholds["r045"]:
            # 0 - 0.45: EXTREMELY CHEAP
            band = "r045"
            multiplier = multiplier_r045
            reason = f"AHR999 {ahr999:.4f} < 0.45 (EXTREMELY CHEAP) → {multiplier}x"
        elif ahr999 < thresholds["r050"]:
            # 0.45 - 0.5: Very Cheap
            band = "r050"
            multiplier = multiplier_r050
            reason = f"AHR999 {ahr999:.4f} between 0.45-0.5 (Very Cheap) → {multiplier}x"
        elif ahr999 < thresholds["r060"]:
            # 0.5 - 0.6: Cheap
            band = "r060"
            multiplier = multiplier_r060
            reason = f"AHR999 {ahr999:.4f} between 0.5-0.6 (Cheap) → {multiplier}x"
        elif ahr999 < thresholds["r070"]:
            # 0.6 - 0.7: Fair
            band = "r070"
            multiplier = multiplier_r070
            reason = f"AHR999 {ahr999:.4f} between 0.6-0.7 (Fair) → {multiplier}x"
        elif ahr999 < thresholds["r080"]:
            # 0.7 - 0.8: Getting Expensive
            band = "r080"
            multiplier = multiplier_r080
            reason = f"AHR999 {ahr999:.4f} between 0.7-0.8 (Getting Expensive) → {multiplier}x"
        elif ahr999 < thresholds["r090"]:
            # 0.8 - 0.9: Expensive
            band = "r090"
            multiplier = multiplier_r090
            reason = f"AHR999 {ahr999:.4f} between 0.8-0.9 (Expensive) → {multiplier}x"
        elif ahr999 < thresholds["r100"]:
            # 0.9 - 1.0: Very Expensive
            band = "r100"
            multiplier = multiplier_r100
            reason = f"AHR999 {ahr999:.4f} between 0.9-1.0 (Very Expensive) → {multiplier}x"
        else:
            # > 1.0: EXTREMELY EXPENSIVE
            band = "r999"
            multiplier = multiplier_r999
            reason = f"AHR999 {ahr999:.4f} >= 1.0 (EXTREMELY EXPENSIVE) → {multiplier}x"

    else:
        # AHR999 Percentile Strategy Logic (6-tier system matching backtest)
        # Use historical percentiles to determine which tier the current AHR999 falls into
        percentiles = calculate_ahr999_percentile_thresholds()
        
        # Default multipliers matching backtest strategy
        # Use new percentile fields if available, otherwise fall back to legacy fields or defaults
        def get_multiplier(new_field, legacy_field, default):
            """Get multiplier from new field, legacy field, or default"""
            if hasattr(strategy, new_field):
                value = getattr(strategy, new_field)
                if value is not None:
                    return value
            if legacy_field and hasattr(strategy, legacy_field):
                value = getattr(strategy, legacy_field)
                if value is not None:
                    return value
            return default
        
        multiplier_p10 = get_multiplier('ahr999_multiplier_p10', 'ahr999_multiplier_low', 5.0)
        multiplier_p25 = get_multiplier('ahr999_multiplier_p25', 'ahr999_multiplier_mid', 2.0)
        multiplier_p50 = get_multiplier('ahr999_multiplier_p50', None, 1.0)
        multiplier_p75 = get_multiplier('ahr999_multiplier_p75', None, 0.0)
        multiplier_p90 = get_multiplier('ahr999_multiplier_p90', None, 0.0)
        multiplier_p100 = get_multiplier('ahr999_multiplier_p100', 'ahr999_multiplier_high', 0.0)
        
        # Determine which percentile tier the current AHR999 falls into (6 tiers)
        if ahr999 < percentiles["p10"]:
            # Bottom 10% - EXTREMELY cheap
            band = "p10"
            multiplier = multiplier_p10
            reason = f"AHR999 {ahr999:.4f} < p10 ({percentiles['p10']:.4f}) - Bottom 10% (EXTREME CHEAP) → {multiplier}x"
        elif ahr999 < percentiles["p25"]:
            # 10-25% - Very cheap
            band = "p25"
            multiplier = multiplier_p25
            reason = f"AHR999 {ahr999:.4f} between p10 ({percentiles['p10']:.4f}) and p25 ({percentiles['p25']:.4f}) - 10-25% (Very Cheap) → {multiplier}x"
        elif ahr999 < percentiles["p50"]:
            # 25-50% - Cheap
            band = "p50"
            multiplier = multiplier_p50
            reason = f"AHR999 {ahr999:.4f} between p25 ({percentiles['p25']:.4f}) and p50 ({percentiles['p50']:.4f}) - 25-50% (Cheap) → {multiplier}x"
        elif ahr999 < percentiles["p75"]:
            # 50-75% - Fair
            band = "p75"
            multiplier = multiplier_p75
            reason = f"AHR999 {ahr999:.4f} between p50 ({percentiles['p50']:.4f}) and p75 ({percentiles['p75']:.4f}) - 50-75% (Fair) → {multiplier}x"
        elif ahr999 < percentiles["p90"]:
            # 75-90% - Expensive
            band = "p90"
            multiplier = multiplier_p90
            reason = f"AHR999 {ahr999:.4f} between p75 ({percentiles['p75']:.4f}) and p90 ({percentiles['p90']:.4f}) - 75-90% (Expensive) → {multiplier}x"
        else:
            # Top 10% - VERY expensive
            band = "p100"
            multiplier = multiplier_p100
            reason = f"AHR999 {ahr999:.4f} >= p90 ({percentiles['p90']:.4f}) - Top 10% (VERY EXPENSIVE) → {multiplier}x"

    # 3. Determine budget reset logic (needed for base amount calculation)
    now = datetime.now(timezone.utc)
    budget_resets = (
        strategy.enforce_monthly_cap
    )  # Budget resets monthly if enforcement is enabled

    # 4. Calculate base amount based on budget and execution frequency
    # Only needed if not already calculated by dynamic strategy
    # For ahr999_fixed_range, we need to calculate base_amount here
    if strategy.strategy_type not in ["dynamic_ahr999"]:
        if strategy.execution_frequency == "daily":
            # Use 30.44 days per month (same as backtest framework)
            base_amount = strategy.total_budget_usd / 30.44
        elif strategy.execution_frequency == "weekly":
            # Approximately 4 weeks per month
            base_amount = strategy.total_budget_usd / 4.0
        else:
            # Fallback to daily if frequency is unknown
            base_amount = strategy.total_budget_usd / 30.44

        # Calculate suggested amount based on multiplier
        # For ahr999_fixed_range, multiplier is already set above
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
                DCATransaction.is_manual == False,  # Exclude manual trades
            )
        ).all()
    else:
        # Count all transactions (no reset)
        total_spent = session.exec(
            select(DCATransaction.fiat_amount).where(
                DCATransaction.status == "SUCCESS",
                DCATransaction.is_manual == False,  # Exclude manual trades
            )
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
                "remaining_budget": remaining_budget if strategy.enforce_monthly_cap else None,
                "budget_resets": budget_resets,
                "time_until_reset": time_until_reset,
                "peak_price_usd": display_peak_price,
                "drawdown_ratio": display_drawdown_ratio,
                "drawdown_percentile": display_drawdown_snapshot["drawdown_percentile"] if display_drawdown_snapshot else None,
                "drawdown_hist_date": display_drawdown_snapshot["historical_date"] if display_drawdown_snapshot else None,
                "drawdown_hist_peak_price_usd": display_drawdown_snapshot["historical_peak"] if display_drawdown_snapshot else None,
                "drawdown_hist_price_usd": display_drawdown_snapshot["historical_price"] if display_drawdown_snapshot else None,
                "drawdown_context": drawdown_context,
            }
        )
        return DCADecision(**decision_data)

    # Append calculation details to reason if it's just "Conditions met"
    if reason == "Conditions met":
        reason = f"Conditions met (Base ${base_amount:.2f} × Mult {multiplier:.2f}x)"

    # --- GLOBAL BUDGET CHECK (All Strategies) ---
    available_cash = strategy.accumulated_savings
    monthly_remaining = max(0.0, strategy.total_budget_usd - total_spent_sum) # total_spent_sum calculated at Line 468
    
    budget_limit = 0.0
    tx_capped_reason = ""
    is_capped = False
    original_suggested = suggested_amount
    
    if not strategy.enforce_monthly_cap:
        # No Cap Mode: No budget limit applied to suggested amount
        # User wants to see the full strategy-calculated amount without restrictions
        # Execution will still require sufficient accumulated_savings, but preview shows uncapped amount
        budget_limit = float('inf')  # No limit
        tx_capped_reason = ""
        # Do not cap the suggested_amount in this mode
    else:
        # Enforced Cap Mode: Limit is min(Monthly Remaining, Available Cash)
        budget_limit = min(monthly_remaining, available_cash)
        if monthly_remaining < available_cash:
            tx_capped_reason = f"Capped by Monthly Limit (${monthly_remaining:.2f})"
        else:
            tx_capped_reason = f"Capped by Savings (${available_cash:.2f})"
        
        # Apply limit only in enforced cap mode
        suggested_amount = min(suggested_amount, budget_limit)
        is_capped = suggested_amount < original_suggested
    
    if is_capped:
        if suggested_amount == 0:
            decision_data = base_decision.copy()
            decision_data.update({
                "can_execute": False,
                "reason": f"Budget Exhausted ({tx_capped_reason}). Spent: ${total_spent_sum:.2f}",
                "ahr999_value": ahr999,
                "ahr_band": band,
                "multiplier": multiplier,
                "base_amount_usd": base_amount,
                "suggested_amount_usd": suggested_amount,
                "price_usd": price,
                "remaining_budget": remaining_budget if strategy.enforce_monthly_cap else None,
                "budget_resets": budget_resets,
                "time_until_reset": time_until_reset,
                "metrics_source": {"backend": source_backend, "label": source_label},
                "peak_price_usd": display_peak_price,
                "drawdown_ratio": display_drawdown_ratio,
                "drawdown_percentile": display_drawdown_snapshot["drawdown_percentile"] if display_drawdown_snapshot else None,
                "drawdown_hist_date": display_drawdown_snapshot["historical_date"] if display_drawdown_snapshot else None,
                "drawdown_hist_peak_price_usd": display_drawdown_snapshot["historical_peak"] if display_drawdown_snapshot else None,
                "drawdown_hist_price_usd": display_drawdown_snapshot["historical_price"] if display_drawdown_snapshot else None,
                "drawdown_context": drawdown_context,
            })
            return DCADecision(**decision_data)
        else:
             # Partial execution allowed (or capped amount)
             # Update reason with cap info (only for enforced cap mode)
             if strategy.enforce_monthly_cap:
                 reason += f" [{tx_capped_reason}]"

    # Append Budget Status to reason for visibility
    if not strategy.enforce_monthly_cap:
        # No Monthly Cap mode: Show available savings without monthly budget comparison
        reason += f" | Budget: Savings=${available_cash:.2f} | Mode: No Monthly Cap"
    else:
        # Enforced Cap mode: Show both savings and monthly spent/budget
        reason += f" | Budget: Savings=${available_cash:.2f} | Monthly Spent=${total_spent_sum:.2f}/${strategy.total_budget_usd:.0f}"
    
    # Check if multiplier is 0 or negative (no purchase needed)
    # This handles cases where user sets multiplier to 0 for a specific tier
    if multiplier <= 0:
        decision_data = base_decision.copy()
        decision_data.update(
            {
                "can_execute": False,
                "reason": f"Multiplier is 0 for {band}, no purchase needed",
                "ahr999_value": ahr999,
                "ahr_band": band,
                "multiplier": multiplier,
                "base_amount_usd": base_amount,
                "suggested_amount_usd": suggested_amount,
                "price_usd": price,
                "metrics_source": {"backend": source_backend, "label": source_label},
                "remaining_budget": remaining_budget if strategy.enforce_monthly_cap else None,
                "budget_resets": budget_resets,
                "time_until_reset": time_until_reset,
                "peak_price_usd": display_peak_price,
                "drawdown_ratio": display_drawdown_ratio,
                "drawdown_percentile": display_drawdown_snapshot["drawdown_percentile"] if display_drawdown_snapshot else None,
                "drawdown_hist_date": display_drawdown_snapshot["historical_date"] if display_drawdown_snapshot else None,
                "drawdown_hist_peak_price_usd": display_drawdown_snapshot["historical_peak"] if display_drawdown_snapshot else None,
                "drawdown_hist_price_usd": display_drawdown_snapshot["historical_price"] if display_drawdown_snapshot else None,
                "drawdown_context": drawdown_context,
            }
        )
        return DCADecision(**decision_data)

    # In No Monthly Cap mode, accumulated_savings is only for record-keeping
    # Actual balance check happens during execution via Binance API
    # We don't block execution based on accumulated_savings in No Monthly Cap mode
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
        remaining_budget=remaining_budget if strategy.enforce_monthly_cap else None,
        budget_resets=budget_resets,
        time_until_reset=time_until_reset,
        peak_price_usd=display_peak_price,
        drawdown_ratio=display_drawdown_ratio,
        drawdown_percentile=display_drawdown_snapshot["drawdown_percentile"] if display_drawdown_snapshot else None,
        drawdown_hist_date=display_drawdown_snapshot["historical_date"] if display_drawdown_snapshot else None,
        drawdown_hist_peak_price_usd=display_drawdown_snapshot["historical_peak"] if display_drawdown_snapshot else None,
        drawdown_hist_price_usd=display_drawdown_snapshot["historical_price"] if display_drawdown_snapshot else None,
        drawdown_context=drawdown_context,
    )
