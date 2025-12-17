"""
Test suite for enforce_monthly_cap behavior.

This test ensures that the single enforce_monthly_cap field correctly controls:
1. Budget reset behavior (monthly reset vs accumulation)
2. Remaining budget display (value vs N/A)
3. Budget limit enforcement (monthly cap vs savings only)
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision, _check_monthly_inflow


@pytest.fixture(name="session")
def session_fixture():
    """Create in-memory SQLite database for testing"""
    engine = create_engine(
        "sqlite://", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="base_strategy")
def base_strategy_fixture(session):
    """Create base strategy with default settings"""
    strategy = DCAStrategy(
        total_budget_usd=500.0,
        enforce_monthly_cap=True,  # Default: monthly cap enforced
        execution_frequency="daily",
        is_active=True,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        accumulated_savings=0.0,
        last_monthly_inflow=None,
        # Percentile multipliers
        ahr999_multiplier_p10=5.0,
        ahr999_multiplier_p25=2.0,
        ahr999_multiplier_p50=1.0,
        ahr999_multiplier_p75=0.0,
        ahr999_multiplier_p90=0.0,
        ahr999_multiplier_p100=0.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


class TestEnforceMonthlyCapTrue:
    """Tests for enforce_monthly_cap=True (limited mode, budget resets monthly)"""
    
    def test_budget_resets_monthly(self, session, base_strategy):
        """When enforce_monthly_cap=True, budget should reset monthly (not accumulate)"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = True
        strategy.accumulated_savings = 100.0  # Start with some savings
        strategy.last_monthly_inflow = datetime(2025, 1, 15, tzinfo=timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Move to next month
        now = datetime(2025, 2, 1, tzinfo=timezone.utc)
        _check_monthly_inflow(session, strategy, now, month_spent=0.0)
        
        # Budget should RESET to 500 (not accumulate to 100 + 500 = 600)
        assert strategy.accumulated_savings == 500.0
    
    def test_remaining_budget_shows_value(self, session, base_strategy):
        """When enforce_monthly_cap=True, remaining_budget should show a value"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = True
        strategy.accumulated_savings = 500.0
        strategy.last_monthly_inflow = datetime.now(timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Mock metrics
        import dca_service.services.dca_engine as engine_module
        mock_metrics = {
            "price_usd": 50000.0,
            "ahr999": 0.30,  # Low AHR999 -> high multiplier
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test"
        }
        original = engine_module.get_latest_metrics
        engine_module.get_latest_metrics = lambda: mock_metrics
        
        try:
            decision = calculate_dca_decision(session)
            # remaining_budget should be a number, not None
            assert decision.remaining_budget is not None
            assert decision.remaining_budget == 500.0
            assert decision.budget_resets is True
        finally:
            engine_module.get_latest_metrics = original
    
    def test_monthly_limit_enforced(self, session, base_strategy):
        """When enforce_monthly_cap=True, spending should be limited by monthly budget"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = True
        strategy.accumulated_savings = 5000.0  # Lots of savings
        strategy.last_monthly_inflow = datetime.now(timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Already spent $450 this month
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=450.0,
            price=50000,
            ahr999=1.0,
            is_manual=False,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()
        
        # Mock metrics suggesting $83 purchase
        import dca_service.services.dca_engine as engine_module
        mock_metrics = {
            "price_usd": 50000.0,
            "ahr999": 0.30,  # High multiplier ~5x
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test"
        }
        original = engine_module.get_latest_metrics
        engine_module.get_latest_metrics = lambda: mock_metrics
        
        try:
            decision = calculate_dca_decision(session)
            # Should be capped at $50 (monthly remaining: 500 - 450 = 50)
            assert decision.suggested_amount_usd == 50.0
            assert "Capped by Monthly Limit" in decision.reason
        finally:
            engine_module.get_latest_metrics = original


class TestEnforceMonthlyCapFalse:
    """Tests for enforce_monthly_cap=False (unlimited mode, budget accumulates)"""
    
    def test_budget_accumulates_monthly(self, session, base_strategy):
        """When enforce_monthly_cap=False, budget should accumulate (not reset)"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = False
        strategy.accumulated_savings = 200.0  # Start with some savings
        strategy.last_monthly_inflow = datetime(2025, 1, 15, tzinfo=timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Move to next month
        now = datetime(2025, 2, 1, tzinfo=timezone.utc)
        _check_monthly_inflow(session, strategy, now, month_spent=0.0)
        
        # Budget should ACCUMULATE (200 + 500 = 700)
        assert strategy.accumulated_savings == 700.0
    
    def test_multi_month_accumulation(self, session, base_strategy):
        """When enforce_monthly_cap=False, missed months should accumulate"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = False
        strategy.accumulated_savings = 50.0
        strategy.last_monthly_inflow = datetime(2025, 1, 15, tzinfo=timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Skip 3 months to April
        now = datetime(2025, 4, 10, tzinfo=timezone.utc)
        _check_monthly_inflow(session, strategy, now, month_spent=0.0)
        
        # Should accumulate: 50 + (3 * 500) = 1550
        # months_diff = 3 (Feb, Mar, Apr)
        assert strategy.accumulated_savings == 1550.0
    
    def test_remaining_budget_is_none(self, session, base_strategy):
        """When enforce_monthly_cap=False, remaining_budget should be None (display as N/A)"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = False
        strategy.accumulated_savings = 1000.0
        strategy.last_monthly_inflow = datetime.now(timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Mock metrics
        import dca_service.services.dca_engine as engine_module
        mock_metrics = {
            "price_usd": 50000.0,
            "ahr999": 0.30,
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test"
        }
        original = engine_module.get_latest_metrics
        engine_module.get_latest_metrics = lambda: mock_metrics
        
        try:
            decision = calculate_dca_decision(session)
            # remaining_budget should be None (will display as N/A)
            assert decision.remaining_budget is None
            assert decision.budget_resets is False
        finally:
            engine_module.get_latest_metrics = original
    
    def test_no_monthly_limit_only_savings(self, session, base_strategy):
        """When enforce_monthly_cap=False, only savings limit applies (not monthly budget)"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = False
        strategy.accumulated_savings = 100.0  # Limited savings
        strategy.last_monthly_inflow = datetime.now(timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Already spent $500 this month (over monthly budget)
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=500.0,
            price=50000,
            ahr999=1.0,
            is_manual=False,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()
        
        # Mock metrics suggesting $83 purchase
        import dca_service.services.dca_engine as engine_module
        mock_metrics = {
            "price_usd": 50000.0,
            "ahr999": 0.30,
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test"
        }
        original = engine_module.get_latest_metrics
        engine_module.get_latest_metrics = lambda: mock_metrics
        
        try:
            decision = calculate_dca_decision(session)
            # Should be limited by savings ($100), not monthly budget
            # Monthly remaining would be negative (500 - 500 = 0)
            # But savings is 100, so should suggest full amount (if < 100)
            assert decision.can_execute is True
            assert decision.suggested_amount_usd <= 100.0
            assert "No Monthly Cap" in decision.reason
            # Should NOT mention "Capped by Monthly Limit"
            assert "Capped by Monthly Limit" not in decision.reason
        finally:
            engine_module.get_latest_metrics = original
    
    def test_can_spend_over_monthly_budget(self, session, base_strategy):
        """When enforce_monthly_cap=False, can spend over monthly budget if savings available"""
        strategy = base_strategy
        strategy.enforce_monthly_cap = False
        strategy.accumulated_savings = 2000.0  # Plenty of savings
        strategy.last_monthly_inflow = datetime.now(timezone.utc)
        session.add(strategy)
        session.commit()
        
        # Already spent $600 this month (over $500 monthly budget)
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=600.0,
            price=50000,
            ahr999=1.0,
            is_manual=False,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx)
        session.commit()
        
        # Mock metrics
        import dca_service.services.dca_engine as engine_module
        mock_metrics = {
            "price_usd": 50000.0,
            "ahr999": 0.30,  # High multiplier
            "peak180": 50000.0,
            "source": "test",
            "source_label": "Test"
        }
        original = engine_module.get_latest_metrics
        engine_module.get_latest_metrics = lambda: mock_metrics
        
        try:
            decision = calculate_dca_decision(session)
            # Should allow purchase despite being over monthly budget
            assert decision.can_execute is True
            # Should suggest full amount (not capped by monthly limit)
            assert decision.suggested_amount_usd > 50.0  # More than what would remain
            assert "No Monthly Cap" in decision.reason
        finally:
            engine_module.get_latest_metrics = original


class TestMigrationCompatibility:
    """Tests to ensure the change is backward compatible"""
    
    def test_strategy_without_field_defaults_correctly(self, session):
        """Ensure strategies created without the old field work correctly"""
        # This tests that the model works without unlimited_monthly_budget field
        strategy = DCAStrategy(
            total_budget_usd=500.0,
            enforce_monthly_cap=True,
            execution_frequency="daily",
            is_active=True,
            ahr999_multiplier_low=5.0,
            ahr999_multiplier_mid=2.0,
            ahr999_multiplier_high=0.0,
            accumulated_savings=500.0,
            last_monthly_inflow=datetime.now(timezone.utc),
            ahr999_multiplier_p10=5.0,
            ahr999_multiplier_p25=2.0,
            ahr999_multiplier_p50=1.0,
            ahr999_multiplier_p75=0.0,
            ahr999_multiplier_p90=0.0,
            ahr999_multiplier_p100=0.0
        )
        session.add(strategy)
        session.commit()
        
        # Should not raise any errors
        assert strategy.enforce_monthly_cap is True
        assert not hasattr(strategy, 'unlimited_monthly_budget')

