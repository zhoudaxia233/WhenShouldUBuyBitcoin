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
from datetime import datetime, timezone

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
    assert data["state_changed_orders"] == 0
    
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


@patch("dca_service.services.sync_service.TradeSyncService")
def test_reset_and_sync_preserves_metadata_and_merges_split_fills(
    mock_service_cls,
    client,
    session: Session,
):
    """
    Reset & Sync should:
    1. Rebuild Binance trades from scratch
    2. Merge split fills by the same Binance order ID
    3. Restore semantic metadata (source / is_manual / ahr999) from pre-reset rows
    """
    # Pre-reset local row: DCA bot order with semantic metadata that Binance sync can't reconstruct.
    dca_tx = DCATransaction(
        timestamp=datetime(2026, 2, 20, 10, 0, tzinfo=timezone.utc),
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.42,
        notes="Automated DCA",
        source="DCA",
        is_manual=False,
        binance_order_id=1111,
        binance_trade_id=50001,
        fee_amount=0.1,
        fee_asset="USDC",
        intended_amount_usd=100.0,
        executed_amount_usd=100.0,
        executed_amount_btc=0.001,
        avg_execution_price_usd=100000.0,
    )

    # Pre-reset local row: add-position LIVE order (manual-triggered, app-executed)
    add_pos_tx = DCATransaction(
        timestamp=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
        status="SUCCESS",
        fiat_amount=49.37,
        btc_amount=0.00075,
        price=65823.0,
        ahr999=0.0,
        notes="Add Position confirmed after advice [BTCUSDC] (LIVE)",
        source="BINANCE",
        is_manual=True,
        binance_order_id=2222,
        binance_trade_id=60001,
        fee_amount=0.05,
        fee_asset="USDC",
        intended_amount_usd=49.37,
        executed_amount_usd=49.37,
        executed_amount_btc=0.00075,
        avg_execution_price_usd=65823.0,
    )
    session.add(dca_tx)
    session.add(add_pos_tx)
    session.commit()

    mock_instance = mock_service_cls.return_value

    async def _mock_sync(*, start_from_scratch: bool = False):
        assert start_from_scratch is True
        # Re-import order 1111 as split fills (would normally come from Binance myTrades)
        fill_1 = DCATransaction(
            timestamp=datetime(2026, 2, 20, 10, 0, 1, tzinfo=timezone.utc),
            status="SUCCESS",
            fiat_amount=40.0,
            btc_amount=0.0004,
            price=100000.0,
            ahr999=0.0,
            notes="Imported from Binance",
            source="MANUAL",
            is_manual=True,
            binance_order_id=1111,
            binance_trade_id=70001,
            fee_amount=0.04,
            fee_asset="USDC",
            intended_amount_usd=40.0,
            executed_amount_usd=40.0,
            executed_amount_btc=0.0004,
            avg_execution_price_usd=100000.0,
        )
        fill_2 = DCATransaction(
            timestamp=datetime(2026, 2, 20, 10, 0, 2, tzinfo=timezone.utc),
            status="SUCCESS",
            fiat_amount=60.0,
            btc_amount=0.0006,
            price=100000.0,
            ahr999=0.0,
            notes="Imported from Binance",
            source="MANUAL",
            is_manual=True,
            binance_order_id=1111,
            binance_trade_id=70002,
            fee_amount=0.06,
            fee_asset="USDC",
            intended_amount_usd=60.0,
            executed_amount_usd=60.0,
            executed_amount_btc=0.0006,
            avg_execution_price_usd=100000.0,
        )

        # Re-import add-position LIVE order as split fills too; source will be restored to BINANCE.
        fill_3 = DCATransaction(
            timestamp=datetime(2026, 2, 21, 12, 0, 1, tzinfo=timezone.utc),
            status="SUCCESS",
            fiat_amount=20.0,
            btc_amount=0.0003,
            price=66666.67,
            ahr999=0.0,
            notes="Imported from Binance",
            source="MANUAL",
            is_manual=True,
            binance_order_id=2222,
            binance_trade_id=80001,
            fee_amount=0.02,
            fee_asset="USDC",
            intended_amount_usd=20.0,
            executed_amount_usd=20.0,
            executed_amount_btc=0.0003,
            avg_execution_price_usd=66666.67,
        )
        fill_4 = DCATransaction(
            timestamp=datetime(2026, 2, 21, 12, 0, 2, tzinfo=timezone.utc),
            status="SUCCESS",
            fiat_amount=29.37,
            btc_amount=0.00045,
            price=65266.67,
            ahr999=0.0,
            notes="Imported from Binance",
            source="MANUAL",
            is_manual=True,
            binance_order_id=2222,
            binance_trade_id=80002,
            fee_amount=0.03,
            fee_asset="USDC",
            intended_amount_usd=29.37,
            executed_amount_usd=29.37,
            executed_amount_btc=0.00045,
            avg_execution_price_usd=65266.67,
        )

        session.add(fill_1)
        session.add(fill_2)
        session.add(fill_3)
        session.add(fill_4)
        session.commit()
        return 4

    mock_instance.sync_trades = AsyncMock(side_effect=_mock_sync)

    response = client.post("/api/transactions/clear-simulated")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["synced_count"] == 4
    assert data["merged_orders"] == 2
    assert data["merged_rows_removed"] == 2
    assert data["metadata_restored"] == 2
    # Pre-reset rows were already normalized; split-fill merge is rebuild work, not a net state change.
    assert data["state_changed_orders"] == 0

    txs = session.exec(
        select(DCATransaction).order_by(DCATransaction.binance_order_id)
    ).all()
    assert len(txs) == 2

    dca_rebuilt = next(tx for tx in txs if tx.binance_order_id == 1111)
    assert dca_rebuilt.source == "DCA"
    assert dca_rebuilt.is_manual is False
    assert dca_rebuilt.ahr999 == 0.42
    assert dca_rebuilt.notes == "Automated DCA"
    assert dca_rebuilt.fiat_amount == 100.0
    assert dca_rebuilt.executed_amount_usd == 100.0
    assert dca_rebuilt.btc_amount == 0.001
    assert dca_rebuilt.executed_amount_btc == 0.001
    assert dca_rebuilt.fee_amount == 0.1
    assert dca_rebuilt.fee_asset == "USDC"

    add_pos_rebuilt = next(tx for tx in txs if tx.binance_order_id == 2222)
    assert add_pos_rebuilt.source == "BINANCE"
    assert add_pos_rebuilt.is_manual is True
    assert add_pos_rebuilt.fiat_amount == pytest.approx(49.37)
    assert add_pos_rebuilt.btc_amount == pytest.approx(0.00075)
    assert add_pos_rebuilt.fee_amount == pytest.approx(0.05)
    assert add_pos_rebuilt.fee_asset == "USDC"


