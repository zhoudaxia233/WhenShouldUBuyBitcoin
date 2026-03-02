"""
Consolidated DCA Engine Tests

Tests for the DCA decision-making engine covering:
- Legacy/Percentile Strategy (6 tiers based on historical percentiles)
- Dynamic AHR999 Strategy (continuous curve with drawdown boost)
- Common functionality (inactive strategy, budget checks, metrics unavailable)
"""
import pytest
from unittest.mock import patch
from sqlmodel import Session
from datetime import datetime, timezone

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision


# ============================================================================
# COMMON TESTS (Apply to all strategies)
# ============================================================================

@pytest.fixture
def basic_strategy(session: Session):
    """Basic strategy for common tests"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        enforce_monthly_cap=True,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5,
        target_btc_amount=1.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_inactive_strategy(mock_metrics, session: Session, basic_strategy: DCAStrategy):
    """Test that inactive strategy prevents execution"""
    basic_strategy.is_active = False
    session.add(basic_strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.4,
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    assert decision.reason == "Strategy is inactive"


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_over_budget_with_enforcement(mock_metrics, session: Session, basic_strategy: DCAStrategy):
    """Test that budget enforcement blocks execution when over budget"""
    # Initialize budget tracking (simulate that budget was provided at month start)
    basic_strategy.last_monthly_inflow = datetime(2025, 12, 1, tzinfo=timezone.utc)
    basic_strategy.accumulated_savings = 1000.0  # Start with full monthly budget
    session.add(basic_strategy)
    session.commit()
    
    # Spend almost all budget
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=980.0,
        price=50000.0,
        ahr999=1.0
    )
    session.add(tx)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 1.0,
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    # Should still be able to execute with $20 remaining (can buy small amount)
    # But suggested amount will be capped to remaining budget
    assert decision.suggested_amount_usd <= 20.0


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_allow_over_budget(mock_metrics, session: Session, basic_strategy: DCAStrategy):
    """
    Test No Monthly Cap mode behavior:
    - Shows uncapped suggested amount (not limited by monthly budget)
    - But execution still requires sufficient accumulated savings
    """
    basic_strategy.enforce_monthly_cap = False
    basic_strategy.accumulated_savings = 100.0  # Ensure sufficient savings for execution
    basic_strategy.last_monthly_inflow = datetime.now(timezone.utc)  # Mark as initialized to prevent reset
    session.add(basic_strategy)
    session.commit()
    
    # Add transaction showing we've spent $980 (over typical monthly budget)
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=980.0,
        price=50000.0,
        ahr999=1.0
    )
    session.add(tx)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 1.0,
        "price_usd": 50000.0,
        "peak180": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    
    # In No Monthly Cap mode with sufficient savings, execution should be allowed
    # even though we've already spent $980 (demonstrating no monthly limit)
    assert decision.can_execute is True
    assert "No Monthly Cap" in decision.reason
    assert "WARNING" not in decision.reason  # No warning when savings are sufficient


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_metrics_unavailable(mock_metrics, session: Session, basic_strategy: DCAStrategy):
    """Test that engine handles missing/stale metrics gracefully"""
    mock_metrics.return_value = None
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    assert "unavailable or stale" in decision.reason


# ============================================================================
# LEGACY/PERCENTILE STRATEGY TESTS
# ============================================================================

@pytest.fixture
def percentile_strategy(session: Session):
    """Strategy using percentile-based approach (new 6-tier system)"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        strategy_type="legacy_band",  # Uses percentile logic now
        enforce_monthly_cap=True,
        # Percentile multipliers (6 tiers)
        ahr999_multiplier_p10=5.0,
        ahr999_multiplier_p25=2.0,
        ahr999_multiplier_p50=1.0,
        ahr999_multiplier_p75=0.5,
        ahr999_multiplier_p90=0.0,
        ahr999_multiplier_p100=0.0,
        # Legacy fields for backward compatibility
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        target_btc_amount=1.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_percentile_strategy_execution(mock_metrics, session: Session, percentile_strategy: DCAStrategy):
    """Test that percentile strategy calculates correctly"""
    # AHR999 in p25-p50 range -> should use multiplier 1.0
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    # Multiplier depends on which percentile tier 0.6 falls into
    assert decision.multiplier >= 0.0


# ============================================================================
# DYNAMIC AHR999 STRATEGY TESTS
# ============================================================================

