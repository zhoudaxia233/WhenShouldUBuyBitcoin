"""
Provider for Binance market data.
"""

import requests
import time
from typing import Optional


def fetch_btc_funding_rate() -> Optional[float]:
    """
    Fetch the current funding rate for BTCUSDC perpetual contract.

    Returns:
        Funding rate as a percentage (e.g. 0.01 for 0.01%).
        Returns None if fetching fails.
    """
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDC"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "lastFundingRate" in data:
            # Convert to percentage (e.g. 0.0001 -> 0.01%)
            rate = float(data["lastFundingRate"]) * 100
            return rate

    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Binance funding rate: {e}")

    return None


def fetch_open_interest_history(
    symbol: str = "BTCUSDC", period: str = "1d", limit: int = 500, max_retries: int = 4
) -> Optional[list]:
    """
    Fetch historical Open Interest data from Binance Futures.
    
    Implements retry logic with exponential backoff to handle transient failures,
    rate limiting, and network issues common in CI environments.

    Args:
        symbol: Trading pair (default: BTCUSDC)
        period: Timeframe (default: 1d)
        limit: Number of data points (default: 500, max 500)
        max_retries: Maximum number of retry attempts (default: 4)

    Returns:
        List of dictionaries containing OI data, or None if failed.
        Each dict has: symbol, sumOpenInterest, sumOpenInterestValue, timestamp
    """
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    params = {"symbol": symbol, "period": period, "limit": limit}

    for attempt in range(max_retries):
        try:
            # Increased timeout for CI environments
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if attempt > 0:
                print(f"✓ Successfully fetched OI data on attempt {attempt + 1}")
            
            return data

        except requests.exceptions.Timeout as e:
            wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s, 8s
            if attempt < max_retries - 1:
                print(f"⚠ Timeout fetching OI data (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"✗ Failed to fetch Binance OI data after {max_retries} attempts (timeout): {e}")
        
        except requests.exceptions.RequestException as e:
            wait_time = 2 ** attempt
            if attempt < max_retries - 1:
                print(f"⚠ Error fetching OI data (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"✗ Failed to fetch Binance OI data after {max_retries} attempts: {e}")
        
        except Exception as e:
            print(f"✗ Unexpected error fetching Binance Open Interest history: {e}")
            break

    return None
