"""
Test to ensure that in No Monthly Cap mode, the suggested_amount_usd
is NOT capped by accumulated_savings in the preview/decision.

This test ensures the bug where "No Monthly Cap" mode still showed capped
amounts does not reoccur.
"""
import pytest
from datetime import datetime, timezone
from sqlmodel import Session, create_engine, SQLModel
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision
from unittest.mock import patch


@pytest.fixture
def engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create a database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def strategy_no_cap(session):
    """
    Create a strategy with No Monthly Cap mode.
    - enforce_monthly_cap=False (No Monthly Cap)
    - accumulated_savings=$50 (low savings)
    - total_budget_usd=$500
    - Strategy will calculate suggested amount based on AHR999
    - Uses ahr999_fixed_range strategy for predictable test results
    """
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=500.0,
        enforce_monthly_cap=False,  # No Monthly Cap mode
        accumulated_savings=50.0,  # Low savings to test uncapped behavior
        last_monthly_inflow=datetime.now(timezone.utc),  # Already initialized
        ahr999_multiplier_low=2.0,  # Legacy field (not used in fixed_range)
        ahr999_multiplier_mid=1.0,  # Legacy field (not used in fixed_range)
        ahr999_multiplier_high=0.5,  # Legacy field (not used in fixed_range)
        # Fixed range multipliers: AHR999 0.55 falls in r060 range (0.5-0.6)
        ahr999_multiplier_r045=5.0,  # 0 - 0.45
        ahr999_multiplier_r050=3.0,  # 0.45 - 0.5
        ahr999_multiplier_r060=2.0,  # 0.5 - 0.6 (our test case)
        ahr999_multiplier_r070=1.0,  # 0.6 - 0.7
        ahr999_multiplier_r080=0.5,  # 0.7 - 0.8
        ahr999_multiplier_r090=0.0,  # 0.8 - 0.9
        ahr999_multiplier_r100=0.0,  # 0.9 - 1.0
        ahr999_multiplier_r999=0.0,  # > 1.0
        target_btc_amount=1.0,
        execution_frequency="daily",
        execution_time_utc="00:00",
        strategy_type="ahr999_fixed_range",  # Use fixed range for predictable results
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy


def test_no_monthly_cap_shows_uncapped_amount(session, strategy_no_cap):
    """
    Test that in No Monthly Cap mode, the suggested_amount_usd is NOT capped
    by accumulated_savings.
    
    Scenario:
    - accumulated_savings = $50
    - AHR999 = 0.42 (in "r045" range: < 0.45, 5x multiplier)
    - base_amount = $16.43 (500/30.44 days/month)
    - Strategy suggests: $16.43 × 5.0 = $82.15
    - Expected: suggested_amount_usd should be $82.15 (NOT capped to $50)
    - Expected: can_execute should be False (insufficient savings: $50 < $82.15)
    - Expected: reason should contain WARNING about insufficient savings
    """
    # Mock metrics to return an "extremely cheap" condition (AHR999 = 0.42, r045 range)
    mock_metrics = {
        "ahr999": 0.42,
        "price_usd": 50000.0,
        "peak180": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Historical Data (CSV)",
    }
    
    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
        decision = calculate_dca_decision(session)
    
    # Verify the decision is correct
    assert decision.ahr999_value == 0.42
    assert decision.ahr_band == "r045"  # Fixed range band for < 0.45
    assert decision.multiplier == 5.0
    assert abs(decision.base_amount_usd - 16.43) < 0.01  # 500 / 30.44
    
    # KEY ASSERTION: suggested_amount should be UNCAPPED in No Monthly Cap mode
    # Strategy calculates base_amount × 5.0, should NOT be capped to $50 savings
    # Actual: (500/30.44) × 5.0 ≈ $82.13
    expected_amount = decision.base_amount_usd * 5.0
    assert abs(decision.suggested_amount_usd - expected_amount) < 0.01, \
        f"Expected uncapped amount ${expected_amount:.2f}, got ${decision.suggested_amount_usd:.2f}"
    
    # Most importantly: verify amount is NOT capped to savings
    assert decision.suggested_amount_usd > strategy_no_cap.accumulated_savings, \
        f"Suggested amount (${decision.suggested_amount_usd:.2f}) should exceed savings (${strategy_no_cap.accumulated_savings:.2f})"
    
    # Execution should be blocked due to insufficient savings
    assert decision.can_execute == False, \
        "can_execute should be False when savings are insufficient"
    
    # Reason should contain warning about insufficient savings
    assert "WARNING" in decision.reason, \
        "Reason should contain WARNING about insufficient savings"
    assert "Insufficient savings" in decision.reason, \
        "Reason should mention insufficient savings"
    assert "$50.00" in decision.reason, \
        "Reason should show available savings amount"
    
    # Verify mode indicator is present
    assert "No Monthly Cap" in decision.reason, \
        "Reason should indicate No Monthly Cap mode"
    
    # Verify no capping reason is shown (since we don't cap in this mode)
    assert "Capped by" not in decision.reason, \
        "Reason should NOT contain 'Capped by' in No Monthly Cap mode"
    
    print(f"✓ Test passed: suggested_amount=${decision.suggested_amount_usd:.2f} (uncapped)")
    print(f"✓ Available savings: $50.00")
    print(f"✓ Execution blocked: {not decision.can_execute}")
    print(f"✓ Reason: {decision.reason}")


