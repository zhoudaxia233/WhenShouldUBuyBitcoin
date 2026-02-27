"""
Tests for DCA Scheduler

Tests automatic DCA execution logic including:
- Time matching (daily and weekly)
- Frequency checks
- Transaction deduplication (don't execute twice)
- Error handling
"""
import pytest
from datetime import datetime, timezone, timedelta
from freezegun import freeze_time
from unittest.mock import patch
from sqlmodel import Session, select

from dca_service.scheduler import DCAScheduler
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import DCADecision
from dca_service.database import get_session
from dca_service.config import settings


@pytest.fixture
def scheduler():
    """Create a scheduler instance for testing"""
    return DCAScheduler()


@pytest.fixture
def daily_strategy(session: Session):
    """Create a daily DCA strategy for testing"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        target_btc_amount=1.0,
        execution_frequency="daily",
        execution_time_utc="14:30",  # 2:30 PM UTC
        execution_mode="DRY_RUN"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


@pytest.fixture
def weekly_strategy(session: Session):
    """Create a weekly DCA strategy for testing"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        target_btc_amount=1.0,
        execution_frequency="weekly",
        execution_day_of_week="monday",
        execution_time_utc="09:00",  # 9:00 AM UTC on Mondays
        execution_mode="DRY_RUN"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


class TestDailyExecution:
    """Tests for daily DCA execution"""
    
    @freeze_time("2024-01-15 14:30:00")
    def test_should_execute_at_correct_time(self, scheduler, daily_strategy, session):
        """Test that DCA executes at the configured time"""
        assert scheduler._should_execute_now(daily_strategy, session) is True
    
    @freeze_time("2024-01-15 14:29:00")
    def test_should_not_execute_before_time(self, scheduler, daily_strategy, session):
        """Test that DCA doesn't execute before the configured time"""
        assert scheduler._should_execute_now(daily_strategy, session) is False
    
    @freeze_time("2024-01-15 14:31:00")
    def test_should_execute_within_grace_window(self, scheduler, daily_strategy, session):
        """Test that DCA can still execute shortly after the configured minute."""
        assert scheduler._should_execute_now(daily_strategy, session) is True

    @freeze_time("2024-01-15 14:36:00")
    def test_should_not_execute_after_grace_window(self, scheduler, daily_strategy, session):
        """Test that DCA doesn't execute after the grace window."""
        assert scheduler._should_execute_now(daily_strategy, session) is False
    
    @freeze_time("2024-01-15 14:30:00")
    def test_should_not_execute_twice_same_day(self, scheduler, daily_strategy, session):
        """Test that DCA doesn't execute twice on the same day"""
        # Create an existing transaction today
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Existing transaction",
            source="SIMULATED",
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()
        
        assert scheduler._should_execute_now(daily_strategy, session) is False
    
    @freeze_time("2024-01-15 14:30:00")
    def test_should_execute_after_previous_day(self, scheduler, daily_strategy, session):
        """Test that DCA executes today even if there was one yesterday"""
        # Create a transaction from yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Yesterday's transaction",
            source="SIMULATED",
            timestamp=yesterday
        )
        session.add(tx)
        session.commit()
        
        assert scheduler._should_execute_now(daily_strategy, session) is True

    @freeze_time("2024-01-15 14:30:00")
    def test_manual_success_today_does_not_block_auto(self, scheduler, daily_strategy, session):
        """Manual trades should not block scheduled auto execution."""
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Manual transaction",
            source="MANUAL",
            is_manual=True,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()

        assert scheduler._should_execute_now(daily_strategy, session) is True

    @freeze_time("2024-01-15 14:30:00")
    def test_future_success_transaction_does_not_block_today(self, scheduler, daily_strategy, session):
        """Future-dated transactions should not block today's execution."""
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Future transaction",
            source="SIMULATED",
            timestamp=datetime(2024, 1, 16, 0, 0, 0, tzinfo=timezone.utc)
        )
        session.add(tx)
        session.commit()

        assert scheduler._should_execute_now(daily_strategy, session) is True


