import pytest
from unittest.mock import patch
from sqlmodel import Session
from datetime import datetime, timezone

from dca_service.models import DCAStrategy
from dca_service.services.dca_engine import calculate_dca_decision

@pytest.fixture
def strategy(session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
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
def test_engine_metrics_unavailable(mock_metrics, session: Session, strategy: DCAStrategy):
    mock_metrics.return_value = None # Simulate missing/stale metrics
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    assert "unavailable or stale" in decision.reason

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_engine_metrics_valid(mock_metrics, session: Session, strategy: DCAStrategy):
    mock_metrics.return_value = {
        "ahr999": 0.4, 
        "price_usd": 50000.0, 
        "timestamp": datetime.now(timezone.utc)
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    assert decision.ahr_band == "low"
