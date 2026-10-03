"""
Daily BTC close price and AHR999 from the generated metrics CSV.
"""
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

from dca_service.config import settings
from dca_service.core.logging import logger


@dataclass(frozen=True)
class MarketDay:
    close_price: Optional[float]
    ahr999: Optional[float]


def resolve_metrics_csv_path() -> Path:
    """Resolve metrics CSV path using the same conventions as metrics provider."""
    csv_path_str = settings.METRICS_CSV_PATH
    csv_path = Path(csv_path_str)
    if csv_path.is_absolute():
        return csv_path

    # dca_service/src/dca_service/services/market_history.py -> dca_service/
    dca_service_dir = Path(__file__).resolve().parent.parent.parent.parent
    if csv_path_str.startswith("../"):
        relative_part = csv_path_str[3:]
        resolved = (dca_service_dir.parent / relative_part).resolve()
    else:
        resolved = (dca_service_dir / csv_path_str).resolve()

    if not resolved.exists():
        alt_path = Path(csv_path_str)
        if alt_path.exists():
            return alt_path.resolve()
    return resolved


_cache: Tuple[Optional[Tuple[str, float]], Dict[str, MarketDay]] = (None, {})


def _float_or_none(value: Optional[str]) -> Optional[float]:
    try:
        number = float(value) if value not in (None, "") else None
    except ValueError:
        return None
    return number if number is not None and number > 0 else None


def _load() -> Dict[str, MarketDay]:
    global _cache
    path = resolve_metrics_csv_path()
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return {}
    if _cache[0] == key:
        return _cache[1]
    days: Dict[str, MarketDay] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("date"):
                    days[row["date"]] = MarketDay(
                        close_price=_float_or_none(row.get("close_price")),
                        ahr999=_float_or_none(row.get("ahr999")),
                    )
    except Exception as e:
        logger.warning(f"Could not read metrics CSV {path}: {e}")
        return {}
    _cache = (key, days)
    return days


def market_day(day: date) -> Optional[MarketDay]:
    return _load().get(day.isoformat())
