"""
Data fetching module for Bitcoin historical price data.

This module provides functions to fetch BTC price history from Yahoo Finance,
USD/JPY exchange rate data, and interest rate data from FRED API and Yahoo Finance.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

try:
    import requests
except ImportError:
    requests = None

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


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


def fetch_usdjpy_history(
    days: Optional[int] = None, start_date: Optional[str] = None
) -> pd.DataFrame:
    """
    Fetch historical USD/JPY exchange rate data from Yahoo Finance.

    Args:
        days: Number of days of historical data to fetch (default: None = all available)
        start_date: Specific start date in 'YYYY-MM-DD' format (overrides days)

    Returns:
        DataFrame with columns:
            - date: datetime object
            - close_price: closing exchange rate (USD/JPY)

    Raises:
        Exception: If data fetching fails
        ValueError: If invalid data is returned

    Note:
        Yahoo Finance has USDJPY=X data from 1971-01-04 onwards.
    """
    usdjpy = yf.Ticker("USDJPY=X")
    end_date = datetime.now()

    try:
        if start_date:
            # Use specific start date
            print(f"Fetching USD/JPY history from {start_date}...")
            df = usdjpy.history(
                start=start_date,
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )
        elif days:
            # Use number of days
            print(f"Fetching {days} days of USD/JPY history from Yahoo Finance...")
            calc_start = end_date - timedelta(days=days)
            df = usdjpy.history(
                start=calc_start.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )
        else:
            # Fetch all available data (from earliest Yahoo Finance has)
            print(f"Fetching ALL available USD/JPY history from Yahoo Finance...")
            # Fetch from 2000-01-01 for reasonable amount of data
            df = usdjpy.history(
                start="2000-01-01",
                end=end_date.strftime("%Y-%m-%d"),
                interval="1d",
            )

        if df.empty:
            raise ValueError("No USD/JPY data returned from Yahoo Finance")

        # Reset index to get date as a column
        df = df.reset_index()

        # Rename columns and keep only what we need
        df = df.rename(columns={"Date": "date", "Close": "close_price"})
        df = df[["date", "close_price"]]

        # Ensure date is datetime (without timezone for simplicity)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        # Sort by date ascending
        df = df.sort_values("date").reset_index(drop=True)

        print(f"✓ Successfully fetched {len(df)} days of USD/JPY data")
        print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        print(
            f"  Rate range: {df['close_price'].min():.2f} to {df['close_price'].max():.2f}"
        )

        return df

    except Exception as e:
        print(f"✗ Error fetching USD/JPY data from Yahoo Finance: {e}")
        raise


def fetch_fred_series(
    series_id: str,
    days: Optional[int] = None,
    start_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch data from FRED (Federal Reserve Economic Data) API.

    Args:
        series_id: FRED series ID (e.g., 'DGS2' for US 2-year yield)
        days: Number of days of historical data to fetch (default: None = all available)
        start_date: Specific start date in 'YYYY-MM-DD' format (overrides days)

    Returns:
        DataFrame with columns:
            - date: datetime object
            - close_price: series value

    Raises:
        Exception: If data fetching fails
    """
    if requests is None:
        raise ImportError(
            "requests library is required for FRED data fetching. Install it with: pip install requests"
        )

    # Get API key from environment variable
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise ValueError(
            "FRED_API_KEY not found in environment variables. "
            "Please set it in .env file or as an environment variable."
        )

    end_date = datetime.now()
    
    if start_date:
        start_str = start_date
    elif days:
        calc_start = end_date - timedelta(days=days)
        start_str = calc_start.strftime("%Y-%m-%d")
    else:
        # Default to 10 years of data
        calc_start = end_date - timedelta(days=3650)
        start_str = calc_start.strftime("%Y-%m-%d")
    
    end_str = end_date.strftime("%Y-%m-%d")
    
    # FRED API endpoint
    url = f"https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_str,
        "observation_end": end_str,
        "frequency": "d",  # Daily
        "units": "lin",  # Linear (not transformed)
    }

    try:
        print(f"Fetching {series_id} from FRED from {start_str} to {end_str}...")
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "observations" not in data:
            raise ValueError(f"No observations returned from FRED for {series_id}")

        # Convert to DataFrame
        observations = data["observations"]
        df = pd.DataFrame(observations)

        if df.empty:
            raise ValueError(f"Empty data returned from FRED for {series_id}")

        # Convert date and value columns
        df["date"] = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        # Remove rows with missing values
        df = df.dropna(subset=["value"])

        # Keep only date and value
        df = df[["date", "value"]].rename(columns={"value": "close_price"})

        # Remove timezone
        df["date"] = df["date"].dt.tz_localize(None)

        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)

        print(f"✓ Successfully fetched {len(df)} days of {series_id} data")
        print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        print(f"  Value range: {df['close_price'].min():.2f} to {df['close_price'].max():.2f}")

        return df

    except Exception as e:
        print(f"✗ Error fetching {series_id} from FRED: {e}")
        raise