@patch("dca_service.services.sync_service.TradeSyncService")
def test_reset_and_sync_reports_net_changes_when_pre_reset_has_duplicate_rows(
    mock_service_cls,
    client,
    session: Session,
):
    # Broken pre-reset state: same order duplicated locally.
    tx1 = DCATransaction(
        timestamp=datetime(2026, 2, 22, 8, 0, tzinfo=timezone.utc),
        status="SUCCESS",
        fiat_amount=49.37,
        btc_amount=0.00075,
        price=65823.0,
        ahr999=0.0,
        notes="Imported from Binance",
        source="MANUAL",
        is_manual=True,
        binance_order_id=3333,
        binance_trade_id=90001,
        fee_amount=0.05,
        fee_asset="USDC",
        executed_amount_usd=49.37,
        executed_amount_btc=0.00075,
        avg_execution_price_usd=65823.0,
    )
    tx2 = DCATransaction(
        timestamp=datetime(2026, 2, 22, 8, 0, 1, tzinfo=timezone.utc),
        status="SUCCESS",
        fiat_amount=49.37,
        btc_amount=0.00075,
        price=65823.0,
        ahr999=0.0,
        notes="Imported from Binance",
        source="MANUAL",
        is_manual=True,
        binance_order_id=3333,
        binance_trade_id=90002,
        fee_amount=0.05,
        fee_asset="USDC",
        executed_amount_usd=49.37,
        executed_amount_btc=0.00075,
        avg_execution_price_usd=65823.0,
    )
    session.add(tx1)
    session.add(tx2)
    session.commit()

    mock_instance = mock_service_cls.return_value

    async def _mock_sync(*, start_from_scratch: bool = False):
        assert start_from_scratch is True
        rebuilt = DCATransaction(
            timestamp=datetime(2026, 2, 22, 8, 0, tzinfo=timezone.utc),
            status="SUCCESS",
            fiat_amount=49.37,
            btc_amount=0.00075,
            price=65823.0,
            ahr999=0.0,
            notes="Imported from Binance",
            source="MANUAL",
            is_manual=True,
            binance_order_id=3333,
            binance_trade_id=91001,
            fee_amount=0.05,
            fee_asset="USDC",
            executed_amount_usd=49.37,
            executed_amount_btc=0.00075,
            avg_execution_price_usd=65823.0,
        )
        session.add(rebuilt)
        session.commit()
        return 1

    mock_instance.sync_trades = AsyncMock(side_effect=_mock_sync)

    response = client.post("/api/transactions/clear-simulated")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["state_changed_orders"] == 1
