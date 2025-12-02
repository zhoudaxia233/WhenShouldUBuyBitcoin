"""
Tests for duplicate DCA transaction prevention in sync_service.

Verifies that:
1. DCA bot transactions are not duplicated as MANUAL when syncing from Binance
2. Multiple fills for the same order are handled correctly
3. Real manual trades are still imported correctly
"""
import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from sqlmodel import Session, select

from dca_service.models import DCATransaction
from dca_service.services.sync_service import TradeSyncService


class TestDuplicateDCADetection:
    """Tests to prevent DCA transactions from being duplicated as MANUAL"""
    
    def test_dca_order_not_duplicated_as_manual(self, session: Session):
        """
        Test that a DCA bot transaction is not duplicated when syncing from Binance.
        
        Scenario:
        1. DCA bot executes trade, creates DCATransaction with binance_order_id=123
        2. Trade sync runs and fetches the same trade from Binance
        3. Verify: No new MANUAL transaction is created
        4. Verify: binance_trade_id is updated on the existing DCA record
        """
        # 1. Create a DCA transaction (as if bot just executed it)
        dca_tx = DCATransaction(
            timestamp=datetime.now(timezone.utc),
            status="SUCCESS",
            fiat_amount=50.0,
            btc_amount=0.0006,
            price=83333.33,
            ahr999=0.52,
            notes="Automated DCA",
            source="DCA",
            binance_order_id=123456789,
            binance_trade_id=None,  # Not yet linked
            intended_amount_usd=50.0,
            executed_amount_usd=50.0,
            executed_amount_btc=0.0006,
            avg_execution_price_usd=83333.33
        )
        session.add(dca_tx)
        session.commit()
        session.refresh(dca_tx)
        
        # 2. Mock Binance client to return this trade
        mock_binance_client = AsyncMock()
        mock_binance_client._request.return_value = [{
            "id": 999888777,  # trade_id
            "orderId": 123456789,  # Same as DCA transaction
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "price": "83333.33",
            "qty": "0.0006",
            "quoteQty": "50.0",
            "commission": "0.04",
            "commissionAsset": "USDC",
            "isBuyer": True
        }]
        mock_binance_client.close = AsyncMock()
        
        # 3. Run sync using asyncio.run()
        sync_service = TradeSyncService(session)
        
        with patch.object(sync_service, '_get_client', return_value=mock_binance_client):
            added = asyncio.run(sync_service.sync_trades())
        
        # 4. Verify results
        # Should add 0 new transactions (just update existing)
        assert added == 0, "Should not create new MANUAL transaction for DCA order"
        
        # Verify the DCA transaction was updated with trade_id
        session.refresh(dca_tx)
        assert dca_tx.binance_trade_id == 999888777, "binance_trade_id should be linked"
        assert dca_tx.source == "DCA", "Source should still be DCA"
        
        # Verify no MANUAL transaction was created
        manual_txs = session.exec(
            select(DCATransaction).where(DCATransaction.source == "MANUAL")
        ).all()
        assert len(manual_txs) == 0, "No MANUAL transactions should be created"
    
    def test_multiple_fills_for_same_order(self, session: Session):
        """
        Test that multiple fills for the same order are handled correctly.
        
        Scenario:
        1. DCA bot creates transaction with order_id=123
        2. Sync runs with 3 fills for order_id=123
        3. Verify: Only 1 transaction exists (not 3 duplicates)
        4. Verify: First fill's trade_id is linked
        """
        # 1. Create DCA transaction
        dca_tx = DCATransaction(
            timestamp=datetime.now(timezone.utc),
            status="SUCCESS",
            fiat_amount=150.0,
            btc_amount=0.0018,
            price=83333.33,
            ahr999=0.52,
            notes="Automated DCA",
            source="DCA",
            binance_order_id=555666777,
            binance_trade_id=None,
            intended_amount_usd=150.0,
            executed_amount_usd=150.0,
            executed_amount_btc=0.0018,
            avg_execution_price_usd=83333.33
        )
        session.add(dca_tx)
        session.commit()
        
        # 2. Mock Binance to return 3 fills for the same order
        mock_binance_client = AsyncMock()
        mock_binance_client._request.return_value = [
            {
                "id": 11111,
                "orderId": 555666777,  # Same order
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "price": "83333.33",
                "qty": "0.0006",
                "quoteQty": "50.0",
                "commission": "0.013",
                "commissionAsset": "USDC",
                "isBuyer": True
            },
            {
                "id": 22222,
                "orderId": 555666777,  # Same order
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "price": "83333.33",
                "qty": "0.0006",
                "quoteQty": "50.0",
                "commission": "0.013",
                "commissionAsset": "USDC",
                "isBuyer": True
            },
            {
                "id": 33333,
                "orderId": 555666777,  # Same order
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "price": "83333.33",
                "qty": "0.0006",
                "quoteQty": "50.0",
                "commission": "0.014",
                "commissionAsset": "USDC",
                "isBuyer": True
            }
        ]
        mock_binance_client.close = AsyncMock()
        
        # 3. Run sync
        sync_service = TradeSyncService(session)
        
        with patch.object(sync_service, '_get_client', return_value=mock_binance_client):
            added = asyncio.run(sync_service.sync_trades())
        
        # 4. Verify
        # Should add 0 new transactions
        assert added == 0, "Should not create duplicates for multiple fills"
        
        # Verify only 1 transaction exists
        all_txs = session.exec(
            select(DCATransaction).where(DCATransaction.binance_order_id == 555666777)
        ).all()
        assert len(all_txs) == 1, "Should only have 1 transaction for this order"
        
        # Verify first fill is linked
        session.refresh(dca_tx)
        assert dca_tx.binance_trade_id == 11111, "Should link to first fill"
    
    def test_real_manual_trade_imported(self, session: Session):
        """
        Test that genuine manual trades are still imported correctly.
        
        Scenario:
        1. No DCA transaction exists
        2. User manually buys BTC on Binance
        3. Sync runs
        4. Verify: MANUAL transaction is created
        """
        # No DCA transaction created (user did manual trade)
        
        # Mock Binance to return a manual trade
        mock_binance_client = AsyncMock()
        mock_binance_client._request.return_value = [{
            "id": 444555666,
            "orderId": 777888999,  # Order that doesn't exist in our DB
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "price": "85000.00",
            "qty": "0.001",
            "quoteQty": "85.0",
            "commission": "0.02",
            "commissionAsset": "USDC",
            "isBuyer": True
        }]
        mock_binance_client.close = AsyncMock()
        
        # Run sync
        sync_service = TradeSyncService(session)
        
        with patch.object(sync_service, '_get_client', return_value=mock_binance_client):
            added = asyncio.run(sync_service.sync_trades())
        
        # Verify
        assert added == 1, "Should add 1 new MANUAL transaction"
        
        # Verify MANUAL transaction was created
        manual_tx = session.exec(
            select(DCATransaction).where(DCATransaction.binance_order_id == 777888999)
        ).first()
        
        assert manual_tx is not None, "MANUAL transaction should exist"
        assert manual_tx.source == "MANUAL", "Source should be MANUAL"
        assert manual_tx.binance_trade_id == 444555666, "trade_id should be set"
        assert manual_tx.btc_amount == 0.001, "BTC amount should match"
        assert manual_tx.is_manual is True, "is_manual flag should be True"
    
    def test_simulated_transactions_not_in_existing_dca_orders(self, session: Session):
        """
        Test that SIMULATED transactions are not included in existing_dca_orders.
        
        This verifies the fix: existing_dca_orders should only include
        source="DCA" or source="BINANCE", not "SIMULATED".
        """
        # Create a SIMULATED transaction with binance_order_id (shouldn't happen in reality)
        sim_tx = DCATransaction(
            timestamp=datetime.now(timezone.utc),
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=100000.0,
            ahr999=0.6,
            notes="Simulated",
            source="SIMULATED",
            binance_order_id=999000111,  # Hypothetical
            intended_amount_usd=100.0,
            executed_amount_usd=100.0,
            executed_amount_btc=0.001,
            avg_execution_price_usd=100000.0
        )
        session.add(sim_tx)
        session.commit()
        
        # Mock Binance to return a trade with the same order_id
        mock_binance_client = AsyncMock()
        mock_binance_client._request.return_value = [{
            "id": 111222333,
            "orderId": 999000111,  # Same as SIMULATED (shouldn't match in reality)
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "price": "100000.0",
            "qty": "0.001",
            "quoteQty": "100.0",
            "commission": "0.025",
            "commissionAsset": "USDC",
            "isBuyer": True
        }]
        mock_binance_client.close = AsyncMock()
        
        # Run sync
        sync_service = TradeSyncService(session)
        
        with patch.object(sync_service, '_get_client', return_value=mock_binance_client):
            added = asyncio.run(sync_service.sync_trades())
        
        # Verify
        # Should add 1 MANUAL transaction because SIMULATED is not in existing_dca_orders
        assert added == 1, "Should create MANUAL tx because SIMULATED is not in existing_dca_orders"
        
        # Verify both exist
        all_txs = session.exec(
            select(DCATransaction).where(DCATransaction.binance_order_id == 999000111)
        ).all()
        assert len(all_txs) == 2, "Should have both SIMULATED and MANUAL"
        
        sources = {tx.source for tx in all_txs}
        assert sources == {"SIMULATED", "MANUAL"}, "Should have both sources"