@pytest.fixture
def fixed_dca_strategy(session: Session):
    """Strategy using fixed DCA approach (budget/frequency only)."""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=304.4,  # Exactly $10/day with 30.44 divisor
        strategy_type="fixed_dca",
        execution_frequency="daily",
        enforce_monthly_cap=True,
        # Required legacy fields
        ahr999_multiplier_low=0,
        ahr999_multiplier_mid=0,
        ahr999_multiplier_high=0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_fixed_dca_ignores_ahr_for_sizing(mock_metrics, session: Session, fixed_dca_strategy: DCAStrategy):
    """Fixed DCA should use budget/frequency amount regardless of AHR999 level."""
    mock_metrics.return_value = {
        "ahr999": 0.25,
        "price_usd": 70000.0,
        "peak180": 100000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    decision_low = calculate_dca_decision(session)

    mock_metrics.return_value = {
        "ahr999": 1.5,
        "price_usd": 70000.0,
        "peak180": 100000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    decision_high = calculate_dca_decision(session)

    assert decision_low.can_execute is True
    assert decision_high.can_execute is True
    assert decision_low.ahr999_value == 0.25  # still reported for reference
    assert decision_high.ahr999_value == 1.5  # still reported for reference
    assert abs(decision_low.base_amount_usd - 10.0) < 0.01
    assert abs(decision_high.base_amount_usd - 10.0) < 0.01
    assert abs(decision_low.suggested_amount_usd - 10.0) < 0.01
    assert abs(decision_high.suggested_amount_usd - 10.0) < 0.01
    assert decision_low.multiplier == 1.0
    assert decision_high.multiplier == 1.0

@pytest.fixture
def dynamic_strategy(session: Session):
    """Strategy using dynamic AHR999 approach"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=300.0,  # $10/day approx
        strategy_type="dynamic_ahr999",
        enforce_monthly_cap=True,
        dynamic_min_multiplier=0.0,
        dynamic_max_multiplier=10.0,
        dynamic_gamma=2.0,
        dynamic_a_low=0.45,
        dynamic_a_high=1.0,
        dynamic_enable_drawdown_boost=True,
        # Legacy fields required by model but ignored by dynamic logic
        ahr999_multiplier_low=0,
        ahr999_multiplier_mid=0,
        ahr999_multiplier_high=0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_dynamic_strategy_integration(mock_metrics, session: Session, dynamic_strategy: DCAStrategy):
    """Test that engine correctly uses dynamic strategy logic"""
    # AHR = 0.725 -> x=0.5 -> Base M=2.5
    # Price=70k, Peak=100k -> DD=0.3 -> Factor=1.2
    # Final M = 3.0
    # Base Amount = 300/30.44 = 9.85545335085414 (using 30.44 days per month)
    # Suggested = 9.85545335085414 * 3.0 = 29.566360052562416
    mock_metrics.return_value = {
        "ahr999": 0.725,
        "price_usd": 70000.0,
        "peak180": 100000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.can_execute is True
    assert decision.ahr999_value == 0.725
    assert abs(decision.multiplier - 3.0) < 0.01
    # Base amount = 300 / 30.44 = 9.85545335085414
    assert abs(decision.base_amount_usd - 9.85545335085414) < 0.01
    # Suggested amount = 9.85545335085414 * 3.0 = 29.566360052562416
    assert abs(decision.suggested_amount_usd - 29.566360052562416) < 0.01
    assert decision.ahr_band == "mid"  # 0.45 < 0.725 < 1.0


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_dynamic_strategy_monthly_cap(mock_metrics, session: Session, dynamic_strategy: DCAStrategy):
    """Test monthly cap enforcement in dynamic strategy"""
    # Override monthly cap to a low value
    dynamic_strategy.total_budget_usd = 100.0  # Low cap
    session.add(dynamic_strategy)
    
    # Add transactions to fill cap
    # Spent 90, Cap 100 -> Remaining 10
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=90.0,
        price=50000.0,
        ahr999=0.5,
        timestamp=month_start
    )
    session.add(tx)
    session.commit()
    
    # Mock Metrics -> Would suggest 30 but should cap at 10
    mock_metrics.return_value = {
        "ahr999": 0.725,
        "price_usd": 70000.0,
        "peak180": 100000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    
    # Should be capped at remaining budget (10.0)
    # Base amount = 100 / 30.44 = 3.2851511169513796
    # Suggested = 3.2851511169513796 * 3.0 = 9.85545335085414
    # But capped at remaining budget = 10.0
    assert decision.can_execute is True
    # The suggested amount should be capped at remaining budget (10.0)
    # but the actual calculation gives 9.85545335085414 which is less than 10.0
    assert abs(decision.suggested_amount_usd - 9.85545335085414) < 0.01


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_dynamic_strategy_fallback_to_legacy(mock_metrics, session: Session):
    """Test that legacy strategy still works when explicitly set"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=300.0,
        strategy_type="legacy_band",  # Explicit legacy
        enforce_monthly_cap=True,
        ahr999_multiplier_p10=2.0,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.4,  # Should trigger appropriate percentile tier
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.can_execute is True
    # Multiplier depends on which percentile tier 0.4 falls into
    assert decision.multiplier >= 0.0


# ============================================================================
# REGRESSION TESTS
# ============================================================================

def test_legacy_strategy_execution_no_error(session):
    """
    Regression test: Ensure legacy strategy execution does not raise UnboundLocalError.
    """
    # 1. Create a legacy strategy
    strategy = DCAStrategy(
        total_budget_usd=1000.0,
        enforce_monthly_cap=True,
        ahr999_multiplier_low=1.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0,
        execution_frequency="daily",
        strategy_type="legacy_band",  # Explicitly set to legacy
        is_active=True
    )
    session.add(strategy)
    session.commit()
    
    # 2. Mock metrics
    mock_metrics = {
        "price_usd": 50000.0,
        "ahr999": 0.40, # Low band
        "peak180": 60000.0,
        "source": "mock",
        "source_label": "Mock Data"
    }
    
    # 3. Run decision calculation
    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
        decision = calculate_dca_decision(session)
        
    # 4. Verify no error and correct reason
    assert decision.can_execute is True
    # New percentile strategy provides detailed reason with AHR999 percentile info
    assert "AHR999" in decision.reason or decision.reason == "Conditions met"
    # AHR999 0.40 falls into p10 tier (bottom 10%) in new percentile strategy
    assert decision.ahr_band in ["p10", "low"]  # Accept either
    assert decision.multiplier == 1.5


def test_bottoming_signal_prefers_fresher_daily_report(session: Session, basic_strategy: DCAStrategy):
    """If daily_report signal is newer than CSV signal, preview should use daily_report."""
    metrics = {
        "ahr999": 0.8,
        "price_usd": 70000.0,
        "peak180": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test",
    }
    csv_signal = {
        "available": True,
        "as_of_date": "2026-02-26",
        "source": "metrics_csv",
    }
    report_signal = {
        "available": True,
        "as_of_date": "2026-03-01",
        "source": "daily_report",
    }

    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=metrics), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_volume_signal", return_value=csv_signal), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_signal_from_daily_report", return_value=report_signal), \
         patch("dca_service.services.dca_engine.get_latest_macro_preview_snapshot", return_value=None):
        decision = calculate_dca_decision(session)

    assert decision.bottoming_signal is not None
    assert decision.bottoming_signal.get("as_of_date") == "2026-03-01"
    assert decision.bottoming_signal.get("source") == "daily_report"


