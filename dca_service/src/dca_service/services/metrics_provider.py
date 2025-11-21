import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Union

from dca_service.config import settings

# CSV Column Constants
COL_DATE = "date"
COL_PRICE = "close_price"
COL_AHR999 = "ahr999"

def get_latest_metrics() -> Optional[Dict[str, Union[float, datetime]]]:
    """
    Reads the latest metrics from the configured CSV file.
    
    Validates:
    - File existence
    - Required columns
    - Data types (float)
    - Staleness (METRICS_MAX_AGE_HOURS)
    
    Returns:
        Dict with keys: 'ahr999', 'price_usd', 'timestamp'
        or None if any validation fails.
    """
    file_path = Path(settings.METRICS_CSV_PATH)
    
    if not file_path.exists():
        print(f"Metrics file not found: {file_path}")
        return None

    try:
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            
            # Check headers
            if not reader.fieldnames:
                print("Metrics file is empty")
                return None
                
            required_cols = {COL_DATE, COL_PRICE, COL_AHR999}
            if not required_cols.issubset(reader.fieldnames):
                print(f"Missing columns. Found: {reader.fieldnames}, Required: {required_cols}")
                return None
            
            # Read all rows to get the last one
            rows = list(reader)
            if not rows:
                print("Metrics file has no data rows")
                return None
                
            last_row = rows[-1]
            
            # Parse and Validate
            try:
                # Parse date (YYYY-MM-DD) -> datetime UTC
                date_str = last_row[COL_DATE]
                # Assuming the CSV date is just a date, we treat it as 00:00 UTC of that day
                timestamp = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                
                # Parse floats
                price_usd = float(last_row[COL_PRICE])
                ahr999 = float(last_row[COL_AHR999])
                
                # Check for NaN/Inf
                if price_usd != price_usd or ahr999 != ahr999: # NaN check
                    print("Metrics contain NaN values")
                    return None
                    
            except ValueError as e:
                print(f"Error parsing metrics row: {e}")
                return None
            
            # Check Staleness
            now = datetime.now(timezone.utc)
            age = now - timestamp
            if age > timedelta(hours=settings.METRICS_MAX_AGE_HOURS):
                print(f"Metrics are stale. Age: {age}, Max allowed: {settings.METRICS_MAX_AGE_HOURS} hours")
                return None

            return {
                "ahr999": ahr999,
                "price_usd": price_usd,
                "timestamp": timestamp
            }

    except Exception as e:
        print(f"Unexpected error reading metrics: {e}")
        return None
