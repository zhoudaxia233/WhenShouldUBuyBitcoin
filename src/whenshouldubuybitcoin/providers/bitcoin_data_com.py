"""
Provider for free Bitcoin on-chain metrics from bitcoin-data.com (BGeometrics).

Free tier (no token): 10 requests/hour, 15 requests/day, history limited to
the most recent ~4 years. An optional BGEOMETRICS_TOKEN env var is sent as a
Bearer token for paid tiers. Responses are JSON arrays of per-day objects
like {"d": "2024-01-01", "unixTs": ..., "<metricField>": "1.23"} where the
metric field name varies per endpoint.
"""

import os
import time
from typing import Optional

import requests

BASE_URL = "https://api.bitcoin-data.com"

# Free tier allows 10 requests/hour; spacing keeps a 7-call run under it.
REQUEST_SPACING_SECONDS = 7.0

# Dataset key -> API endpoint path.
ONCHAIN_ENDPOINTS = {
    "lth_realized_price": "/v1/lth-realized-price",
    "realized_price": "/v1/realized-price",
    "sth_realized_price": "/v1/sth-realized-price",
    "mvrv": "/v1/mvrv",
    "supply_loss_btc": "/v1/supply-loss",
    "supply_profit_btc": "/v1/supply-profit",
    "realized_cap_change_30d_usd": "/v1/realized-cap-change-30d",
}

# Non-value fields seen in API rows; the remaining parseable field is the metric.
_META_FIELDS = {"d", "theDay", "day", "unixTs", "unixTimestamp"}


def _auth_headers() -> dict:
    token = os.environ.get("BGEOMETRICS_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_series(rows) -> list[tuple[str, float]]:
    """Parse a bitcoin-data.com JSON array into [(YYYY-MM-DD, value), ...].

    Rows with a missing date or no numeric metric field are skipped. Output
    is sorted by date ascending. Relies on the API placing exactly one
    non-meta numeric field per row; the fixture-pinned tests catch breakage.
    """
    out: list[tuple[str, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        day = row.get("d") or row.get("theDay") or row.get("day")
        if not day:
            continue
        value = None
        for key, raw in row.items():
            if key in _META_FIELDS:
                continue
            try:
                value = float(raw)
                break
            except (TypeError, ValueError):
                continue
        if value is not None:
            out.append((str(day)[:10], value))
    out.sort(key=lambda pair: pair[0])
    return out


def fetch_series(
    metric_key: str,
    startday: Optional[str] = None,
    max_retries: int = 3,
) -> Optional[list[tuple[str, float]]]:
    """Fetch one metric series; returns None when all retries fail."""
    url = f"{BASE_URL}{ONCHAIN_ENDPOINTS[metric_key]}"
    params = {"startday": startday} if startday else {}

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url, params=params, headers=_auth_headers(), timeout=30
            )
            response.raise_for_status()
            return parse_series(response.json())
        except Exception as e:
            wait = 10 * (2**attempt)
            if attempt < max_retries - 1:
                print(
                    f"⚠ bitcoin-data.com {metric_key} attempt "
                    f"{attempt + 1}/{max_retries} failed: {e}. Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                print(
                    f"✗ bitcoin-data.com {metric_key} failed after "
                    f"{max_retries} attempts: {e}"
                )
    return None


def fetch_all_onchain_series(
    startday: Optional[str] = None,
) -> dict[str, list[tuple[str, float]]]:
    """Fetch every on-chain series sequentially with free-tier spacing.

    Returns only the series that succeeded (possibly none); callers degrade
    gracefully on partial data.
    """
    results: dict[str, list[tuple[str, float]]] = {}
    for i, metric_key in enumerate(ONCHAIN_ENDPOINTS):
        if i:
            time.sleep(REQUEST_SPACING_SECONDS)
        series = fetch_series(metric_key, startday=startday)
        if series is not None:
            results[metric_key] = series
            print(f"✓ bitcoin-data.com {metric_key}: {len(series)} rows")
    return results
