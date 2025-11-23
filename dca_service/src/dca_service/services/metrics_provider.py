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
class MetricsSource:
    backend: str  # "csv" or "realtime"
    label: str    # Human-readable description

@dataclass
class Metrics:
    ahr999: float
    price_usd: float
    peak180: float
    timestamp: datetime
    source: MetricsSource

class BaseMetricsBackend(Protocol):
    def get_latest_metrics(self) -> Metrics:
        ...

class CsvMetricsBackend:
    def get_latest_metrics(self) -> Metrics:
        file_path = _resolve_csv_path()
        
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
                
                # Calculate peak180 from last 180 rows
                # Get last 180 rows (including current)
                last_180_rows = rows[-180:]
                prices_180 = []
                for r in last_180_rows:
                    try:
                        prices_180.append(float(r[COL_PRICE]))
                    except (ValueError, KeyError):
                        continue
                
                peak180 = max(prices_180) if prices_180 else price_usd
                
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
                    peak180=peak180,
                    timestamp=timestamp,
                    source=MetricsSource(
                        backend="csv",
                        label="Historical CSV"
                    )
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
            peak180 = data.get("peak180", price_usd) # Fallback to current price if missing
            
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
                peak180=peak180,
                timestamp=timestamp,
                source=MetricsSource(
                    backend="realtime",
                    label="Binance"
                )
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
            "peak180": metrics.peak180,
            "timestamp": metrics.timestamp,
            "source": metrics.source.backend,
            "source_label": metrics.source.label
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
                    "peak180": metrics.peak180,
                    "timestamp": metrics.timestamp,
                    "source": "csv",
                    "source_label": "Historical CSV [fallback]"
                }
            except Exception as csv_e:
                print(f"Fallback CSV backend also failed: {csv_e}")
                return None
        
        return None

def _resolve_csv_path() -> Path:
    """
    Resolve the CSV path from settings, handling relative paths correctly.
    The path "../docs/data/btc_metrics.csv" should resolve relative to dca_service/ directory.
    """
    csv_path_str = settings.METRICS_CSV_PATH
    
    if Path(csv_path_str).is_absolute():
        return Path(csv_path_str)
    
    # For relative paths like "../docs/data/btc_metrics.csv"
    # Resolve from dca_service/ directory (parent of src/)
    # __file__ is dca_service/src/dca_service/services/metrics_provider.py
    # We want to go to dca_service/ directory
    dca_service_dir = Path(__file__).resolve().parent.parent.parent.parent
    # Now resolve the relative path from dca_service/
    # "../docs/data/btc_metrics.csv" -> go up one level, then docs/data/btc_metrics.csv
    if csv_path_str.startswith("../"):
        # Remove "../" and resolve from parent of dca_service/
        relative_part = csv_path_str[3:]  # Remove "../"
        file_path = (dca_service_dir.parent / relative_part).resolve()
    else:
        file_path = (dca_service_dir / csv_path_str).resolve()
    
    # If still not found, try from current working directory
    if not file_path.exists():
        alt_path = Path(csv_path_str)
        if alt_path.exists():
            return alt_path
    
    return file_path

def get_historical_ahr999_values() -> list[float]:
    """
    Get all historical AHR999 values from CSV file.
    Used for calculating percentiles in AHR999 percentile strategy.
    
    Returns:
        List of AHR999 values (float), sorted by date
    """
    file_path = _resolve_csv_path()
    
    if not file_path.exists():
        return []
    
    try:
        with open(file_path, 'r') as f:
            reader = csv.DictReader(f)
            
            if not reader.fieldnames or COL_AHR999 not in reader.fieldnames:
                return []
            
            ahr999_values = []
            for row in reader:
                try:
                    ahr999_val = float(row[COL_AHR999])
                    if ahr999_val == ahr999_val:  # Check for NaN
                        ahr999_values.append(ahr999_val)
                except (ValueError, KeyError):
                    continue
            
            return ahr999_values
    except Exception as e:
        print(f"Error reading historical AHR999 values: {e}")
        return []

def calculate_ahr999_percentile_thresholds() -> dict[str, float]:
    """
    Calculate AHR999 percentile thresholds (p10, p25, p50, p75, p90).
    Used for AHR999 percentile strategy to determine which tier the current AHR999 falls into.
    
    Returns:
        Dictionary with percentile thresholds:
        {
            "p10": float,  # 10th percentile (bottom 10%)
            "p25": float,  # 25th percentile
            "p50": float,  # 50th percentile (median)
            "p75": float,  # 75th percentile
            "p90": float,  # 90th percentile
        }
    """
    historical_values = get_historical_ahr999_values()
    
    if not historical_values:
        # Fallback to fixed thresholds if no historical data
        return {
            "p10": 0.45,
            "p25": 0.60,
            "p50": 0.90,
            "p75": 1.20,
            "p90": 1.80,
        }
    
    sorted_values = sorted(historical_values)
    n = len(sorted_values)
    
    def get_percentile_value(percentile: int) -> float:
        """Get the value at a given percentile (0-100)"""
        index = int((percentile / 100.0) * n)
        index = min(index, n - 1)  # Ensure index is within bounds
        return sorted_values[index]
    
    return {
        "p10": get_percentile_value(10),
        "p25": get_percentile_value(25),
        "p50": get_percentile_value(50),
        "p75": get_percentile_value(75),
        "p90": get_percentile_value(90),
    }
