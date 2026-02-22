import csv
import json
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
from dca_service.core.logging import logger

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
        logger.warning(f"Error fetching metrics from {settings.METRICS_BACKEND}: {e}")
        
        # Fallback logic
        if settings.METRICS_BACKEND == "realtime" and settings.METRICS_FALLBACK_TO_CSV:
            logger.info("Attempting fallback to CSV backend...")
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
                logger.warning(f"Fallback CSV backend also failed: {csv_e}")
                return None
        
        return None


def get_latest_bottoming_volume_signal() -> Optional[Dict[str, Any]]:
    """
    Read latest volume-based bottoming proxy signal from metrics CSV.

    This is an advisory-only signal used by UI/analysis layers. It is optional and
    returns None when the CSV has not been regenerated with the new columns yet.
    """
    file_path = _resolve_csv_path()
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None

        last_row = rows[-1]

        def _as_float(key: str) -> Optional[float]:
            value = last_row.get(key)
            if value in (None, "", "nan", "NaN"):
                return None
            try:
                parsed = float(value)
                return parsed if parsed == parsed else None
            except (TypeError, ValueError):
                return None

        def _as_bool(key: str) -> Optional[bool]:
            value = last_row.get(key)
            if value is None or value == "":
                return None
            return str(value).strip().lower() in {"1", "true", "yes"}

        ratio = _as_float("volume_ratio_30")
        available = any(
            col in (reader.fieldnames or [])
            for col in [
                "volume",
                "volume_ma30",
                "volume_ratio_30",
                "is_post_panic_volume_contraction",
            ]
        )
        if not available:
            return None

        return {
            "available": True,
            "as_of_date": last_row.get(COL_DATE),
            "volume": _as_float("volume"),
            "volume_ma30": _as_float("volume_ma30"),
            "volume_ratio_30": ratio,
            "daily_return_pct": _as_float("daily_return_pct"),
            "is_panic_selloff_day": _as_bool("is_panic_selloff_day"),
            "recent_panic_selloff_7d": _as_bool("recent_panic_selloff_7d"),
            "is_post_panic_volume_contraction": _as_bool("is_post_panic_volume_contraction"),
            "rsi14": _as_float("rsi14"),
            "rsi14w": _as_float("rsi14w"),
            "is_rsi_daily_oversold": _as_bool("is_rsi_daily_oversold"),
            "is_rsi_weekly_oversold_proxy": _as_bool("is_rsi_weekly_oversold_proxy"),
            "is_rsi_bottoming_signal": _as_bool("is_rsi_bottoming_signal"),
            "status_label": (
                "Post-panic volume contraction"
                if _as_bool("is_post_panic_volume_contraction")
                else "No post-panic contraction"
            ),
            "source": "metrics_csv",
        }
    except Exception as e:
        logger.warning(f"Failed to read bottoming volume signal from CSV: {e}")
        return None


