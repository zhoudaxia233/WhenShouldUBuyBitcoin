import pytest
from unittest.mock import patch
from sqlmodel import Session, select
from datetime import datetime

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision

@pytest.fixture
def strategy(session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,
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
def test_engine_inactive_strategy(mock_metrics, session: Session, strategy: DCAStrategy):
    strategy.is_active = False
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {"ahr999": 0.4, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    assert decision.reason == "Strategy is inactive"

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_low_band(mock_metrics, session: Session, strategy: DCAStrategy):
    mock_metrics.return_value = {"ahr999": 0.4, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    assert decision.ahr_band == "low"
    assert decision.multiplier == 0.5
    assert decision.suggested_amount_usd == 50.0 * 0.5 # Base 50

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_mid_band(mock_metrics, session: Session, strategy: DCAStrategy):
    mock_metrics.return_value = {"ahr999": 1.0, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    assert decision.ahr_band == "mid"
    assert decision.multiplier == 1.0

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_high_band(mock_metrics, session: Session, strategy: DCAStrategy):
    mock_metrics.return_value = {"ahr999": 1.5, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    assert decision.ahr_band == "high"
    assert decision.multiplier == 1.5

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_over_budget(mock_metrics, session: Session, strategy: DCAStrategy):
    # Spend almost all budget
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=980.0,
        price=50000.0,
        ahr999=1.0
    )
    session.add(tx)
    session.commit()
    
    mock_metrics.return_value = {"ahr999": 1.0, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    # Suggested amount = 50 * 1.0 = 50. Total spent 980 + 50 = 1030 > 1000
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    assert "Over budget" in decision.reason

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_allow_over_budget(mock_metrics, session: Session, strategy: DCAStrategy):
    strategy.allow_over_budget = True
    session.add(strategy)
    session.commit()
    
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=980.0,
        price=50000.0,
        ahr999=1.0
    )
    session.add(tx)
    session.commit()
    
    mock_metrics.return_value = {"ahr999": 1.0, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
