
import pytest
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision, _check_monthly_inflow

# Use in-memory SQLite for testing
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="strategy")
def strategy_fixture(session):
    strategy = DCAStrategy(
        total_budget_usd=500.0,
        enforce_monthly_cap=True,
        execution_frequency="daily",
        is_active=True,
        ahr999_multiplier_low=5.0,  # Legacy
        ahr999_multiplier_mid=2.0,  # Legacy
        ahr999_multiplier_high=0.0, # Legacy (Strategy requires these)
        
        # Savings and inflow tracking
        accumulated_savings=0.0,
        last_monthly_inflow=None,
        
        # AHR999 Percentile Defaults (Ensure non-None for logic)
        ahr999_multiplier_p10=5.0,
        ahr999_multiplier_p25=2.0,
        ahr999_multiplier_p50=1.0, # Should buy normally
        ahr999_multiplier_p75=0.0,
        ahr999_multiplier_p90=0.0,
        ahr999_multiplier_p100=0.0
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy

def test_initial_savings_setup(session, strategy):
    """Test that savings initialize to remaining monthly budget on first run."""
    # Assuming user spent 0 so far this month
    now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    month_spent = 0.0
    
    _check_monthly_inflow(session, strategy, now, month_spent)
    
    assert strategy.accumulated_savings == 500.0
    
    # Normalize retrieved datetime
    retrieved = strategy.last_monthly_inflow
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    assert retrieved == now
    
    # Run again immediately - no change
    strategy.accumulated_savings = 500.0 # Reset just in case logic changed
    _check_monthly_inflow(session, strategy, now + timedelta(hours=1), month_spent)
    assert strategy.accumulated_savings == 500.0

def test_initial_savings_setup_partial_spend(session, strategy):
    """Test initialization when user already spent money this month."""
    now = datetime(2025, 1, 15, tzinfo=timezone.utc)
    month_spent = 200.0
    
    _check_monthly_inflow(session, strategy, now, month_spent)
    
    # Should only credit remaining: 500 - 200 = 300
    assert strategy.accumulated_savings == 300.0

def test_monthly_accumulation(session, strategy):
    """Test monthly budget accumulation in Limited vs No-Cap mode."""
    strategy.total_budget_usd = 500.0
    strategy.accumulated_savings = 0.0
    strategy.enforce_monthly_cap = True  # Limited mode (cap enforced)
    strategy.last_monthly_inflow = datetime(2025, 1, 1, tzinfo=timezone.utc)
    session.add(strategy)
    session.commit()
    
    # Simulate time passing to next month (Feb 1st)
    now = datetime(2025, 2, 1, tzinfo=timezone.utc)
    month_spent = 0.0  # Haven't spent anything yet this month
    
    _check_monthly_inflow(session, strategy, now, month_spent)
    
    # In Limited mode, budget should RESET to 500 (not accumulate to 500+500)
    assert strategy.accumulated_savings == 500.0
    
    # Verify timestamp updated
    retrieved = strategy.last_monthly_inflow
    if retrieved.tzinfo is None:
        retrieved = retrieved.replace(tzinfo=timezone.utc)
    assert retrieved == now
    
    # Test No-Cap mode (enforce_monthly_cap=False)
    strategy.enforce_monthly_cap = False
    strategy.accumulated_savings = 200.0  # Start with some savings
    strategy.last_monthly_inflow = datetime(2025, 2, 1, tzinfo=timezone.utc)
    session.add(strategy)
    session.commit()
    
    # Move to March
    now = datetime(2025, 3, 1, tzinfo=timezone.utc)
    _check_monthly_inflow(session, strategy, now, month_spent)
    
    # In No-Cap mode, budget should ACCUMULATE (200 + 500 = 700)
    assert strategy.accumulated_savings == 700.0

def test_multi_month_accumulation(session, strategy):
    """Test budget behavior when bot is offline for multiple months."""
    # Test Limited mode (enforce_monthly_cap=True): Should only reset to current month's budget
    strategy.enforce_monthly_cap = True
    strategy.last_monthly_inflow = datetime(2025, 1, 15, tzinfo=timezone.utc)
    strategy.accumulated_savings = 50.0
    session.add(strategy)
    session.commit()
    
    # Bot offline for 3 months, now it's April
    now = datetime(2025, 4, 10, tzinfo=timezone.utc)
    
    _check_monthly_inflow(session, strategy, now, 0.0)
    
    # In Limited mode: Budget should reset to 500 (not add 3*500)
    # Even though 3 months passed, unspent budget doesn't accumulate
    assert strategy.accumulated_savings == 500.0
    
    # Test No-Cap mode (enforce_monthly_cap=False): Should accumulate all missed months
    strategy.enforce_monthly_cap = False
    strategy.last_monthly_inflow = datetime(2025, 4, 15, tzinfo=timezone.utc)
    strategy.accumulated_savings = 50.0
    session.add(strategy)
    session.commit()
    
    # Move forward 3 months to July
    now = datetime(2025, 7, 10, tzinfo=timezone.utc)
    _check_monthly_inflow(session, strategy, now, 0.0)
    
    # In No-Cap mode: Should add 3 * 500 = 1500
    # months_diff: (7-4) = 3 (May, Jun, Jul)
    assert strategy.accumulated_savings == 1550.0  # 50 + (3 * 500)
    
def test_limited_budget_cap(session, strategy):
    """Test strict monthly cap enforcement."""
    # Setup: Lots of savings, but monthly cap applies
    strategy.accumulated_savings = 5000.0 
    strategy.enforce_monthly_cap = True  # Enforce monthly cap
    strategy.last_monthly_inflow = datetime.now(timezone.utc)
    session.add(strategy)
    session.commit()
    
    # Already spent 400 this month. Cap = 500. Remaining = 100.
    # We create a dummy transaction to simulate spending in DB?
    # No, calculation uses query. Instead, we can't easily mock `calculate_dca_decision` internal query
    # unless we patch `month_spent_txs`.
    # BUT `calculate_dca_decision` calculates `month_spent`.
    # We can inject transactions into DB.
    
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=400.0, # Spent 400
        executed_amount_usd=400.0,
        price=50000,
        ahr999=1.0,
        is_manual=False,
        timestamp=datetime.now(timezone.utc) # Today
    )
    session.add(tx1)
    session.commit()
    
    # Mock metrics needed for `calculate_dca_decision`
    # We need to patch `get_latest_metrics`
    import dca_service.services.dca_engine as engine_module
    
    # Mock return value
    mock_metrics = {
        "price_usd": 50000.0,
        "ahr999": 0.30, # Low -> High multiplier (e.g. 2x or 5x)
        # 0.30 < p10 (likely < 0.45). So multiplier = 5.0 (p10).
        # Base amount = 500/30 = 16.6.
        # Suggested = 16.6 * 5 = 83.3.
        # 83.3 < 100 (Remaining). So should buy full 83.3.
        "peak180": 50000.0
    }
    
    # We need to temporarily set the mock
    original_get_metrics = engine_module.get_latest_metrics
    engine_module.get_latest_metrics = lambda **_: mock_metrics
    
    try:
        decision = calculate_dca_decision(session)
        assert decision.can_execute is True
        # Check amount. 
        # Cap = 100. Suggested ~83. 
        # Should be ~83.
        assert 80.0 < decision.suggested_amount_usd < 90.0
        
        # Now spend more so remaining is only $10.
        tx2 = DCATransaction(
            status="SUCCESS",
            fiat_amount=90.0, 
            price=50000,
            ahr999=1.0,
            is_manual=False,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(tx2)
        session.commit()
        
        # Total Spent = 490. Remaining = 10.
        # Suggested ~83. 
        # Should be capped at 10.
        decision = calculate_dca_decision(session)
        assert decision.can_execute is True
        assert decision.suggested_amount_usd == 10.0
        assert "Capped by Monthly Limit" in decision.reason or "Capped by Monthly Limit" in str(decision)
        
    finally:
        engine_module.get_latest_metrics = original_get_metrics

def test_unlimited_budget_spending(session, strategy):
    """Test spending from savings in no-cap mode (enforce_monthly_cap=False)."""
    strategy.accumulated_savings = 5000.0 
    strategy.enforce_monthly_cap = False  # No monthly cap, can spend accumulated savings
    strategy.last_monthly_inflow = datetime.now(timezone.utc) # Prevent initialization overwrite
    session.add(strategy)
    session.commit()

    # Spent 500 already (Full budget).
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=500.0,
        executed_amount_usd=500.0,
        price=50000,
        ahr999=1.0,
        is_manual=False,
        timestamp=datetime.now(timezone.utc)
    )
    session.add(tx1)
    session.commit()
    
    import dca_service.services.dca_engine as engine_module
    mock_metrics = {
        "price_usd": 50000.0,
        "ahr999": 0.30, # Multiplier ~5x -> $83
        "peak180": 50000.0
    }
    original_get_metrics = engine_module.get_latest_metrics
    engine_module.get_latest_metrics = lambda **_: mock_metrics
    
    try:
        # Should allow spending despite monthly cap being hit
        decision = calculate_dca_decision(session)
        assert decision.can_execute is True
        # Should not be capped to 0. Should be full amount ~83.
        assert decision.suggested_amount_usd > 80.0
        assert "No Monthly Cap" in decision.reason
        
    finally:
        engine_module.get_latest_metrics = original_get_metrics