def fetch_mof_japan_yield() -> pd.DataFrame:
    """
    Fetch historical and current Japan 2-year government bond yields from Ministry of Finance Japan.
    
    Returns:
        DataFrame with 'date' and 'jp_2y' columns.
    """
    try:
        print("\nFetching Japan 2Y yield data from Ministry of Finance (MOF)...")
        
        # URLs for MOF data
        # Historical data (1974-present)
        hist_url = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
        # Current month data (sometimes newer than historical file)
        curr_url = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
        
        dfs = []
        for url in [hist_url, curr_url]:
            try:
                # Read CSV, skipping the first row (header title)
                # The actual header is on the second row (index 1)
                response = requests.get(url)
                response.raise_for_status()
                
                # Use io.StringIO to parse the text content
                import io
                # Skip the first line which is just a title
                content = response.text.split('\n', 1)[1]
                df = pd.read_csv(io.StringIO(content))
                
                # Clean up column names
                df.columns = [c.strip() for c in df.columns]
                
                # Check if '2Y' column exists
                if '2Y' in df.columns and 'Date' in df.columns:
                    # Convert Date to datetime
                    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                    
                    # Convert 2Y to numeric, handling '-' or other non-numeric values
                    df['2Y'] = pd.to_numeric(df['2Y'], errors='coerce')
                    
                    # Rename columns
                    df = df.rename(columns={'Date': 'date', '2Y': 'jp_2y'})
                    
                    # Filter valid data
                    df = df.dropna(subset=['date', 'jp_2y'])
                    dfs.append(df[['date', 'jp_2y']])
            except Exception as e:
                print(f"⚠ Warning fetching MOF URL {url}: {e}")
                
        if not dfs:
            raise ValueError("No valid data fetched from MOF")
            
        # Combine and deduplicate
        full_df = pd.concat(dfs).drop_duplicates(subset=['date']).sort_values('date')
        
        print(f"✓ Fetched {len(full_df)} data points from MOF")
        print(f"  Range: {full_df['date'].min().date()} to {full_df['date'].max().date()}")
        print(f"  Latest 2Y Yield: {full_df['jp_2y'].iloc[-1]}%")
        
        return full_df
        
    except Exception as e:
        print(f"⚠ Failed to fetch MOF data: {e}")
        return pd.DataFrame(columns=['date', 'jp_2y'])

# Constant for Japan 2Y yield estimate (used as last resort fallback)
# Updated Nov 2025 based on market data
JAPAN_2Y_ESTIMATE = 0.93

