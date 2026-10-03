"""
EUR→USD reference rates from the European Central Bank, served by Frankfurter.

Used once when an external EUR buy is saved; the rate is stored with the buy.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict

import httpx

from dca_service.core.logging import logger

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/{day}"


@dataclass(frozen=True)
class FxRate:
    rate: float  # USD per 1 EUR
    date: str  # ECB reference date actually used (previous business day on weekends)


class FxUnavailable(Exception):
    """The reference rate could not be fetched."""


# Rates for days before today never change, so keep them for the process lifetime.
_settled: Dict[date, FxRate] = {}


def eur_usd_rate(day: date) -> FxRate:
    if day in _settled:
        return _settled[day]
    try:
        response = httpx.get(
            FRANKFURTER_URL.format(day=day.isoformat()),
            params={"base": "EUR", "symbols": "USD"},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        rate = float(payload["rates"]["USD"])
        rate_date = str(payload["date"])
    except Exception as e:
        logger.warning(f"EUR/USD reference rate for {day} unavailable: {e}")
        raise FxUnavailable(str(e)) from e
    if rate <= 0:
        raise FxUnavailable(f"Non-positive rate {rate}")
    result = FxRate(rate=rate, date=rate_date)
    if day < datetime.now(timezone.utc).date():
        _settled[day] = result
    return result
