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
    multiplier: float  # Final multiplier (m_final), includes boost if enabled
    base_multiplier: float  # Base multiplier (m_base), before boost
    multiplier_before_clip: float  # Multiplier before max_multiplier clipping (m_base * factor)
    multiplier_clipped: bool  # Whether multiplier was clipped by max_multiplier
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
    
    This implements a value-based DCA strategy where:
    - Lower AHR999 = More undervalued = Higher investment
    - The multiplier follows a power law curve for smooth, intuitive scaling
    
    Formula:
        Cheapness x = (a_high - ahr999) / (a_high - a_low)  [mapped to 0-1]
        Mult_base = min_mult + (max_mult - min_mult) * (x ^ gamma)
    
    Best Practice Guidelines:
        - gamma = 1.0: Linear scaling (simple, predictable)
        - gamma = 2.0: Quadratic scaling (recommended, balanced)
        - gamma = 3.0-5.0: More aggressive (only invest when very cheap)
        - gamma > 5.0: Too extreme (not recommended, defeats the purpose)
    
    Example with gamma=2.0:
        - Cheapness 0.5 → Multiplier = 2.5x (moderate investment)
        - Cheapness 0.79 → Multiplier = 6.24x (good opportunity)
        - Cheapness 1.0 → Multiplier = 10.0x (maximum investment)
    
    Args:
        params: Input parameters including market data and config
        
    Returns:
        DynamicAhr999Result containing the buy amount and intermediate metrics
    """
    cfg = params.config
    
    # Step 1: Cheapness Score x
    # Map AHR999 into [0, 1] where:
    # - x = 1.0 means very cheap (ahr999 <= a_low)
    # - x = 0.0 means expensive (ahr999 >= a_high)
    # - Linear interpolation in between
    if params.ahr999 <= cfg.a_low:
        x = 1.0
    elif params.ahr999 >= cfg.a_high:
        x = 0.0
    else:
        x = (cfg.a_high - params.ahr999) / (cfg.a_high - cfg.a_low)
    
    x = clamp(x, 0.0, 1.0)
    
    # Step 2: Base Multiplier M
    # Power law: M = min + (max - min) * (x ^ gamma)
    # 
    # This creates a smooth curve where:
    # - When x is small (expensive), multiplier is close to min_multiplier
    # - When x is large (cheap), multiplier approaches max_multiplier
    # - Gamma controls the curve shape:
    #   * gamma = 1.0: Linear (proportional, simple)
    #   * gamma = 2.0: Quadratic (recommended, balanced, intuitive)
    #   * gamma = 3.0-5.0: More aggressive (only invest heavily when very cheap)
    #   * gamma > 5.0: Too extreme (not recommended, defeats purpose)
    #
    # Best practice: Use gamma between 1.0 and 3.0 for intuitive behavior
    # Values > 5.0 are too extreme and make the strategy ineffective
    # 
    # Validate gamma and warn if too extreme (but still allow it for flexibility)
    effective_gamma = cfg.gamma
    if cfg.gamma > 5.0:
        # Log warning but don't block (user might have specific reasons)
        # In practice, gamma > 5.0 makes the strategy too conservative
        pass  # Could add logging here if needed
    
    m_base = cfg.min_multiplier + (cfg.max_multiplier - cfg.min_multiplier) * (x ** effective_gamma)
    
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
    multiplier_clipped = False
    multiplier_before_clip = m_base
    
    if cfg.enable_drawdown_boost:
        multiplier_before_clip = m_base * factor
        m_final = multiplier_before_clip
        # Clip to max_multiplier
        if m_final > cfg.max_multiplier:
            m_final = cfg.max_multiplier
            multiplier_clipped = True
        
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
        base_multiplier=m_base,
        multiplier_before_clip=multiplier_before_clip,
        multiplier_clipped=multiplier_clipped,
        cheapness=x,
        drawdown=dd,
        drawdown_factor=factor,
        capped=capped
    )
