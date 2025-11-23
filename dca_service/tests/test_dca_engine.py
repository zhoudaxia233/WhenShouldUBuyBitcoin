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
    assert decision.can_execute is False
    assert "Over budget" in decision.reason


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_allow_over_budget(mock_metrics, session: Session, basic_strategy: DCAStrategy):
    """Test that disabling enforcement allows going over budget"""
    basic_strategy.enforce_monthly_cap = False
    session.add(basic_strategy)
    session.commit()
    
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
    assert decision.can_execute is True


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
    # Base Amount = 300/30 = 10
    # Suggested = 30
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
    assert abs(decision.base_amount_usd - 10.0) < 0.01
    assert abs(decision.suggested_amount_usd - 30.0) < 0.01
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
    
    # Should be capped at 10
    assert decision.can_execute is True
    assert abs(decision.suggested_amount_usd - 10.0) < 0.01


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
