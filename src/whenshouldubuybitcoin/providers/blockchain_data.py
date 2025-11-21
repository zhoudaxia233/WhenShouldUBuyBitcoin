"""
Provider for Blockchain.com data.
"""
import requests
import pandas as pd
from typing import Optional

def fetch_hashrate_trend() -> Optional[float]:
    """
    Fetch hashrate data and calculate a simple trend (e.g. 30-day change).
    
    Returns:
        Percentage change in hashrate over last 30 days.
        Returns None if fetching fails.
    """
    # Blockchain.com charts API
    url = "https://api.blockchain.info/charts/hash-rate?timespan=60days&format=json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "values" in data and len(data["values"]) > 30:
            values = data["values"]
            # Get latest and 30 days ago
            latest = values[-1]["y"]
            month_ago = values[-30]["y"]
            
            if month_ago > 0:
                change_pct = ((latest - month_ago) / month_ago) * 100
                return change_pct
            
    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Hashrate data: {e}")
        
    return None
