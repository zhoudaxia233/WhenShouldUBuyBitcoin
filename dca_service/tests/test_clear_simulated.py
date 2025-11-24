"""
Test Clear Simulated Transactions Endpoint

Tests for the /api/transactions/clear-simulated endpoint to ensure:
1. Only SIMULATED transactions are deleted
2. LEDGER/MANUAL transactions are preserved
3. Blocked in LIVE mode
4. Idempotent operation
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from datetime import datetime, timezone

from dca_service.main import app
from dca_service.models import DCATransaction, DCAStrategy, ColdWalletEntry
from dca_service.database import get_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def setup_test_data(session: Session):
    """Set up test data with mixed transaction sources"""
    # Create strategy in DRY_RUN mode
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
    
    # Create LEDGER/MANUAL transaction
    manual_entry = ColdWalletEntry(
        btc_amount=0.5,
        fee_btc=0.0001,
        notes="Manual cold wallet entry"
    )
    session.add(manual_entry)
    
    session.commit()
    yield
    
    # Cleanup
    session.exec(select(DCATransaction)).all()
    for tx in session.exec(select(DCATransaction)).all():
        session.delete(tx)
    for entry in session.exec(select(ColdWalletEntry)).all():
        session.delete(entry)
    for strat in session.exec(select(DCAStrategy)).all():
        session.delete(strat)
    session.commit()


def test_clear_simulated_in_dry_run_mode(client, setup_test_data, session: Session):
    """Test clearing simulated transactions in DRY_RUN mode"""
    # Verify initial state
    simulated_txs = session.exec(
        select(DCATransaction).where(DCATransaction.source == "SIMULATED")
    ).all()
    assert len(simulated_txs) == 3
    
    manual_entries = session.exec(select(ColdWalletEntry)).all()
    assert len(manual_entries) == 1
    
    # Call clear endpoint
    response = client.post("/api/transactions/clear-simulated")
    
    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["deleted_count"] == 3
    assert "Cleared 3 simulated transaction(s)" in data["message"]
    
    # Verify database state
    simulated_txs_after = session.exec(
        select(DCATransaction).where(DCATransaction.source == "SIMULATED")
    ).all()
    assert len(simulated_txs_after) == 0
    
    # Verify manual entries still exist
    manual_entries_after = session.exec(select(ColdWalletEntry)).all()
    assert len(manual_entries_after) == 1


def test_clear_simulated_blocked_in_live_mode(client, session: Session):
    """Test that clearing is blocked in LIVE mode"""
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
    
    # Create a simulated transaction
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Simulated transaction",
        source="SIMULATED"
    )
    session.add(tx)
    session.commit()
    
    # Try to clear
    response = client.post("/api/transactions/clear-simulated")
    
    # Verify blocked
    assert response.status_code == 400
    data = response.json()
    assert "Cannot clear simulated history in LIVE mode" in data["detail"]
    
    # Verify transaction still exists
    simulated_txs = session.exec(
        select(DCATransaction).where(DCATransaction.source == "SIMULATED")
    ).all()
    assert len(simulated_txs) == 1
    
    # Cleanup
    session.delete(tx)
    session.delete(strategy)
    session.commit()


def test_clear_simulated_idempotent(client, setup_test_data, session: Session):
    """Test that calling clear multiple times is safe (idempotent)"""
    # First clear
    response1 = client.post("/api/transactions/clear-simulated")
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["deleted_count"] == 3
    
    # Second clear (should work but delete 0)
    response2 = client.post("/api/transactions/clear-simulated")
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["success"] is True
    assert data2["deleted_count"] == 0
    assert "Cleared 0 simulated transaction(s)" in data2["message"]


def test_clear_simulated_preserves_binance_transactions(client, session: Session):
    """Test that BINANCE transactions (future feature) are preserved"""
    # Create strategy in DRY_RUN mode
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
    
    # Create SIMULATED transaction
    simulated_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Simulated",
        source="SIMULATED"
    )
    session.add(simulated_tx)
    
    # Create BINANCE transaction (future feature)
    binance_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Real Binance trade",
        source="BINANCE"
    )
    session.add(binance_tx)
    session.commit()
    
    # Clear simulated
    response = client.post("/api/transactions/clear-simulated")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted_count"] == 1
    
    # Verify BINANCE transaction still exists
    binance_txs = session.exec(
        select(DCATransaction).where(DCATransaction.source == "BINANCE")
    ).all()
    assert len(binance_txs) == 1
    
    # Verify SIMULATED transaction is gone
    simulated_txs = session.exec(
        select(DCATransaction).where(DCATransaction.source == "SIMULATED")
    ).all()
    assert len(simulated_txs) == 0
    
    # Cleanup
    session.delete(binance_tx)
    session.delete(strategy)
    session.commit()