def fetch_yield_data(
    days: Optional[int] = None, start_date: Optional[str] = None
) -> tuple[pd.DataFrame, str]:
    """
    Fetch US and Japan 2-year yield data and calculate the spread.

    Pipeline:
    1. US Data: Try FRED API (Series: DGS2).
       - If FRED fails, fall back to Yahoo Finance (US 5Y proxy).
    2. Japan Data:
       - Try FRED API (Series: IR2TTS01JPM156N) -> Currently known to fail (400 Bad Request).
       - Catch Error -> Try Ministry of Finance (MOF) CSVs (Official Source).
       - Catch Error -> Fall back to static estimate (Yahoo Finance fallback logic).

    Args:
        days: Number of days of historical data to fetch
        start_date: Specific start date in 'YYYY-MM-DD' format

    Returns:
        Tuple of:
            - DataFrame with columns: date, us_2y, jp_2y, spread
            - Source string ("FRED" or "Yahoo Finance")
    """
    # Try FRED API first for US data
    try:
        print("\nAttempting to fetch yield data from FRED API...")
        
        print("Fetching US 2-year yield (DGS2) from FRED...")
        us_2y_df = fetch_fred_series("DGS2", days=days, start_date=start_date)
        
        jp_2y_df = None
        data_source_str = "FRED"
        
        # Try fetching Japan data
        try:
            # 1. Try FRED (Legacy/Preferred if working)
            # print("Fetching Japan 2-year yield (IR2TTS01JPM156N) from FRED...")
            # jp_2y_df = fetch_fred_series("IR2TTS01JPM156N", days=days, start_date=start_date)
            # FRED is currently broken for this series, skipping directly to MOF to save time/logs
            raise Exception("FRED series IR2TTS01JPM156N is deprecated/broken")

        except Exception:
            try:
                # 2. Try MOF (Official Source)
                jp_2y_df = fetch_mof_japan_yield()
                
                if not jp_2y_df.empty:
                    data_source_str = "FRED (US) / MOF (JP)"
                    jp_2y_df["close_price"] = jp_2y_df["jp_2y"] 
                else:
                    raise ValueError("Empty MOF data")
                    
            except Exception as e:
                print(f"⚠ Could not fetch Japan 2Y from MOF: {e}")
                print("Falling back to Yahoo Finance for Japan data...")
                # 3. Fallback to Estimate
                print(f"Using estimated Japan 2Y yield ({JAPAN_2Y_ESTIMATE}%) as Yahoo Finance fallback...")
                
                # Create dummy dataframe for Japan yield matching US dates
                jp_2y_df = us_2y_df.copy()
                jp_2y_df["close_price"] = JAPAN_2Y_ESTIMATE
                data_source_str = "FRED (US) / Yahoo (JP)"
        
        # Merge on date
        merged = pd.merge(
            us_2y_df,
            jp_2y_df,
            on="date",
            how="inner",
            suffixes=("_us", "_jp"),
        )
        
        # Calculate spread
        merged["us_2y"] = merged["close_price_us"]
        merged["jp_2y"] = merged["close_price_jp"]
        merged["spread"] = merged["us_2y"] - merged["jp_2y"]
        
        # Keep only needed columns
        result = merged[["date", "us_2y", "jp_2y", "spread"]].copy()
        
        print(f"\n✓ Successfully fetched yield data")
        print(f"  Source: {data_source_str}")
        print(f"  Date range: {result['date'].min().date()} to {result['date'].max().date()}")
        print(f"  US 2Y range: {result['us_2y'].min():.2f}% to {result['us_2y'].max():.2f}%")
        print(f"  Japan 2Y range: {result['jp_2y'].min():.2f}% to {result['jp_2y'].max():.2f}%")
        print(f"  Spread range: {result['spread'].min():.2f}% to {result['spread'].max():.2f}%")
        
        return result, data_source_str
        
    except Exception as e:
        print(f"\n⚠ FRED API failed: {type(e).__name__}: {e}")
        print("Falling back to Yahoo Finance...")
        return fetch_yield_data_yahoo_fallback(days=days, start_date=start_date)





def fetch_yield_data_yahoo_fallback(
    days: Optional[int] = None, start_date: Optional[str] = None
) -> tuple[pd.DataFrame, str]:
    """
    Fallback: Fetch yield data from Yahoo Finance when FRED API is unavailable.
    
    Note: Yahoo Finance has limited yield data, so this is a fallback option.
    """
    end_date = datetime.now()
    
    if start_date:
        calc_start = pd.to_datetime(start_date)
    else:
        if days is None:
            days = 3650  # Default to 10 years
        calc_start = end_date - timedelta(days=days)
    
    try:
        print("\nFetching US Treasury yields from Yahoo Finance...")
        # Use US 5-year yield as proxy for 2-year
        print("Using US 5-year yield (^FVX) as proxy for 2-year yield...")
        
        us_5y = yf.Ticker("^FVX")
        us_5y_df = us_5y.history(
            start=calc_start.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            interval="1d",
        )
        
        if us_5y_df.empty:
            raise ValueError("No US yield data from Yahoo Finance")
        
        us_5y_df = us_5y_df.reset_index()
        us_5y_df = us_5y_df.rename(columns={"Date": "date", "Close": "us_2y"})
        us_5y_df["date"] = pd.to_datetime(us_5y_df["date"]).dt.tz_localize(None)
        us_5y_df = us_5y_df[["date", "us_2y"]]
        
        # For Japan, use estimated value
        print(f"Using estimated Japan 2Y yield (typically 0.0-0.3% due to BOJ policy)...")
        jp_2y_estimate = JAPAN_2Y_ESTIMATE  # Approximate Japan 2Y yield (Updated Nov 2025)
        
        result = us_5y_df.copy()
        result["jp_2y"] = jp_2y_estimate
        result["spread"] = result["us_2y"] - result["jp_2y"]
        
        result = result[["date", "us_2y", "jp_2y", "spread"]].copy()
        
        print(f"✓ Fetched yield data from Yahoo Finance (fallback)")
        print(f"  Date range: {result['date'].min().date()} to {result['date'].max().date()}")
        print(f"  US 2Y (proxy) range: {result['us_2y'].min():.2f}% to {result['us_2y'].max():.2f}%")
        print(f"  Japan 2Y (estimated): {jp_2y_estimate:.2f}%")
        print(f"  Spread range: {result['spread'].min():.2f}% to {result['spread'].max():.2f}%")
        
        return result, "Yahoo Finance"
        
    except Exception as e:
        raise Exception(f"Yahoo Finance fallback also failed: {e}")


if __name__ == "__main__":
    # Quick test
    df = fetch_btc_history(days=30)
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nLast 5 rows:")
    print(df.tail())