class TestWeeklyExecution:
    """Tests for weekly DCA execution"""
    
    @freeze_time("2024-01-15 09:00:00")  # Monday
    def test_should_execute_on_correct_day_and_time(self, scheduler, weekly_strategy, session):
        """Test that weekly DCA executes on the correct day and time"""
        assert scheduler._should_execute_now(weekly_strategy, session) is True
    
    @freeze_time("2024-01-16 09:00:00")  # Tuesday
    def test_should_not_execute_on_wrong_day(self, scheduler, weekly_strategy, session):
        """Test that weekly DCA doesn't execute on wrong day"""
        assert scheduler._should_execute_now(weekly_strategy, session) is False
    
    @freeze_time("2024-01-15 08:59:00")  # Monday, wrong time
    def test_should_not_execute_on_wrong_time(self, scheduler, weekly_strategy, session):
        """Test that weekly DCA doesn't execute at wrong time"""
        assert scheduler._should_execute_now(weekly_strategy, session) is False
    
    @freeze_time("2024-01-15 09:00:00")  # Monday
    def test_should_not_execute_twice_same_week(self, scheduler, weekly_strategy, session):
        """Test that weekly DCA doesn't execute twice in the same week"""
        # Create a transaction earlier this week (e.g., today)
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Earlier this week",
            source="SIMULATED",
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()
        
        assert scheduler._should_execute_now(weekly_strategy, session) is False
    
    @freeze_time("2024-01-22 09:00:00")  # Next Monday
    def test_should_execute_next_week(self, scheduler, weekly_strategy, session):
        """Test that weekly DCA executes again next week"""
        # Create a transaction last week
        last_week = datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)  # Previous Monday
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=100.0,
            btc_amount=0.001,
            price=50000.0,
            ahr999=0.5,
            notes="Last week's transaction",
            source="SIMULATED",
            timestamp=last_week
        )
        session.add(tx)
        session.commit()
        
        # Should execute this week
        assert scheduler._should_execute_now(weekly_strategy, session) is True


class TestStrategyConditions:
    """Tests for strategy-level conditions"""
    
    @freeze_time("2024-01-15 14:30:00")
    def test_should_not_execute_if_inactive(self, scheduler, daily_strategy, session):
        """Test that inactive strategies don't execute"""
        daily_strategy.is_active = False
        session.add(daily_strategy)
        session.commit()
        
        # This would normally execute, but strategy is inactive
        assert scheduler._should_execute_now(daily_strategy, session) is False
    
    def test_invalid_time_format(self, scheduler, daily_strategy, session):
        """Test handling of invalid execution_time_utc format"""
        daily_strategy.execution_time_utc = "invalid"
        session.add(daily_strategy)
        session.commit()
        
        # Should return False for invalid time format
        assert scheduler._should_execute_now(daily_strategy, session) is False
    
    def test_unknown_frequency(self, scheduler, daily_strategy, session):
        """Test handling of unknown execution frequency"""
        daily_strategy.execution_frequency = "monthly"  # Not supported
        session.add(daily_strategy)
        session.commit()
        
        now = datetime.now(timezone.utc)
        assert scheduler._should_execute_now(daily_strategy, session) is False

    @freeze_time("2024-01-15 08:15:00+00:00")
    def test_local_time_mode_uses_configured_timezone(self, scheduler, daily_strategy, session, monkeypatch):
        """Test LOCAL mode executes based on configured LOCAL_TIMEZONE (Europe/Berlin)."""
        monkeypatch.setattr(settings, "LOCAL_TIMEZONE", "Europe/Berlin")
        daily_strategy.time_display_mode = "LOCAL"
        daily_strategy.execution_time_utc = "09:15"  # Interpreted as local time in LOCAL mode
        session.add(daily_strategy)
        session.commit()

        # 08:15 UTC == 09:15 Europe/Berlin (CET in January)
        assert scheduler._should_execute_now(daily_strategy, session) is True


class TestExecutionModes:
    """Tests for execution modes (DRY_RUN vs LIVE)"""
    
    @freeze_time("2024-01-15 14:30:00")
    def test_dry_run_creates_simulated_transaction(self, scheduler, daily_strategy, session):
        """Test that DRY_RUN mode creates SIMULATED transactions"""
        # Execute DCA
        scheduler._execute_dca(daily_strategy, session)
        
        # Check transaction was created with SIMULATED source
        tx = session.exec(select(DCATransaction)).first()
        assert tx is not None
        assert tx.source == "SIMULATED"
        assert "Automated daily DCA" in tx.notes
    
    @freeze_time("2024-01-15 14:30:00")
    @patch("dca_service.services.binance_client.BinanceClient")
    @patch("dca_service.services.security.decrypt_text")
    def test_live_mode_creates_binance_transaction(self, mock_decrypt, mock_client_class, scheduler, daily_strategy, session):
        """Test that LIVE mode creates DCA transactions (source changed from BINANCE to DCA)"""
        from unittest.mock import AsyncMock
        
        # Setup mocks
        mock_decrypt.return_value = "secret_key"
        mock_client = mock_client_class.return_value
        mock_client.execute_market_order_with_confirmation = AsyncMock(return_value={
            "order_id": 12345,
            "total_btc": 0.001,
            "avg_price": 50000.0,
            "quote_spent": 50.0,
            "total_fee": 0.0,
            "fee_asset": "USDC"
        })
        mock_client.close = AsyncMock()
        
        # Add BinanceCredentials for LIVE mode
        from dca_service.models import BinanceCredentials
        creds = BinanceCredentials(
            api_key_encrypted="encrypted_key",
            api_secret_encrypted="encrypted_secret",
            credential_type="TRADING"  # Required for LIVE mode
        )
        session.add(creds)
        
        # Change to LIVE mode
        daily_strategy.execution_mode = "LIVE"
        session.add(daily_strategy)
        session.commit()
        
        # Execute DCA
        scheduler._execute_dca(daily_strategy, session)
        
        # Check transaction was created with DCA source (changed from BINANCE)
        tx = session.exec(select(DCATransaction)).first()
        assert tx is not None
        assert tx.source == "DCA"  # Changed from "BINANCE" to "DCA" for bot-triggered trades


