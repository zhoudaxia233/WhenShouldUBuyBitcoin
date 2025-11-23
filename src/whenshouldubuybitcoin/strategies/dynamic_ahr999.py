"""
Dynamic AHR999-Based DCA Strategy.

This module implements a continuous, non-discrete AHR999 strategy that calculates
buy amounts based on:
1. A continuous AHR999 curve (not buckets)
2. Non-linear multiplier with gamma exponent
3. Optional drawdown-based boost
4. Optional monthly budget cap

Pure deterministic logic, no side effects.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class DynamicAhr999Config:
    base_amount: float = 10.0
    max_multiplier: float = 10.0
    min_multiplier: float = 0.0
    gamma: float = 2.0
    a_low: float = 0.45
    a_high: float = 1.0
    enable_drawdown_boost: bool = True
    enable_monthly_cap: bool = True
    monthly_cap: float = 800.0

DEFAULT_DYNAMIC_AHR999_CONFIG = DynamicAhr999Config()

@dataclass
class DynamicAhr999Params:
    ahr999: float
    price: float
    peak180: float
    month_spent: float
    config: DynamicAhr999Config

@dataclass
class DynamicAhr999Result:
    buy: float
    multiplier: float
    cheapness: float
    drawdown: float
    drawdown_factor: float
    capped: bool

def clamp(value: float, min_val: float, max_val: float) -> float:
    """Helper to clamp a value between min and max."""
    return max(min_val, min(value, max_val))

def calculate_buy_amount(params: DynamicAhr999Params) -> DynamicAhr999Result:
    """
    Calculate the daily buy amount based on the Dynamic AHR999 strategy.
    
    Args:
        params: Input parameters including market data and config
        
    Returns:
        DynamicAhr999Result containing the buy amount and intermediate metrics
    """
    cfg = params.config
    
    # Step 1: Cheapness Score x
    # Map AHR999 into [0, 1]
    # If ahr999 <= a_low, x = 1
    # If ahr999 >= a_high, x = 0
    if params.ahr999 <= cfg.a_low:
        x = 1.0
    elif params.ahr999 >= cfg.a_high:
        x = 0.0
    else:
        x = (cfg.a_high - params.ahr999) / (cfg.a_high - cfg.a_low)
    
    x = clamp(x, 0.0, 1.0)
    
    # Step 2: Base Multiplier M
    # M = min + (max - min) * (x ^ gamma)
    m_base = cfg.min_multiplier + (cfg.max_multiplier - cfg.min_multiplier) * (x ** cfg.gamma)
    
    # Step 3: Drawdown Boost
    # DD = (peak180 - price) / peak180
    if params.peak180 > 0:
        dd = (params.peak180 - params.price) / params.peak180
    else:
        dd = 0.0
        
    # Map DD to boost factor
    if dd < 0.20:
        factor = 1.0
    elif dd < 0.35:
        factor = 1.2
    elif dd < 0.50:
        factor = 1.5
    else: # DD >= 0.50
        factor = 2.0
        
    m_final = m_base
    if cfg.enable_drawdown_boost:
        m_final = m_base * factor
        # Clip to max_multiplier
        m_final = min(m_final, cfg.max_multiplier)
        
    # Step 4: Daily Buy Amount
    buy_today = cfg.base_amount * m_final
    
    # Step 5: Monthly Cap
    capped = False
    if cfg.enable_monthly_cap:
        if (params.month_spent + buy_today) > cfg.monthly_cap:
            buy_today = max(0.0, cfg.monthly_cap - params.month_spent)
            capped = True
            
    return DynamicAhr999Result(
        buy=buy_today,
        multiplier=m_final,
        cheapness=x,
        drawdown=dd,
        drawdown_factor=factor,
        capped=capped
    )
