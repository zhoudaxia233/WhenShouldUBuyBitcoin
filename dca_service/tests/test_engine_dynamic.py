import pytest
from unittest.mock import patch
from sqlmodel import Session, select
from datetime import datetime, timezone

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_dynamic_strategy_integration(mock_metrics, session: Session):
    """Test that engine correctly uses dynamic strategy logic"""
    # Setup Strategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=300.0, # $10/day approx
        strategy_type="dynamic_ahr999",
        dynamic_min_multiplier=0.0,
        dynamic_max_multiplier=10.0,
        dynamic_gamma=2.0,
        dynamic_a_low=0.45,
        dynamic_a_high=1.0,
        dynamic_enable_drawdown_boost=True,
        dynamic_enable_monthly_cap=True,
        dynamic_monthly_cap=800.0,
        # Legacy fields required by model but ignored by dynamic logic
        ahr999_multiplier_low=0,
        ahr999_multiplier_mid=0,
        ahr999_multiplier_high=0
    )
    session.add(strategy)
    session.commit()
    
    # Mock Metrics with Peak180
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
    assert decision.ahr_band == "mid" # 0.45 < 0.725 < 1.0

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_dynamic_strategy_monthly_cap(mock_metrics, session: Session):
    """Test monthly cap enforcement in engine integration"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=300.0,
        strategy_type="dynamic_ahr999",
        dynamic_monthly_cap=100.0, # Low cap
        # Legacy fields
        ahr999_multiplier_low=0,
        ahr999_multiplier_mid=0,
        ahr999_multiplier_high=0
    )
    session.add(strategy)
    
    # Add transactions to fill cap
    # Spent 90, Cap 100 -> Remaining 10
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=90.0,
        price=50000.0,
        ahr999=0.5,
        timestamp=month_start
    )
    session.add(tx)
    session.commit()
    
    # Mock Metrics -> Suggested 30 (same as above)
    mock_metrics.return_value = {
        "ahr999": 0.725,
        "price_usd": 70000.0,
        "peak180": 100000.0,
        "timestamp": datetime.now(timezone.utc)
    }
    
    decision = calculate_dca_decision(session)
    
    # Should be capped at 10
    assert decision.can_execute is True
    assert abs(decision.suggested_amount_usd - 10.0) < 0.01

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_legacy_fallback(mock_metrics, session: Session):
    """Test that legacy strategy still works"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=300.0,
        strategy_type="legacy_band", # Explicit legacy
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.4, # Low band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc)
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.can_execute is True
    assert decision.ahr_band == "low"
    assert decision.multiplier == 2.0
    # Base = 300/30 = 10 -> Suggested = 20
    assert abs(decision.suggested_amount_usd - 20.0) < 0.01