class TestStaticGenerationIntegration:
    """Tests for static file generation integration with scheduler"""
    
    @freeze_time("2024-01-15 14:30:00")
    @patch("dca_service.scheduler.calculate_dca_decision")
    @patch("dca_service.services.static_generator.trigger_static_generation")
    def test_static_generation_triggered_after_success(
        self, mock_trigger, mock_calculate_decision, scheduler, daily_strategy, session
    ):
        """Test that static generation is triggered after successful DCA transaction"""
        mock_calculate_decision.return_value = DCADecision(
            can_execute=True,
            reason="Test decision allows execution",
            ahr999_value=0.5,
            ahr_band="low",
            multiplier=2.0,
            base_amount_usd=100.0,
            suggested_amount_usd=200.0,
            price_usd=50000.0,
            timestamp=datetime.now(timezone.utc),
            metrics_source={"backend": "test", "label": "Mock data"},
            remaining_budget=800.0,
            budget_resets=False,
            time_until_reset=None,
        )

        # Execute DCA
        scheduler._execute_dca(daily_strategy, session)
        
        # Verify static generation was triggered
        mock_trigger.assert_called_once_with(background=True)
        
        # Verify transaction was created
        tx = session.exec(select(DCATransaction)).first()
        assert tx is not None
        assert tx.status == "SUCCESS"
    
    @freeze_time("2024-01-15 14:30:00")
    @patch("dca_service.services.dca_engine.get_latest_metrics")
    @patch("dca_service.services.binance_client.BinanceClient")
    @patch("dca_service.services.security.decrypt_text")
    @patch("dca_service.services.static_generator.trigger_static_generation")
    def test_static_generation_not_triggered_on_failure(
        self, mock_trigger, mock_decrypt, mock_client_class, mock_get_metrics, scheduler, daily_strategy, session
    ):
        """Test that static generation is NOT triggered when DCA fails"""
        from unittest.mock import AsyncMock
        
        # Mock metrics to ensure execution can proceed
        mock_get_metrics.return_value = {
            "price_usd": 50000.0,
            "ahr999": 0.5,
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test Data"
        }
        
        # Setup mocks to simulate trading failure
        mock_decrypt.return_value = "secret_key"
        mock_client = mock_client_class.return_value
        mock_client.execute_market_order_with_confirmation = AsyncMock(
            side_effect=Exception("Trading API error")
        )
        mock_client.close = AsyncMock()
        
        # Add credentials for LIVE mode
        from dca_service.models import BinanceCredentials
        creds = BinanceCredentials(
            api_key_encrypted="encrypted_key",
            api_secret_encrypted="encrypted_secret",
            credential_type="TRADING"
        )
        session.add(creds)
        
        # Change to LIVE mode (to trigger the failure path)
        daily_strategy.execution_mode = "LIVE"
        session.add(daily_strategy)
        session.commit()
        
        # Execute DCA (will fail)
        scheduler._execute_dca(daily_strategy, session)
        
        # Verify static generation was NOT triggered
        mock_trigger.assert_not_called()
        
        # Verify failed transaction was created
        tx = session.exec(select(DCATransaction)).first()
        assert tx is not None
        assert tx.status == "FAILED"
    
    @freeze_time("2024-01-15 14:30:00")
    @patch("dca_service.services.static_generator.trigger_static_generation")
    def test_scheduler_continues_on_static_generation_error(
        self, mock_trigger, scheduler, daily_strategy, session
    ):
        """Test that scheduler continues even if static generation fails"""
        # Make static generation raise an error
        mock_trigger.side_effect = Exception("Static generation failed")
        
        # Execute DCA (should complete despite static generation error)
        scheduler._execute_dca(daily_strategy, session)
        
        # Verify transaction was still created successfully
        tx = session.exec(select(DCATransaction)).first()
        assert tx is not None
        assert tx.status == "SUCCESS"
        
        # Verify static generation was attempted
        mock_trigger.assert_called_once()


class TestSchedulerLifecycle:
    """Tests for scheduler start/stop lifecycle"""
    
    def test_scheduler_start(self, scheduler):
        """Test that scheduler starts correctly"""
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()
    
    def test_scheduler_stop(self, scheduler):
        """Test that scheduler stops correctly"""
        scheduler.start()
        scheduler.stop()
        assert scheduler.is_running is False
    
    def test_scheduler_double_start(self, scheduler):
        """Test that starting scheduler twice doesn't cause issues"""
        scheduler.start()
        scheduler.start()  # Should not raise error
        assert scheduler.is_running is True
        scheduler.stop()
    
    def test_scheduler_stop_when_not_running(self, scheduler):
        """Test that stopping non-running scheduler doesn't cause issues"""
        scheduler.stop()  # Should not raise error
        assert scheduler.is_running is False
