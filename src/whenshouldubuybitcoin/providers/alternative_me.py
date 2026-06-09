"""
Provider for Fear & Greed Index from alternative.me.
"""
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timezone

def fetch_fear_and_greed_index() -> Optional[Dict[str, Any]]:
    """
    Fetch the latest Fear & Greed Index.
    
    Returns:
        Dictionary with:
        - value: int (0-100)
        - value_classification: str (e.g. "Extreme Fear")
        - timestamp: str
        
        Returns None if fetching fails.
    """
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "data" in data and len(data["data"]) > 0:
            item = data["data"][0]
            return {
                "value": int(item["value"]),
                "value_classification": item["value_classification"],
                "timestamp": datetime.fromtimestamp(int(item["timestamp"])).isoformat()
            }
            
    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Fear & Greed Index: {e}")

    return None


def fetch_fear_and_greed_history() -> Optional[list]:
    """
    Fetch the full daily Fear & Greed history (index inception: 2018-02-01).

    Returns:
        List of {"date": "YYYY-MM-DD", "value": int} sorted by date ascending,
        or None if fetching fails or yields no rows.
    """
    url = "https://api.alternative.me/fng/?limit=0"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        rows = []
        for item in data.get("data", []):
            try:
                ts = str(item["timestamp"])
                if "-" in ts:
                    day = ts[:10]
                else:
                    day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
                rows.append({"date": day, "value": int(item["value"])})
            except (KeyError, TypeError, ValueError):
                continue

        rows.sort(key=lambda r: r["date"])
        return rows or None

    except Exception as e:
        print(f"⚠ Warning: Failed to fetch Fear & Greed history: {e}")

    return None
