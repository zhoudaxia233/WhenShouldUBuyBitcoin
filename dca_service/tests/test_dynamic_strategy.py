import pytest
from whenshouldubuybitcoin.strategies.dynamic_ahr999 import (
    calculate_buy_amount,
    DynamicAhr999Params,
    DynamicAhr999Config,
    DynamicAhr999Result
)

@pytest.fixture
def default_config():
    return DynamicAhr999Config(
        base_amount=10.0,
        max_multiplier=10.0,
        min_multiplier=0.0,
        gamma=2.0,
        a_low=0.45,
        a_high=1.0,
        enable_drawdown_boost=True,
        enable_monthly_cap=True,
        monthly_cap=800.0
    )

def test_cheapness_score_logic(default_config):
    """Test that cheapness x is calculated correctly"""
    # Case 1: AHR <= a_low -> x = 1
    params = DynamicAhr999Params(
        ahr999=0.40, # < 0.45
        price=50000,
        peak180=50000,
        month_spent=0,
        config=default_config
    )
    res = calculate_buy_amount(params)
    assert res.cheapness == 1.0
    assert res.multiplier == 10.0 # Max multiplier

    # Case 2: AHR >= a_high -> x = 0
    params.ahr999 = 1.1 # > 1.0
    res = calculate_buy_amount(params)
    assert res.cheapness == 0.0
    assert res.multiplier == 0.0 # Min multiplier

    # Case 3: Middle value
    # x = (1.0 - 0.725) / (1.0 - 0.45) = 0.275 / 0.55 = 0.5
    params.ahr999 = 0.725
    res = calculate_buy_amount(params)
    assert abs(res.cheapness - 0.5) < 0.001
    
    # Multiplier = 0 + (10 - 0) * (0.5 ^ 2) = 10 * 0.25 = 2.5
    assert abs(res.multiplier - 2.5) < 0.001

def test_drawdown_boost(default_config):
    """Test drawdown boost logic"""
    # Setup: AHR such that base multiplier is known
    # AHR = 0.725 -> x=0.5 -> M_base=2.5
    
    # Case 1: No drawdown (DD=0) -> Factor 1.0
    params = DynamicAhr999Params(
        ahr999=0.725,
        price=100000,
        peak180=100000,
        month_spent=0,
        config=default_config
    )
    res = calculate_buy_amount(params)
    assert res.drawdown == 0.0
    assert res.drawdown_factor == 1.0
    assert abs(res.multiplier - 2.5) < 0.001

    # Case 2: 30% Drawdown -> Factor 1.2 (0.20 <= DD < 0.35)
    # Price = 70k, Peak = 100k -> DD = 0.3
    params.price = 70000
    res = calculate_buy_amount(params)
    assert abs(res.drawdown - 0.3) < 0.001
    assert res.drawdown_factor == 1.2
    # M = 2.5 * 1.2 = 3.0
    assert abs(res.multiplier - 3.0) < 0.001

    # Case 3: 60% Drawdown -> Factor 2.0 (DD >= 0.50)
    # Price = 40k, Peak = 100k -> DD = 0.6
    params.price = 40000
    res = calculate_buy_amount(params)
    assert abs(res.drawdown - 0.6) < 0.001
    assert res.drawdown_factor == 2.0
    # M = 2.5 * 2.0 = 5.0
    assert abs(res.multiplier - 5.0) < 0.001

def test_monthly_cap(default_config):
    """Test monthly cap enforcement"""
    # Setup: Multiplier = 2.5, Base = 10 -> Buy = 25
    params = DynamicAhr999Params(
        ahr999=0.725,
        price=100000,
        peak180=100000,
        month_spent=790, # Cap is 800
        config=default_config
    )
    
    # Should be capped at 10 (800 - 790)
    res = calculate_buy_amount(params)
    assert res.capped is True
    assert res.buy == 10.0
    
    # If already over cap
    params.month_spent = 850
    res = calculate_buy_amount(params)
    assert res.capped is True
    assert res.buy == 0.0

def test_max_multiplier_cap(default_config):
    """Test that multiplier is capped at max_multiplier even with boost"""
    # Setup: AHR low -> Base M = 10
    # Drawdown huge -> Factor 2.0
    # Result would be 20, but should clip to 10
    params = DynamicAhr999Params(
        ahr999=0.40,
        price=40000,
        peak180=100000,
        month_spent=0,
        config=default_config
    )
    
    res = calculate_buy_amount(params)
    assert res.multiplier == 10.0
    assert res.drawdown_factor == 2.0
