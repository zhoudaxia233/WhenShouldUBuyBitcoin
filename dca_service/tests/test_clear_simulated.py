"""
Test Reset & Sync Transactions Endpoint

Tests for the /api/transactions/clear-simulated endpoint to ensure:
1. ALL transactions (SIMULATED, MANUAL, BINANCE) are deleted.
2. Sync service is triggered with start_from_scratch=True.
3. Works in both DRY_RUN and LIVE modes.
"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.models import DCATransaction, DCAStrategy


@pytest.fixture
def setup_test_data(session: Session):
    """Set up test data with mixed transaction sources"""
    # Create strategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        target_btc_amount=1.0,
        execution_mode="DRY_RUN"
    )
    session.add(strategy)
    
    # Create SIMULATED transactions
    for i in range(3):
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes=f"Simulated transaction {i}",
            source="SIMULATED"
        )
        session.add(tx)
    
    # Create MANUAL transaction (should also be deleted in a full reset)
    manual_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=500.0,
        btc_amount=0.01,
        price=50000.0,
        ahr999=0.5,
        notes="Manual trade",
        source="MANUAL",
        is_manual=True
    )
    session.add(manual_tx)
    
    session.commit()
    yield


@patch("dca_service.services.sync_service.TradeSyncService")
def test_reset_and_sync_clears_all(mock_service_cls, client, setup_test_data, session: Session):
    """Test that ALL transactions are deleted and sync is triggered"""
    # Setup mock
    mock_instance = mock_service_cls.return_value
    mock_instance.sync_trades = AsyncMock(return_value=5)
    
    # Verify initial state
    all_txs = session.exec(select(DCATransaction)).all()
    assert len(all_txs) == 4  # 3 simulated + 1 manual
    
    # Call clear endpoint
    response = client.post("/api/transactions/clear-simulated")
    
    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted_count"] == "ALL"
    assert data["synced_count"] == 5
    
    # Verify database state (should be empty before sync adds new ones, 
    # but since we mocked sync to return count but not actually add to DB, it should be empty)
    all_txs_after = session.exec(select(DCATransaction)).all()
    assert len(all_txs_after) == 0
    
    # Verify sync was called with start_from_scratch=True
    mock_instance.sync_trades.assert_called_once_with(start_from_scratch=True)


@patch("dca_service.services.sync_service.TradeSyncService")
def test_reset_works_in_live_mode(mock_service_cls, client, session: Session):
    """Test that reset works in LIVE mode (no longer blocked)"""
    # Setup mock
    mock_instance = mock_service_cls.return_value
    mock_instance.sync_trades = AsyncMock(return_value=0)
    
    # Create strategy in LIVE mode
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        target_btc_amount=1.0,
        execution_mode="LIVE"
    )
    session.add(strategy)
    
    # Create a transaction
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Live transaction",
        source="DCA"
    )
    session.add(tx)
    session.commit()
    
    # Call clear endpoint
    response = client.post("/api/transactions/clear-simulated")
    
    # Verify success (not 400)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Verify transaction is gone
    txs = session.exec(select(DCATransaction)).all()
    assert len(txs) == 0
