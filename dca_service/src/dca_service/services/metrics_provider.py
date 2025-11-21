import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Union, Protocol, Any
from dataclasses import dataclass
import sys
import os

# Add the parent directory to sys.path to allow importing from whenshouldubuybitcoin
# This is needed because dca_service is a subdirectory of the main repo
sys.path.append(str(Path(__file__).resolve().parents[4] / "src"))

from dca_service.config import settings

# CSV Column Constants
COL_DATE = "date"
COL_PRICE = "close_price"
COL_AHR999 = "ahr999"

@dataclass
class Metrics:
    ahr999: float
    price_usd: float
    timestamp: datetime
    source: str = "unknown"

class BaseMetricsBackend(Protocol):
    def get_latest_metrics(self) -> Metrics:
        ...

class CsvMetricsBackend:
    def get_latest_metrics(self) -> Metrics:
        file_path = Path(settings.METRICS_CSV_PATH)
        
        if not file_path.exists():
            raise FileNotFoundError(f"Metrics file not found: {file_path}")

        try:
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                
                if not reader.fieldnames:
                    raise ValueError("Metrics file is empty")
                    
                required_cols = {COL_DATE, COL_PRICE, COL_AHR999}
                if not required_cols.issubset(reader.fieldnames):
                    raise ValueError(f"Missing columns. Found: {reader.fieldnames}, Required: {required_cols}")
                
                rows = list(reader)
                if not rows:
                    raise ValueError("Metrics file has no data rows")
                    
                last_row = rows[-1]
                
                # Parse date (YYYY-MM-DD) -> datetime UTC
                date_str = last_row[COL_DATE]
                timestamp = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                
                # Parse floats
                price_usd = float(last_row[COL_PRICE])
                ahr999 = float(last_row[COL_AHR999])
                
                # Check for NaN/Inf
                if price_usd != price_usd or ahr999 != ahr999:
                    raise ValueError("Metrics contain NaN values")
                
                # Check Staleness
                now = datetime.now(timezone.utc)
                age = now - timestamp
                if age > timedelta(hours=settings.METRICS_MAX_AGE_HOURS):
                    raise ValueError(f"Metrics are stale. Age: {age}, Max allowed: {settings.METRICS_MAX_AGE_HOURS} hours")

                return Metrics(
                    ahr999=ahr999,
                    price_usd=price_usd,
                    timestamp=timestamp,
                    source="csv"
                )

        except Exception as e:
            raise e

class RealtimeMetricsBackend:
    def get_latest_metrics(self) -> Metrics:
        try:
            from whenshouldubuybitcoin.realtime_check import check_realtime_status
            
            # Call the existing realtime function
            # verbose=False to avoid printing to stdout
            data = check_realtime_status(verbose=False)
            
            if not data:
                raise ValueError("Realtime check returned no data")
                
            ahr999 = data.get("ahr999")
            price_usd = data.get("realtime_price")
            timestamp = data.get("timestamp")
            
            # Validate
            if ahr999 is None or price_usd is None or timestamp is None:
                raise ValueError("Realtime data missing required fields")
                
            if ahr999 != ahr999 or price_usd != price_usd: # NaN check
                raise ValueError("Realtime metrics contain NaN values")
                
            if ahr999 <= 0 or price_usd <= 0:
                raise ValueError("Realtime metrics must be positive")

            # Ensure timestamp is timezone-aware UTC
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            else:
                timestamp = timestamp.astimezone(timezone.utc)
                
            # Check Staleness (even for realtime, to be safe)
            now = datetime.now(timezone.utc)
            age = now - timestamp
            if age > timedelta(hours=settings.METRICS_MAX_AGE_HOURS):
                raise ValueError(f"Realtime metrics are stale. Age: {age}")

            return Metrics(
                ahr999=ahr999,
                price_usd=price_usd,
                timestamp=timestamp,
                source="realtime"
            )
            
        except ImportError as e:
            raise ImportError(f"Could not import whenshouldubuybitcoin.realtime_check: {e}")
        except Exception as e:
            raise e

def get_metrics_backend() -> BaseMetricsBackend:
    if settings.METRICS_BACKEND == "realtime":
        return RealtimeMetricsBackend()
    return CsvMetricsBackend()

def get_latest_metrics() -> Optional[Dict[str, Any]]:
    """
    Top-level function to get metrics from the configured backend.
    Handles fallback logic if enabled.
    Returns a Dict compatible with the previous API:
    {"ahr999": float, "price_usd": float, "timestamp": datetime, "source": str}
    or None if all attempts fail.
    """
    backend = get_metrics_backend()
    
    try:
        metrics = backend.get_latest_metrics()
        return {
            "ahr999": metrics.ahr999,
            "price_usd": metrics.price_usd,
            "timestamp": metrics.timestamp,
            "source": metrics.source
        }
    except Exception as e:
        print(f"Error fetching metrics from {settings.METRICS_BACKEND}: {e}")
        
        # Fallback logic
        if settings.METRICS_BACKEND == "realtime" and settings.METRICS_FALLBACK_TO_CSV:
            print("Attempting fallback to CSV backend...")
            try:
                csv_backend = CsvMetricsBackend()
                metrics = csv_backend.get_latest_metrics()
                return {
                    "ahr999": metrics.ahr999,
                    "price_usd": metrics.price_usd,
                    "timestamp": metrics.timestamp,
                    "source": "csv (fallback)"
                }
            except Exception as csv_e:
                print(f"Fallback CSV backend also failed: {csv_e}")
                return None
        
        return None