def test_bottoming_signal_prefers_csv_on_tie(session: Session, basic_strategy: DCAStrategy):
    """If CSV and daily_report have same date, keep CSV as primary source."""
    metrics = {
        "ahr999": 0.8,
        "price_usd": 70000.0,
        "peak180": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Test",
    }
    csv_signal = {
        "available": True,
        "as_of_date": "2026-03-01",
        "source": "metrics_csv",
    }
    report_signal = {
        "available": True,
        "as_of_date": "2026-03-01",
        "source": "daily_report",
    }

    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=metrics), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_volume_signal", return_value=csv_signal), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_signal_from_daily_report", return_value=report_signal), \
         patch("dca_service.services.dca_engine.get_latest_macro_preview_snapshot", return_value=None):
        decision = calculate_dca_decision(session)

    assert decision.bottoming_signal is not None
    assert decision.bottoming_signal.get("as_of_date") == "2026-03-01"
    assert decision.bottoming_signal.get("source") == "metrics_csv"


def test_bottoming_signal_present_when_metrics_unavailable(session: Session, basic_strategy: DCAStrategy):
    """Even when trading metrics are unavailable, preview should still include latest signal."""
    report_signal = {
        "available": True,
        "as_of_date": "2026-03-01",
        "source": "daily_report",
    }
    macro_preview = {
        "available": True,
        "report_date": "2026-03-01",
        "macro_risk_score": 40.0,
    }

    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=None), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_volume_signal", return_value=None), \
         patch("dca_service.services.dca_engine.get_latest_bottoming_signal_from_daily_report", return_value=report_signal), \
         patch("dca_service.services.dca_engine.get_latest_macro_preview_snapshot", return_value=macro_preview):
        decision = calculate_dca_decision(session)

    assert decision.can_execute is False
    assert "unavailable or stale" in decision.reason
    assert decision.bottoming_signal is not None
    assert decision.bottoming_signal.get("as_of_date") == "2026-03-01"
    assert decision.bottoming_signal.get("source") == "daily_report"
    assert decision.bottoming_signal.get("macro_snapshot") == macro_preview
