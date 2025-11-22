"""
Provider for Binance market data.
"""

import requests
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
    symbol: str = "BTCUSDC", period: str = "1d", limit: int = 500
) -> Optional[list]:
    """
    Fetch historical Open Interest data from Binance Futures.

    Args:
        symbol: Trading pair (default: BTCUSDC)
        period: Timeframe (default: 1d)
        limit: Number of data points (default: 500, max 500)

    Returns:
        List of dictionaries containing OI data, or None if failed.
        Each dict has: symbol, sumOpenInterest, sumOpenInterestValue, timestamp
    """
    url = "https://fapi.binance.com/futures/data/openInterestHist"
    params = {"symbol": symbol, "period": period, "limit": limit}

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data

    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Binance Open Interest history: {e}")

    return None
