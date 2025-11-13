"""
Data fetching module for Bitcoin historical price data.

This module provides functions to fetch BTC price history from Yahoo Finance.
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf


def fetch_btc_history(days: int = 2000) -> pd.DataFrame:
    """
    Fetch historical BTC price data from Yahoo Finance.

    Args:
        days: Number of days of historical data to fetch (default: 2000)

    Returns:
        DataFrame with columns:
            - date: datetime object
            - close_price: closing price in USD

    Raises:
        Exception: If data fetching fails
        ValueError: If invalid data is returned
    """
    print(f"Fetching {days} days of BTC price history from Yahoo Finance...")

    try:
        # Calculate start date
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Download BTC-USD data from Yahoo Finance
        btc = yf.Ticker("BTC-USD")
        df = btc.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            interval="1d",
        )

        if df.empty:
            raise ValueError("No price data returned from Yahoo Finance")

        # Reset index to get date as a column
        df = df.reset_index()

        # Rename columns and keep only what we need
        df = df.rename(columns={"Date": "date", "Close": "close_price"})
        df = df[["date", "close_price"]]

        # Ensure date is datetime (without timezone for simplicity)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        # Sort by date ascending
        df = df.sort_values("date").reset_index(drop=True)

        print(f"✓ Successfully fetched {len(df)} days of data")
        print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        print(
            f"  Price range: ${df['close_price'].min():.2f} to ${df['close_price'].max():.2f}"
        )

        return df

    except Exception as e:
        print(f"✗ Error fetching data from Yahoo Finance: {e}")
        raise


def get_latest_btc_price() -> tuple[datetime, float]:
    """
    Get the latest BTC price from Yahoo Finance.

    Returns:
        Tuple of (datetime, price) for the latest available price

    Raises:
        Exception: If data fetching fails
    """
    try:
        btc = yf.Ticker("BTC-USD")

        # Get the most recent data (last 2 days to ensure we get latest)
        df = btc.history(period="2d")

        if df.empty:
            raise ValueError("No price data returned from Yahoo Finance")

        # Get the last row
        latest = df.iloc[-1]
        date = latest.name.to_pydatetime().replace(tzinfo=None)
        price = float(latest["Close"])

        return date, price

    except Exception as e:
        print(f"✗ Error fetching latest price: {e}")
        raise


if __name__ == "__main__":
    # Quick test
    df = fetch_btc_history(days=30)
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nLast 5 rows:")
    print(df.tail())
