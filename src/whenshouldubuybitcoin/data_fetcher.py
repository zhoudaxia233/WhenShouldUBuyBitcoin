"""
Data fetching module for Bitcoin historical price data.

This module provides functions to fetch BTC price history from Yahoo Finance.
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

try:
    import requests
except ImportError:
    requests = None


def fetch_btc_history(
    days: Optional[int] = None, start_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetch historical BTC price data from Yahoo Finance.

    Args:
        days: Number of days of historical data to fetch (default: None = all available)
        start_date: Specific start date in 'YYYY-MM-DD' format (overrides days)

    Returns:
        DataFrame with columns:
            - date: datetime object
            - close_price: closing price in USD

    Raises:
        Exception: If data fetching fails
        ValueError: If invalid data is returned

    Note:
        Yahoo Finance has BTC-USD data from 2014-09-17 onwards (~4000+ days).
        For power law model accuracy, using all available data is recommended.
    """
    btc = yf.Ticker("BTC-USD")
    end_date = datetime.now()

    try:
        if start_date:
            # Use specific start date
            print(f"Fetching BTC price history from {start_date}...")
            df = btc.history(
                start=start_date,
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )
        elif days:
            # Use number of days
            print(f"Fetching {days} days of BTC price history from Yahoo Finance...")
            calc_start = end_date - timedelta(days=days)
            df = btc.history(
                start=calc_start.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )
        else:
            # Fetch all available data (from earliest Yahoo Finance has)
            print(f"Fetching ALL available BTC price history from Yahoo Finance...")
            # Yahoo Finance has data from 2014-09-17
            df = btc.history(
                start="2014-09-17",
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


def get_realtime_btc_price() -> tuple[datetime, float]:
    """
    Get the current real-time BTC price.
    
    Priority: Binance -> Coinbase
    Yahoo Finance is only used for historical data analysis.

    Returns:
        Tuple of (datetime, price) for the current price

    Raises:
        Exception: If data fetching fails from all sources
    """
    if requests is None:
        raise ImportError("requests library is required for real-time price fetching. Install it with: pip install requests")
    
    def validate_price(price: float) -> bool:
        """Validate price is within reasonable range"""
        return 1000 < price < 200000
    
    # Try Binance first
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        if data and "price" in data:
            price = float(data["price"])
            if validate_price(price):
                print(f"✓ Fetched real-time price from Binance: ${price:,.2f}")
                return datetime.now(), price
    except Exception as e:
        print(f"⚠ Binance API error: {e}")
    
    # Fallback to Coinbase
    try:
        response = requests.get(
            "https://api.coinbase.com/v2/exchange-rates?currency=BTC",
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        if data and "data" in data and "rates" in data["data"] and "USD" in data["data"]["rates"]:
            price = float(data["data"]["rates"]["USD"])
            if validate_price(price):
                print(f"✓ Fetched real-time price from Coinbase: ${price:,.2f}")
                return datetime.now(), price
    except Exception as e:
        print(f"⚠ Coinbase API error: {e}")
    
    # All sources failed
    raise Exception("Failed to fetch real-time price from Binance and Coinbase")


if __name__ == "__main__":
    # Quick test
    df = fetch_btc_history(days=30)
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nLast 5 rows:")
    print(df.tail())