def test_no_monthly_cap_with_sufficient_savings(session, strategy_no_cap):
    """
    Test that in No Monthly Cap mode with sufficient savings, execution is allowed.
    
    Scenario:
    - accumulated_savings = $100
    - AHR999 = 0.42 (in "r045" range, 5x multiplier)
    - base_amount = $16.43, strategy suggests $82.15
    - Expected: suggested_amount_usd = $82.15 (uncapped)
    - Expected: can_execute = True (sufficient savings)
    """
    # Update strategy to have more savings
    strategy_no_cap.accumulated_savings = 100.0
    session.add(strategy_no_cap)
    session.commit()
    
    # Mock metrics for cheap condition
    mock_metrics = {
        "ahr999": 0.42,
        "price_usd": 50000.0,
        "peak180": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Historical Data (CSV)",
    }
    
    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
        decision = calculate_dca_decision(session)
    
    # Verify uncapped amount
    expected_amount = decision.base_amount_usd * 5.0
    assert abs(decision.suggested_amount_usd - expected_amount) < 0.01, \
        f"Expected uncapped amount ${expected_amount:.2f}, got ${decision.suggested_amount_usd:.2f}"
    
    # Execution should be allowed with sufficient savings
    assert decision.can_execute == True, \
        "can_execute should be True when savings are sufficient"
    
    # No warning should be present
    assert "WARNING" not in decision.reason, \
        "No warning should be present when savings are sufficient"
    
    assert "Insufficient savings" not in decision.reason, \
        "No insufficient savings message when savings are adequate"
    
    print(f"✓ Test passed: suggested_amount=${decision.suggested_amount_usd:.2f} (uncapped)")
    print(f"✓ Available savings: $300.00")
    print(f"✓ Execution allowed: {decision.can_execute}")


def test_enforced_cap_mode_still_caps_correctly(session):
    """
    Verify that Enforced Cap mode (enforce_monthly_cap=True) still applies
    caps correctly - this is a regression test.
    """
    # Create strategy with Enforced Cap mode
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=500.0,
        enforce_monthly_cap=True,  # Enforced Cap mode
        accumulated_savings=50.0,  # Low savings
        last_monthly_inflow=datetime.now(timezone.utc),
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        # Fixed range multipliers for testing
        ahr999_multiplier_r045=5.0,
        ahr999_multiplier_r050=3.0,
        ahr999_multiplier_r060=2.0,
        ahr999_multiplier_r070=1.0,
        ahr999_multiplier_r080=0.5,
        ahr999_multiplier_r090=0.0,
        ahr999_multiplier_r100=0.0,
        ahr999_multiplier_r999=0.0,
        target_btc_amount=1.0,
        execution_frequency="daily",
        execution_time_utc="00:00",
        strategy_type="ahr999_fixed_range",
    )
    session.add(strategy)
    session.commit()
    
    # Mock cheap metrics (would suggest $82.15)
    mock_metrics = {
        "ahr999": 0.42,
        "price_usd": 50000.0,
        "peak180": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Historical Data (CSV)",
    }
    
    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
        decision = calculate_dca_decision(session)
    
    # In Enforced Cap mode, amount SHOULD be capped to available savings
    assert decision.suggested_amount_usd == 50.0, \
        f"In Enforced Cap mode, amount should be capped to $50, got ${decision.suggested_amount_usd:.2f}"
    
    # Should show capping reason
    assert "Capped by" in decision.reason, \
        "Enforced Cap mode should show 'Capped by' in reason"
    
    # Execution should still be allowed (capped to available amount)
    assert decision.can_execute == True, \
        "Enforced Cap mode allows execution with capped amount"
    
    print(f"✓ Enforced Cap mode correctly caps: ${decision.suggested_amount_usd:.2f}")
    print(f"✓ Reason shows capping: {decision.reason}")


def test_no_monthly_cap_zero_savings(session, strategy_no_cap):
    """
    Edge case: No Monthly Cap mode with zero accumulated savings.
    Should show uncapped suggested amount but block execution.
    """
    # Set savings to zero
    strategy_no_cap.accumulated_savings = 0.0
    session.add(strategy_no_cap)
    session.commit()
    
    # Mock cheap metrics
    mock_metrics = {
        "ahr999": 0.42,
        "price_usd": 50000.0,
        "peak180": 50000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "Historical Data (CSV)",
    }
    
    with patch("dca_service.services.dca_engine.get_latest_metrics", return_value=mock_metrics):
        decision = calculate_dca_decision(session)
    
    # Should still show uncapped amount
    expected_amount = decision.base_amount_usd * 5.0
    assert abs(decision.suggested_amount_usd - expected_amount) < 0.01, \
        f"Should show uncapped amount even with $0 savings, got ${decision.suggested_amount_usd:.2f}"
    
    # Execution must be blocked
    assert decision.can_execute == False, \
        "Execution should be blocked with zero savings"
    
    # Should show warning
    assert "WARNING" in decision.reason and "Insufficient savings" in decision.reason, \
        "Should warn about insufficient savings"
    
    print(f"✓ Zero savings edge case handled correctly")
    print(f"✓ Shows uncapped amount: ${decision.suggested_amount_usd:.2f}")
    print(f"✓ Blocks execution: {not decision.can_execute}")