def get_latest_macro_preview_snapshot() -> Optional[Dict[str, Any]]:
    """
    Read a concise macro snapshot from docs/data/daily_report.json for DCA preview UI.

    This is display-only and should never block DCA decisions.
    """
    try:
        # __file__ = dca_service/src/dca_service/services/metrics_provider.py
        # parents[3] = dca_service/
        dca_service_dir = Path(__file__).resolve().parents[3]
        report_path = (dca_service_dir.parent / "docs" / "data" / "daily_report.json").resolve()
        if not report_path.exists():
            return None

        data = json.loads(report_path.read_text(encoding="utf-8"))
        sections = data.get("sections")
        if not isinstance(sections, list):
            return None

        section_metrics: Dict[str, Dict[str, Any]] = {}
        for section in sections:
            if not isinstance(section, dict):
                continue
            chart = str(section.get("chart") or "").strip()
            metrics = section.get("metrics")
            if chart and isinstance(metrics, dict):
                section_metrics[chart] = metrics

        macro_metrics = section_metrics.get("Macro Risk Score", {})
        funding_metrics = section_metrics.get("Funding & Credit Stress", {})
        liquidity_metrics = section_metrics.get("Net Liquidity", {})
        oi_metrics = section_metrics.get("Futures OI & Price", {})
        usdjpy_metrics = section_metrics.get("USD/JPY Risk Map", {})
        ma_metrics = section_metrics.get("MA Cross Analysis", {})

        def _as_float(obj: Dict[str, Any], key: str) -> Optional[float]:
            value = obj.get(key)
            if value in (None, "", "nan", "NaN"):
                return None
            try:
                parsed = float(value)
                return parsed if parsed == parsed else None
            except (TypeError, ValueError):
                return None

        snapshot = {
            "available": True,
            "report_date": data.get("report_date"),
            "macro_risk_score": _as_float(macro_metrics, "score"),
            "macro_risk_regime": macro_metrics.get("regime"),
            "stress_flags": funding_metrics.get("stress_flags"),
            "funding_stress_level": funding_metrics.get("stress_level"),
            "net_liquidity_90d_delta": _as_float(liquidity_metrics, "net_liquidity_90d_delta"),
            "oi_30d_change_pct": _as_float(oi_metrics, "oi_30d_change_pct"),
            "oi_quadrant": oi_metrics.get("quadrant"),
            "usdjpy_risk_level": usdjpy_metrics.get("risk_level"),
            "ma_regime": ma_metrics.get("regime"),
        }

        has_any = any(
            snapshot.get(k) is not None
            for k in [
                "macro_risk_score",
                "macro_risk_regime",
                "stress_flags",
                "net_liquidity_90d_delta",
                "oi_30d_change_pct",
                "usdjpy_risk_level",
                "ma_regime",
            ]
        )
        return snapshot if has_any else None
    except Exception as e:
        logger.warning(f"Failed to read macro preview snapshot from daily_report: {e}")
        return None


def get_drawdown_percentile_snapshot(
    current_price: float,
    current_peak: float,
    window_days: int = 180,
) -> Optional[Dict[str, Any]]:
    """
    Compute current drawdown percentile against historical rolling-window drawdowns.

    Returns:
        {
            "drawdown_ratio": float,         # e.g. 0.42
            "drawdown_percentile": float,    # 0..100
            "historical_date": str,          # YYYY-MM-DD
            "historical_peak": float,        # rolling peak on matched day
            "historical_price": float,       # close price on matched day
            "historical_drawdown_ratio": float
        }
        or None if unavailable.
    """
    try:
        if current_peak <= 0 or current_price <= 0:
            return None

        current_drawdown = max(0.0, min(1.0, (current_peak - current_price) / current_peak))
        file_path = _resolve_csv_path()

        if not file_path.exists():
            return None

        rows: list[tuple[str, float]] = []
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row.get(COL_DATE)
                price_str = row.get(COL_PRICE)
                if not date_str or not price_str:
                    continue
                try:
                    rows.append((date_str, float(price_str)))
                except (TypeError, ValueError):
                    continue

        if len(rows) < 2:
            return None

        drawdowns: list[dict[str, Any]] = []
        prices_only = [p for _, p in rows]
        for i, (date_str, price) in enumerate(rows):
            start = max(0, i - window_days + 1)
            peak = max(prices_only[start : i + 1])
            if peak <= 0:
                continue
            dd = max(0.0, min(1.0, (peak - price) / peak))
            drawdowns.append(
                {
                    "date": date_str,
                    "price": price,
                    "peak": peak,
                    "drawdown_ratio": dd,
                }
            )

        if not drawdowns:
            return None

        less_or_equal = sum(1 for item in drawdowns if item["drawdown_ratio"] <= current_drawdown)
        percentile = (less_or_equal / len(drawdowns)) * 100.0

        matched = min(drawdowns, key=lambda item: abs(item["drawdown_ratio"] - current_drawdown))

        return {
            "drawdown_ratio": current_drawdown,
            "drawdown_percentile": percentile,
            "historical_date": matched["date"],
            "historical_peak": matched["peak"],
            "historical_price": matched["price"],
            "historical_drawdown_ratio": matched["drawdown_ratio"],
        }
    except Exception as e:
        logger.warning(f"Failed to compute drawdown percentile snapshot: {e}")
        return None


