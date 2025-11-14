"""
Metrics calculation module for Bitcoin valuation analysis.

This module provides functions to calculate various metrics:
- 200-day DCA cost (Dollar Cost Averaging)
- Power law trend fitting (long-term growth model)
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional


def calculate_dca_cost(prices: pd.Series, window: int = 200) -> pd.Series:
    """
    Calculate the 200-day DCA (Dollar Cost Averaging) cost.
    
    This represents the effective average cost if a user had invested
    a fixed $1 per day over the last 'window' days.
    
    Mathematical explanation:
    - For each day i in the window, buying $1 worth gets you: BTC_i = 1 / P_i
    - Total BTC accumulated over window days: sum(1 / P_i)
    - Total USD invested: window (e.g., 200 USD)
    - DCA cost = Total USD / Total BTC = window / sum(1 / P_i)
    
    This is mathematically equivalent to the harmonic mean of prices,
    which represents the average cost basis when investing fixed dollar amounts.
    
    Note: This is different from arithmetic mean (simple average) or 
    geometric mean. The harmonic mean is always <= geometric mean <= arithmetic mean.
    
    Args:
        prices: Pandas Series of daily prices
        window: Number of days for rolling calculation (default: 200)
        
    Returns:
        Pandas Series of DCA costs, aligned with input index.
        First (window-1) values will be NaN.
        
    Example:
        >>> prices = pd.Series([100, 110, 90, 95, 105])
        >>> dca = calculate_dca_cost(prices, window=3)
        >>> # For index 2: DCA = 3 / (1/100 + 1/110 + 1/90) ≈ 99.17
    """
    # Calculate the reciprocal of prices (BTC per $1)
    btc_per_dollar = 1.0 / prices
    
    # Rolling sum of BTC accumulated (investing $1 per day)
    total_btc_accumulated = btc_per_dollar.rolling(window=window).sum()
    
    # DCA cost = Total USD invested / Total BTC accumulated
    dca_cost = window / total_btc_accumulated
    
    return dca_cost


def add_dca_metrics(df: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    """
    Add DCA cost and related metrics to a DataFrame with price data.
    
    Args:
        df: DataFrame with 'close_price' column
        window: Number of days for DCA calculation (default: 200)
        
    Returns:
        DataFrame with added columns:
            - dca_cost: The 200-day DCA cost
            - ratio_dca: Price / DCA cost ratio
            
    The input DataFrame is not modified; a copy with new columns is returned.
    """
    df = df.copy()
    
    # Calculate DCA cost
    df["dca_cost"] = calculate_dca_cost(df["close_price"], window=window)
    
    # Calculate ratio: price / DCA cost
    # Values > 1 mean price is above DCA cost (potentially overvalued)
    # Values < 1 mean price is below DCA cost (potentially undervalued)
    df["ratio_dca"] = df["close_price"] / df["dca_cost"]
    
    return df


def get_dca_summary(df: pd.DataFrame) -> dict:
    """
    Get summary statistics for DCA analysis.
    
    Args:
        df: DataFrame with 'close_price', 'dca_cost', and 'ratio_dca' columns
        
    Returns:
        Dictionary with summary statistics
    """
    # Filter out NaN values (first 199 days)
    valid_data = df.dropna(subset=["dca_cost"])
    
    if valid_data.empty:
        return {
            "error": "Not enough data for DCA calculation (need at least 200 days)"
        }
    
    latest = valid_data.iloc[-1]
    
    # Count how many times price was below DCA cost
    below_dca = (valid_data["ratio_dca"] < 1.0).sum()
    total_days = len(valid_data)
    
    summary = {
        "total_days_analyzed": total_days,
        "latest_price": latest["close_price"],
        "latest_dca_cost": latest["dca_cost"],
        "latest_ratio": latest["ratio_dca"],
        "latest_status": "Below DCA (Undervalued)" if latest["ratio_dca"] < 1.0 else "Above DCA",
        "days_below_dca": below_dca,
        "pct_days_below_dca": (below_dca / total_days) * 100,
        "min_ratio": valid_data["ratio_dca"].min(),
        "max_ratio": valid_data["ratio_dca"].max(),
        "mean_ratio": valid_data["ratio_dca"].mean(),
    }
    
    return summary


# ============================================================================
# EXPONENTIAL TREND FITTING
# ============================================================================


def fit_exponential_trend(
    df: pd.DataFrame, 
    price_col: str = "close_price"
) -> Tuple[pd.Series, float, float]:
    """
    Fit a power law growth model to Bitcoin price history.
    
    Model: price(t) = a * t^n
    
    Where:
    - t is time in days since the first date
    - a is the scaling coefficient
    - n is the power law exponent (growth rate)
    
    Implementation:
    1. Convert dates to numeric time (days since first date)
    2. Take log of both: log(price) = log(a) + n*log(t)
    3. Fit linear regression: log(price) = α + n*log(t)
    4. Extract parameters: a = exp(α), n = slope
    
    This is more appropriate for Bitcoin than exponential growth because:
    - Power law models network effects (Metcalfe's Law)
    - Growth rate decreases over time (more realistic for mature assets)
    - Widely used in academic research on Bitcoin valuation
    
    Args:
        df: DataFrame with 'date' and price column
        price_col: Name of the price column (default: 'close_price')
        
    Returns:
        Tuple of (trend_series, a, n) where:
        - trend_series: Pandas Series with fitted trend values
        - a: Scaling coefficient
        - n: Power law exponent (typically between 5-6 for Bitcoin)
        
    Example:
        If n = 5.84 (like academic research), price grows as t^5.84
        This means growth rate decreases as Bitcoin matures
    """
    # Convert dates to Bitcoin age (days since genesis block)
    # Bitcoin genesis block: 2009-01-03
    # This is critical for power law model accuracy!
    genesis_date = pd.Timestamp("2009-01-03")
    df_copy = df.copy()
    df_copy["bitcoin_age_days"] = (df_copy["date"] - genesis_date).dt.days
    
    # Get time (t) = Bitcoin age in days
    # Note: This will be a large number (e.g., 2000+ days even for 2014 data)
    # This is correct! Academic research uses Bitcoin age, not data age
    t = df_copy["bitcoin_age_days"].values
    prices = df_copy[price_col].values
    
    # Take log of both time and price for power law fitting
    log_t = np.log(t)
    log_prices = np.log(prices)
    
    # Fit linear regression: log(price) = α + n*log(t)
    # polyfit returns [n, α] (highest degree first)
    coeffs = np.polyfit(log_t, log_prices, deg=1)
    n = coeffs[0]      # Slope (power law exponent)
    alpha = coeffs[1]  # Intercept
    
    # Extract power law parameters
    a = np.exp(alpha)  # Scaling coefficient
    
    # Calculate fitted trend values using power law
    trend_values = a * np.power(t, n)
    trend_series = pd.Series(trend_values, index=df.index, name="trend_value")
    
    return trend_series, a, n


def add_trend_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add power law trend and related metrics to a DataFrame.
    
    Args:
        df: DataFrame with 'date' and 'close_price' columns
        
    Returns:
        DataFrame with added columns:
            - trend_value: The power law trend (fair value)
            - ratio_trend: Price / Trend ratio
            - trend_a: Scaling coefficient (as attribute)
            - trend_b: Power law exponent n (as attribute, name kept for compatibility)
    """
    df = df.copy()
    
    # Fit power law trend and get parameters
    trend_series, a, n = fit_exponential_trend(df, price_col="close_price")
    
    df["trend_value"] = trend_series
    
    # Calculate ratio: price / trend
    # Values > 1 mean price is above trend (potentially overheated)
    # Values < 1 mean price is below trend (potentially undervalued)
    df["ratio_trend"] = df["close_price"] / df["trend_value"]
    
    # Store parameters as attributes for later reference
    # Note: 'trend_b' now represents the power law exponent 'n' (not growth rate)
    df.attrs["trend_a"] = a
    df.attrs["trend_b"] = n  # This is now the power law exponent
    
    return df


def get_trend_summary(df: pd.DataFrame) -> dict:
    """
    Get summary statistics for power law trend analysis.
    
    Args:
        df: DataFrame with trend metrics
        
    Returns:
        Dictionary with trend summary statistics
    """
    latest = df.iloc[-1]
    
    # Count how many times price was below trend
    below_trend = (df["ratio_trend"] < 1.0).sum()
    total_days = len(df)
    
    # Get power law parameters
    a = df.attrs.get("trend_a", None)
    n = df.attrs.get("trend_b", None)  # This is now the power law exponent
    
    # Calculate current growth rate (derivative of power law at current time)
    # For price = a * t^n, growth rate = (n * price) / t
    current_growth_rate_pct = None
    if n is not None and total_days > 0:
        # Growth rate decreases over time in power law model
        current_growth_rate_pct = (n / total_days) * 100
    
    summary = {
        "total_days": total_days,
        "latest_price": latest["close_price"],
        "latest_trend": latest["trend_value"],
        "latest_ratio": latest["ratio_trend"],
        "latest_status": "Below Trend (Undervalued)" if latest["ratio_trend"] < 1.0 else "Above Trend",
        "days_below_trend": below_trend,
        "pct_days_below_trend": (below_trend / total_days) * 100,
        "min_ratio": df["ratio_trend"].min(),
        "max_ratio": df["ratio_trend"].max(),
        "mean_ratio": df["ratio_trend"].mean(),
        "trend_coefficient_a": a,
        "trend_growth_rate_b": n,  # This is now power law exponent (not growth rate)
        "daily_growth_rate_pct": current_growth_rate_pct,  # Current instantaneous growth rate
        "power_law_exponent": n,  # Explicit field for clarity
    }
    
    return summary


# ============================================================================
# AHR999 INDEX
# ============================================================================


def calculate_ahr999(df: pd.DataFrame) -> pd.Series:
    """
    Calculate the ahr999 index.
    
    The ahr999 index is a composite metric that combines two undervaluation signals:
    ahr999 = (Price / DCA) × (Price / Trend)
    
    This is mathematically equivalent to:
    ahr999 = ratio_dca × ratio_trend
    
    Classic thresholds (from Bitcoin community):
    - ahr999 < 0.45: 🔥 Bottom Zone (exceptional buying opportunity)
    - 0.45 ≤ ahr999 < 1.2: 💎 DCA Zone (good for accumulation)
    - ahr999 ≥ 1.2: ⚠️ Watch Zone (potentially overheated)
    
    Why it works:
    - When price is below both DCA and Trend, ahr999 < 1.0
    - The lower the value, the more undervalued Bitcoin is
    - Values < 0.45 historically mark major market bottoms
    
    Args:
        df: DataFrame with ratio_dca and ratio_trend columns
        
    Returns:
        Pandas Series with ahr999 values
        
    Example:
        If ratio_dca = 0.7 and ratio_trend = 0.6, then ahr999 = 0.42
        This is in the bottom zone (< 0.45), a rare buying opportunity
    """
    ahr999 = df["ratio_dca"] * df["ratio_trend"]
    return ahr999


def get_ahr999_zone(ahr999_value: float) -> dict:
    """
    Classify ahr999 value into zones and provide interpretation.
    
    Args:
        ahr999_value: The ahr999 index value
        
    Returns:
        Dictionary with zone classification and interpretation
    """
    if ahr999_value < 0.45:
        return {
            "zone": "bottom",
            "emoji": "🔥",
            "label": "Bottom Zone",
            "description": "Exceptional buying opportunity - historical bottom territory",
            "action": "Strong Buy",
            "color": "#28a745"  # Green
        }
    elif ahr999_value < 1.2:
        return {
            "zone": "dca",
            "emoji": "💎",
            "label": "DCA Zone",
            "description": "Good accumulation zone - suitable for dollar-cost averaging",
            "action": "Accumulate",
            "color": "#0071e3"  # Blue
        }
    else:
        return {
            "zone": "watch",
            "emoji": "⚠️",
            "label": "Watch Zone",
            "description": "Potentially overheated - exercise caution",
            "action": "Wait",
            "color": "#ff9500"  # Orange
        }


def calculate_ahr999_percentile(df: pd.DataFrame, current_ahr999: Optional[float] = None) -> float:
    """
    Calculate the historical percentile of ahr999 value.
    
    This tells you what percentage of historical days had a higher ahr999 value.
    
    Lower percentile = Better buying opportunity
    - 5th percentile: Only 5% of history was cheaper (excellent!)
    - 50th percentile: Median price
    - 95th percentile: Only 5% of history was more expensive
    
    Args:
        df: DataFrame with ahr999 column
        current_ahr999: Specific ahr999 value to check (default: use latest)
        
    Returns:
        Percentile value (0-100)
        
    Example:
        If percentile = 15, it means 85% of historical days had higher ahr999,
        so this is a relatively rare good opportunity (only 15% of days were better)
    """
    valid_data = df.dropna(subset=["ahr999"])
    
    if valid_data.empty:
        return None
    
    if current_ahr999 is None:
        current_ahr999 = valid_data["ahr999"].iloc[-1]
    
    # Calculate percentile using rank
    # Lower ahr999 = better opportunity = lower percentile
    percentile = (valid_data["ahr999"] < current_ahr999).sum() / len(valid_data) * 100
    
    return percentile


def get_ahr999_summary(df: pd.DataFrame) -> dict:
    """
    Get comprehensive summary statistics for ahr999 analysis.
    
    Args:
        df: DataFrame with ahr999 metrics
        
    Returns:
        Dictionary with ahr999 summary statistics and zone analysis
    """
    valid_data = df.dropna(subset=["ahr999"])
    
    if valid_data.empty:
        return {"error": "Not enough data for ahr999 analysis"}
    
    latest = valid_data.iloc[-1]
    latest_ahr999 = latest["ahr999"]
    
    # Calculate zone statistics
    total_days = len(valid_data)
    bottom_zone = (valid_data["ahr999"] < 0.45).sum()
    dca_zone = ((valid_data["ahr999"] >= 0.45) & (valid_data["ahr999"] < 1.2)).sum()
    watch_zone = (valid_data["ahr999"] >= 1.2).sum()
    
    # Get current zone classification
    current_zone = get_ahr999_zone(latest_ahr999)
    
    # Calculate percentile
    percentile = calculate_ahr999_percentile(valid_data, latest_ahr999)
    
    # Historical statistics
    summary = {
        "total_days_analyzed": total_days,
        "current_ahr999": latest_ahr999,
        "current_zone": current_zone,
        "historical_percentile": percentile,
        "days_in_bottom_zone": bottom_zone,
        "days_in_dca_zone": dca_zone,
        "days_in_watch_zone": watch_zone,
        "pct_in_bottom_zone": (bottom_zone / total_days) * 100,
        "pct_in_dca_zone": (dca_zone / total_days) * 100,
        "pct_in_watch_zone": (watch_zone / total_days) * 100,
        "min_ahr999": valid_data["ahr999"].min(),
        "max_ahr999": valid_data["ahr999"].max(),
        "mean_ahr999": valid_data["ahr999"].mean(),
        "median_ahr999": valid_data["ahr999"].median(),
    }
    
    return summary


# ============================================================================
# COMBINED VALUATION METRICS & DOUBLE UNDERVALUATION
# ============================================================================


def compute_valuation_metrics(df: pd.DataFrame, dca_window: int = 200) -> pd.DataFrame:
    """
    Compute all valuation metrics in one function.
    
    This is the main function that combines:
    - 200-day DCA cost (short-term valuation)
    - Power law trend (long-term valuation)
    - Double undervaluation flag
    - ahr999 index (composite metric)
    
    Args:
        df: DataFrame with 'date' and 'close_price' columns
        dca_window: Window for DCA calculation (default: 200)
        
    Returns:
        DataFrame with all valuation metrics:
            - dca_cost: 200-day DCA cost
            - ratio_dca: Price / DCA ratio
            - trend_value: Power law trend fair value
            - ratio_trend: Price / Trend ratio
            - is_double_undervalued: Boolean flag for buy zone
            - ahr999: The ahr999 composite index
    """
    df = df.copy()
    
    # Add DCA metrics
    df = add_dca_metrics(df, window=dca_window)
    
    # Add trend metrics
    df = add_trend_metrics(df)
    
    # Add double undervaluation flag
    # Both conditions must be met:
    # 1. Price < 200-day DCA cost (ratio_dca < 1.0)
    # 2. Price < Power law trend (ratio_trend < 1.0)
    df["is_double_undervalued"] = (df["ratio_dca"] < 1.0) & (df["ratio_trend"] < 1.0)
    
    # Calculate ahr999 index
    df["ahr999"] = calculate_ahr999(df)
    
    return df


def get_double_undervaluation_summary(df: pd.DataFrame) -> dict:
    """
    Get summary statistics for double undervaluation analysis.
    
    Args:
        df: DataFrame with valuation metrics including 'is_double_undervalued'
        
    Returns:
        Dictionary with double undervaluation summary
    """
    # Filter to valid data (where DCA is available)
    valid_data = df.dropna(subset=["dca_cost", "trend_value"])
    
    if valid_data.empty:
        return {"error": "Not enough data for analysis"}
    
    latest = valid_data.iloc[-1]
    
    # Count occurrences of each condition
    total_days = len(valid_data)
    below_dca = (valid_data["ratio_dca"] < 1.0).sum()
    below_trend = (valid_data["ratio_trend"] < 1.0).sum()
    double_undervalued = valid_data["is_double_undervalued"].sum()
    
    # Find all double undervaluation periods
    double_uv_df = valid_data[valid_data["is_double_undervalued"]].copy()
    
    # Calculate statistics about double undervaluation periods
    if len(double_uv_df) > 0:
        # Get date ranges for double undervaluation periods
        # Find contiguous periods
        double_uv_df["date_diff"] = double_uv_df["date"].diff().dt.days
        double_uv_df["new_period"] = double_uv_df["date_diff"] > 1
        double_uv_df["period_id"] = double_uv_df["new_period"].cumsum()
        
        periods = []
        for period_id in double_uv_df["period_id"].unique():
            period_data = double_uv_df[double_uv_df["period_id"] == period_id]
            periods.append({
                "start": period_data["date"].iloc[0],
                "end": period_data["date"].iloc[-1],
                "days": len(period_data),
                "avg_price": period_data["close_price"].mean(),
                "min_price": period_data["close_price"].min(),
            })
        
        last_occurrence = double_uv_df["date"].iloc[-1]
        days_since_last = (valid_data["date"].iloc[-1] - last_occurrence).days
    else:
        periods = []
        last_occurrence = None
        days_since_last = None
    
    summary = {
        "total_days_analyzed": total_days,
        "current_price": latest["close_price"],
        "current_dca": latest["dca_cost"],
        "current_trend": latest["trend_value"],
        "current_ratio_dca": latest["ratio_dca"],
        "current_ratio_trend": latest["ratio_trend"],
        "is_currently_double_undervalued": latest["is_double_undervalued"],
        "days_below_dca": below_dca,
        "days_below_trend": below_trend,
        "days_double_undervalued": double_undervalued,
        "pct_below_dca": (below_dca / total_days) * 100,
        "pct_below_trend": (below_trend / total_days) * 100,
        "pct_double_undervalued": (double_undervalued / total_days) * 100,
        "num_double_uv_periods": len(periods),
        "double_uv_periods": periods,
        "last_double_uv_date": last_occurrence,
        "days_since_last_double_uv": days_since_last,
    }
    
    return summary


if __name__ == "__main__":
    # Quick test with sample data
    dates = pd.date_range("2020-01-01", periods=250, freq="D")
    # Create sample prices with upward trend
    prices = pd.Series(
        10000 + np.cumsum(np.random.randn(250) * 100),
        index=dates,
        name="close_price"
    )
    
    df = pd.DataFrame({"date": dates, "close_price": prices.values})
    df = add_dca_metrics(df, window=200)
    
    print("Sample DCA Calculation:")
    print(df.tail(10))
    print("\nSummary:")
    print(get_dca_summary(df))

