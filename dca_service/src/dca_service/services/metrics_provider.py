import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

from dca_service.config import settings

def get_latest_metrics() -> Optional[Dict[str, Union[float, datetime]]]:
    """
    Reads the latest metrics (AHR999, Price) from the configured file path.
    Supports CSV and JSON formats.
    
    Returns:
        Dict with keys: 'ahr999', 'price_usd', 'timestamp'
        or None if file not found or invalid.
    """
    file_path = Path(settings.METRICS_FILE_PATH)
    
    if not file_path.exists():
        return None

    try:
        if file_path.suffix == '.csv':
            return _read_csv_metrics(file_path)
        elif file_path.suffix == '.json':
            return _read_json_metrics(file_path)
        else:
            return None
    except Exception as e:
        print(f"Error reading metrics: {e}")
        return None

def _read_csv_metrics(file_path: Path) -> Optional[Dict]:
    """
    Expects CSV with headers: timestamp,price,ahr999
    Returns the last row.
    """
    with open(file_path, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        if not rows:
            return None
            
        last_row = rows[-1]
        
        # Try parsing timestamp, handle ISO format or simple date
        ts_str = last_row.get('timestamp', '')
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except ValueError:
            timestamp = datetime.utcnow() # Fallback

        return {
            "ahr999": float(last_row.get('ahr999', 0)),
            "price_usd": float(last_row.get('price', 0)),
            "timestamp": timestamp
        }

def _read_json_metrics(file_path: Path) -> Optional[Dict]:
    """
    Expects JSON object: {"timestamp": "...", "price": 123.4, "ahr999": 0.5}
    """
    with open(file_path, 'r') as f:
        data = json.load(f)
        
        ts_str = data.get('timestamp', '')
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except ValueError:
            timestamp = datetime.utcnow()

        return {
            "ahr999": float(data.get('ahr999', 0)),
            "price_usd": float(data.get('price', 0)),
            "timestamp": timestamp
        }
