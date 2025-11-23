"""
Tests for execution frequency base amount calculation.
This test file ensures the bug where execution_frequency was ignored
when allow_over_budget=True never comes back.
"""
import pytest
from unittest.mock import patch
from sqlmodel import Session
from datetime import datetime, timezone

from dca_service.models import DCAStrategy
from dca_service.services.dca_engine import calculate_dca_decision


@pytest.fixture
def daily_strategy(session: Session):
    """Strategy with daily execution frequency and monthly budget reset."""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=3000.0,
        allow_over_budget=False,  # Budget resets monthly
        execution_frequency="daily",
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@pytest.fixture
def weekly_strategy(session: Session):
    """Strategy with weekly execution frequency and monthly budget reset."""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=3000.0,
        allow_over_budget=False,  # Budget resets monthly
        execution_frequency="weekly",
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_daily_frequency_calculates_correct_base_amount(mock_metrics, session: Session, daily_strategy: DCAStrategy):
    """Test that daily frequency divides budget by 30."""
    mock_metrics.return_value = {
        "ahr999": 1.0,  # Mid band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    
    decision = calculate_dca_decision(session)
    
    # Budget of $3000 / 30 days = $100/day base amount
    # With mid-band multiplier of 1.0: suggested = $100 * 1.0 = $100
    assert decision.can_execute is True
    assert decision.base_amount_usd == 100.0
    assert decision.suggested_amount_usd == 100.0


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_weekly_frequency_calculates_correct_base_amount(mock_metrics, session: Session, weekly_strategy: DCAStrategy):
    """Test that weekly frequency divides budget by 4."""
    mock_metrics.return_value = {
        "ahr999": 1.0,  # Mid band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    
    decision = calculate_dca_decision(session)
    
    # Budget of $3000 / 4 weeks = $750/week base amount
    # With mid-band multiplier of 1.0: suggested = $750 * 1.0 = $750
    assert decision.can_execute is True
    assert decision.base_amount_usd == 750.0
    assert decision.suggested_amount_usd == 750.0


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_daily_frequency_with_allow_over_budget(mock_metrics, session: Session, daily_strategy: DCAStrategy):
    """
    CRITICAL: Test that daily frequency works even when allow_over_budget=True.
    This is the bug that was fixed - execution_frequency was being ignored.
    """
    # Enable allow_over_budget
    daily_strategy.allow_over_budget = True
    session.add(daily_strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.4,  # Low band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    
    decision = calculate_dca_decision(session)
    
    # Budget of $3000 / 30 days = $100/day base amount
    # With low-band multiplier of 2.0: suggested = $100 * 2.0 = $200
    assert decision.can_execute is True
    assert decision.base_amount_usd == 100.0
    assert decision.suggested_amount_usd == 200.0
    assert decision.budget_resets is False  # allow_over_budget=True means no reset


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_weekly_frequency_with_allow_over_budget(mock_metrics, session: Session, weekly_strategy: DCAStrategy):
    """
    CRITICAL: Test that weekly frequency works even when allow_over_budget=True.
    This is the bug that was fixed - execution_frequency was being ignored.
    """
    # Enable allow_over_budget
    weekly_strategy.allow_over_budget = True
    session.add(weekly_strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 1.5,  # High band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    
    decision = calculate_dca_decision(session)
    
    # Budget of $3000 / 4 weeks = $750/week base amount
    # With high-band multiplier of 0.5: suggested = $750 * 0.5 = $375
    assert decision.can_execute is True
    assert decision.base_amount_usd == 750.0
    assert decision.suggested_amount_usd == 375.0
    assert decision.budget_resets is False  # allow_over_budget=True means no reset


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_frequency_change_updates_base_amount(mock_metrics, session: Session, daily_strategy: DCAStrategy):
    """Test that changing frequency updates the base amount calculation."""
    mock_metrics.return_value = {
        "ahr999": 1.0,  # Mid band
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    
    # First check as daily
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 100.0  # $3000 / 30
    assert decision.suggested_amount_usd == 100.0
    
    # Change to weekly
    daily_strategy.execution_frequency = "weekly"
    session.add(daily_strategy)
    session.commit()
    
    # Check again as weekly
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 750.0  # $3000 / 4
    assert decision.suggested_amount_usd == 750.0


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_daily_with_different_multipliers(mock_metrics, session: Session, daily_strategy: DCAStrategy):
    """Test that multipliers work correctly with daily frequency."""
    # Test low band (multiplier 2.0)
    mock_metrics.return_value = {
        "ahr999": 0.4,
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 100.0
    assert decision.suggested_amount_usd == 200.0  # $100 * 2.0
    
    # Test mid band (multiplier 1.0)
    mock_metrics.return_value["ahr999"] = 1.0
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 100.0
    assert decision.suggested_amount_usd == 100.0  # $100 * 1.0
    
    # Test high band (multiplier 0.5)
    mock_metrics.return_value["ahr999"] = 1.5
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 100.0
    assert decision.suggested_amount_usd == 50.0  # $100 * 0.5


@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_weekly_with_different_multipliers(mock_metrics, session: Session, weekly_strategy: DCAStrategy):
    """Test that multipliers work correctly with weekly frequency."""
    # Test low band (multiplier 2.0)
    mock_metrics.return_value = {
        "ahr999": 0.4,
        "price_usd": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV Data"
    }
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 750.0
    assert decision.suggested_amount_usd == 1500.0  # $750 * 2.0
    
    # Test mid band (multiplier 1.0)
    mock_metrics.return_value["ahr999"] = 1.0
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 750.0
    assert decision.suggested_amount_usd == 750.0  # $750 * 1.0
    
    # Test high band (multiplier 0.5)
    mock_metrics.return_value["ahr999"] = 1.5
    decision = calculate_dca_decision(session)
    assert decision.base_amount_usd == 750.0
    assert decision.suggested_amount_usd == 375.0  # $750 * 0.5
