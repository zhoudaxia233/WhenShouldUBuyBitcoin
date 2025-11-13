"""
Metrics calculation module for Bitcoin valuation analysis.

This module provides functions to calculate various metrics:
- 200-day DCA cost (Dollar Cost Averaging)
- Exponential trend fitting (long-term growth model)
"""

import numpy as np
import pandas as pd
from typing import Tuple


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
    Fit an exponential growth model to Bitcoin price history.
    
    Model: price(t) = a * exp(b * t)
    
    Where:
    - t is time in days since the first date
    - a is the initial price coefficient
    - b is the exponential growth rate (per day)
    
    Implementation:
    1. Convert dates to numeric time (days since first date)
    2. Take log of prices: log(price) = log(a) + b*t
    3. Fit linear regression: log_price = α + β*t
    4. Extract parameters: a = exp(α), b = β
    
    Args:
        df: DataFrame with 'date' and price column
        price_col: Name of the price column (default: 'close_price')
        
    Returns:
        Tuple of (trend_series, a, b) where:
        - trend_series: Pandas Series with fitted trend values
        - a: Initial price coefficient
        - b: Exponential growth rate (per day)
        
    Example:
        If b = 0.003, then daily growth rate is ~0.3%
        Annual growth rate ≈ (1 + 0.003)^365 - 1 ≈ 195%
    """
    # Convert dates to numeric: days since first date
    first_date = df["date"].iloc[0]
    df_copy = df.copy()
    df_copy["days_since_start"] = (df_copy["date"] - first_date).dt.days
    
    # Get time (t) and log of price
    t = df_copy["days_since_start"].values
    prices = df_copy[price_col].values
    log_prices = np.log(prices)
    
    # Fit linear regression: log(price) = α + β*t
    # polyfit returns [β, α] (highest degree first)
    coeffs = np.polyfit(t, log_prices, deg=1)
    beta = coeffs[0]  # Slope (growth rate)
    alpha = coeffs[1]  # Intercept
    
    # Extract exponential parameters
    a = np.exp(alpha)  # Initial value coefficient
    b = beta           # Growth rate per day
    
    # Calculate fitted trend values
    trend_values = a * np.exp(b * t)
    trend_series = pd.Series(trend_values, index=df.index, name="trend_value")
    
    return trend_series, a, b


def add_trend_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add exponential trend and related metrics to a DataFrame.
    
    Args:
        df: DataFrame with 'date' and 'close_price' columns
        
    Returns:
        DataFrame with added columns:
            - trend_value: The exponential trend (fair value)
            - ratio_trend: Price / Trend ratio
            - trend_a: Initial coefficient (as attribute)
            - trend_b: Growth rate (as attribute)
    """
    df = df.copy()
    
    # Fit trend and get parameters
    trend_series, a, b = fit_exponential_trend(df, price_col="close_price")
    
    df["trend_value"] = trend_series
    
    # Calculate ratio: price / trend
    # Values > 1 mean price is above trend (potentially overheated)
    # Values < 1 mean price is below trend (potentially undervalued)
    df["ratio_trend"] = df["close_price"] / df["trend_value"]
    
    # Store parameters as attributes for later reference
    df.attrs["trend_a"] = a
    df.attrs["trend_b"] = b
    
    return df


def get_trend_summary(df: pd.DataFrame) -> dict:
    """
    Get summary statistics for exponential trend analysis.
    
    Args:
        df: DataFrame with trend metrics
        
    Returns:
        Dictionary with trend summary statistics
    """
    latest = df.iloc[-1]
    
    # Count how many times price was below trend
    below_trend = (df["ratio_trend"] < 1.0).sum()
    total_days = len(df)
    
    # Get trend parameters
    a = df.attrs.get("trend_a", None)
    b = df.attrs.get("trend_b", None)
    
    # Calculate annualized growth rate from daily rate
    annual_growth_rate = None
    if b is not None:
        annual_growth_rate = (np.exp(b * 365) - 1) * 100  # Percentage
    
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
        "trend_growth_rate_b": b,
        "daily_growth_rate_pct": b * 100 if b else None,
        "annual_growth_rate_pct": annual_growth_rate,
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
    - Exponential trend (long-term valuation)
    - Double undervaluation flag
    
    Args:
        df: DataFrame with 'date' and 'close_price' columns
        dca_window: Window for DCA calculation (default: 200)
        
    Returns:
        DataFrame with all valuation metrics:
            - dca_cost: 200-day DCA cost
            - ratio_dca: Price / DCA ratio
            - trend_value: Exponential trend fair value
            - ratio_trend: Price / Trend ratio
            - is_double_undervalued: Boolean flag for buy zone
    """
    df = df.copy()
    
    # Add DCA metrics
    df = add_dca_metrics(df, window=dca_window)
    
    # Add trend metrics
    df = add_trend_metrics(df)
    
    # Add double undervaluation flag
    # Both conditions must be met:
    # 1. Price < 200-day DCA cost (ratio_dca < 1.0)
    # 2. Price < Exponential trend (ratio_trend < 1.0)
    df["is_double_undervalued"] = (df["ratio_dca"] < 1.0) & (df["ratio_trend"] < 1.0)
    
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

