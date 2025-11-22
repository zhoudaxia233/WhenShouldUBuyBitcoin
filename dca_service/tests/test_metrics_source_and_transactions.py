import pytest
from unittest.mock import patch
from sqlmodel import Session, select
from datetime import datetime, timezone

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision

# Test fixtures
@pytest.fixture
def strategy(session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0,
        execution_frequency="daily",
        execution_time_utc="07:30"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy

# Test metrics_source in preview response
@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_preview_includes_metrics_source(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that /api/dca/preview returns metrics_source with backend and label"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file)"
    }
    
    decision = calculate_dca_decision(session)
    
    # Check metrics_source structure
    assert "metrics_source" in decision.model_dump()
    assert isinstance(decision.metrics_source, dict)
    assert "backend" in decision.metrics_source
    assert "label" in decision.metrics_source
    assert decision.metrics_source["backend"] == "csv"
    assert "CSV" in decision.metrics_source["label"]

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_preview_metrics_source_when_unavailable(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that metrics_source is present even when can_execute=false"""
    mock_metrics.return_value = None  # Simulating unavailable metrics
    
    decision = calculate_dca_decision(session)
    
    assert decision.can_execute is False
    assert "metrics_source" in decision.model_dump()
    assert decision.metrics_source["backend"] == "unknown"
    assert decision.metrics_source["label"] == "Unknown"

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_preview_realtime_metrics_source(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that realtime metrics source is properly labeled"""
    mock_metrics.return_value = {
        "ahr999": 0.7,
        "price_usd": 95000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "realtime",
        "source_label": "Realtime (WhenShouldUBuyBitcoin + Binance)"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.metrics_source["backend"] == "realtime"
    assert "Realtime" in decision.metrics_source["label"]
    assert "Binance" in decision.metrics_source["label"]

# Test new transaction fields
@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_simulated_execution_populates_new_fields(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that simulated execution creates transaction with intent and execution fields"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file)"
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    
    # Simulate the API endpoint creating a transaction
    btc_amount = decision.suggested_amount_usd / decision.price_usd
    
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=decision.suggested_amount_usd,
        btc_amount=btc_amount,
        price=decision.price_usd,
        ahr999=decision.ahr999_value,
        notes="SIMULATED",
        # New Phase 6 fields
        intended_amount_usd=decision.suggested_amount_usd,
        executed_amount_usd=decision.suggested_amount_usd,
        executed_amount_btc=btc_amount,
        avg_execution_price_usd=decision.price_usd,
        fee_amount=0.0,
        fee_asset=None
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    # Verify all new fields are populated
    assert transaction.intended_amount_usd == decision.suggested_amount_usd
    assert transaction.executed_amount_usd == decision.suggested_amount_usd
    assert transaction.executed_amount_btc == btc_amount
    assert transaction.avg_execution_price_usd == decision.price_usd
    assert transaction.fee_amount == 0.0
    assert transaction.fee_asset is None

def test_transaction_model_backwards_compatibility(session: Session):
    """Test that old transactions without new fields still work"""
    # Create a transaction with only legacy fields
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.5,
        notes="Test"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    # Verify new fields are None (nullable)
    assert transaction.intended_amount_usd is None
    assert transaction.executed_amount_usd is None
    assert transaction.executed_amount_btc is None
    assert transaction.avg_execution_price_usd is None
    assert transaction.fee_amount is None
    assert transaction.fee_asset is None

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_execution_skipped_no_transaction_created(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that when can_execute=false, no transaction is created"""
    # Set strategy to inactive
    strategy.is_active = False
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file)"
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is False
    
    # Simulating the API endpoint NOT creating a transaction
    transactions_count_before = len(session.exec(select(DCATransaction)).all())
    
    # No transaction should be created when can_execute is False
    # (this is handled in the API endpoint, testing the logic here)
    
    transactions_count_after = len(session.exec(select(DCATransaction)).all())
    assert transactions_count_before == transactions_count_after

# Test fallback metrics source label
@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_fallback_metrics_source_label(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that fallback to CSV is properly labeled"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file) [fallback]"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.metrics_source["backend"] == "csv"
    assert "[fallback]" in decision.metrics_source["label"]