def get_drawdown_context(current_price: float) -> Optional[Dict[str, Any]]:
    """
    Build multi-definition drawdown context for UI:
    - ATH drawdown
    - 365-day rolling drawdown
    - 180-day rolling drawdown

    For each definition, includes:
    - current_drawdown_ratio
    - percentile_rank (historical % of points with drawdown <= current)
    - deeper_than_pct (= percentile_rank)
    - more_extreme_pct (= 100 - percentile_rank)
    - nearest_match (historical closest drawdown by value)
    - last_occurrence (most recent historical day with drawdown >= current)
    - recent_comparable (most recent day with similar drawdown, +/-2 percentage points;
      if unavailable, falls back to nearest_match)
    """
    try:
        if current_price <= 0:
            return None

        file_path = _resolve_csv_path()
        if not file_path.exists():
            return None

        rows: list[tuple[str, float]] = []
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row.get(COL_DATE)
                price_str = row.get(COL_PRICE)
                if not date_str or not price_str:
                    continue
                try:
                    rows.append((date_str, float(price_str)))
                except (TypeError, ValueError):
                    continue

        if len(rows) < 2:
            return None

        prices = [p for _, p in rows]

        def _hist_drawdowns(window_days: Optional[int]) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            for i, (date_str, price) in enumerate(rows):
                if window_days is None:
                    peak = max(prices[: i + 1])
                else:
                    start = max(0, i - window_days + 1)
                    peak = max(prices[start : i + 1])
                if peak <= 0:
                    continue
                dd = max(0.0, min(1.0, (peak - price) / peak))
                out.append(
                    {
                        "date": date_str,
                        "price": price,
                        "peak": peak,
                        "drawdown_ratio": dd,
                    }
                )
            return out

        def _current_peak(window_days: Optional[int]) -> float:
            if window_days is None:
                hist_peak = max(prices)
            else:
                hist_peak = max(prices[-window_days:])
            return max(hist_peak, current_price)

        def _compute_one(window_label: str, window_days: Optional[int]) -> Dict[str, Any]:
            hist = _hist_drawdowns(window_days)
            if not hist:
                return {}

            peak_now = _current_peak(window_days)
            current_dd = max(0.0, min(1.0, (peak_now - current_price) / peak_now))

            less_or_equal = sum(1 for item in hist if item["drawdown_ratio"] <= current_dd)
            percentile = (less_or_equal / len(hist)) * 100.0

            nearest = min(hist, key=lambda item: abs(item["drawdown_ratio"] - current_dd))
            last_occurrence = None
            for item in reversed(hist):
                if item["drawdown_ratio"] >= current_dd:
                    last_occurrence = item
                    break

            comparable_tolerance = 0.02
            recent_comparable = None
            for item in reversed(hist):
                if abs(item["drawdown_ratio"] - current_dd) <= comparable_tolerance:
                    recent_comparable = item
                    break
            if recent_comparable is None:
                recent_comparable = nearest

            return {
                "window": window_label,
                "current_peak": peak_now,
                "current_price": current_price,
                "current_drawdown_ratio": current_dd,
                "percentile_rank": percentile,
                "deeper_than_pct": percentile,
                "more_extreme_pct": max(0.0, 100.0 - percentile),
                "nearest_match": nearest,
                "last_occurrence": last_occurrence,
                "recent_comparable": recent_comparable,
            }

        return {
            "ath": _compute_one("ATH", None),
            "365d": _compute_one("365D", 365),
            "180d": _compute_one("180D", 180),
        }
    except Exception as e:
        logger.warning(f"Failed to compute drawdown context: {e}")
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
