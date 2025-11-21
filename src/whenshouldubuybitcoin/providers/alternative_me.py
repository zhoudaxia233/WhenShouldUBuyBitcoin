"""
Provider for Fear & Greed Index from alternative.me.
"""
import requests
from typing import Optional, Dict, Any
from datetime import datetime

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
