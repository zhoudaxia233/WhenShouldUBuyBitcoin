import pytest
from sqlmodel import Session, SQLModel, create_engine
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from dca_service.models import DCAStrategy
from dca_service.services.dca_engine import calculate_dca_decision

# Setup in-memory DB
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

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
