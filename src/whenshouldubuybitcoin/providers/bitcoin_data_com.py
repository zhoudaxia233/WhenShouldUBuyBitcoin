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

# Free tier allows 10 requests/hour; spacing keeps a multi-call run under it.
REQUEST_SPACING_SECONDS = 7.0
# Hard ceiling on HTTP requests issued per run (including retries), so a retry
# storm can never exceed the free-tier 10/hour budget.
MAX_REQUESTS_PER_RUN = 10

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


class RequestBudget:
    """Spaces requests and caps the per-run total to protect the free-tier quota.

    One budget is shared across every series in a run: ``consume`` sleeps
    ``spacing`` seconds before each request *except the first* and counts it, so
    retries are throttled and counted too. Once ``max_requests`` are used,
    ``can_request`` returns False and callers stop issuing requests — a retry
    storm can no longer blow the 10/hour · 15/day budget.
    """

    def __init__(
        self,
        max_requests: int = MAX_REQUESTS_PER_RUN,
        spacing: float = REQUEST_SPACING_SECONDS,
    ) -> None:
        self.max_requests = max_requests
        self.spacing = spacing
        self.used = 0

    def can_request(self) -> bool:
        return self.used < self.max_requests

    def consume(self) -> None:
        """Throttle (space requests) and count one request against the budget."""
        if self.used and self.spacing:
            time.sleep(self.spacing)
        self.used += 1


def _report_failure(metric_key: str, attempt: int, max_retries: int, error) -> None:
    if attempt < max_retries - 1:
        print(
            f"⚠ bitcoin-data.com {metric_key} attempt "
            f"{attempt + 1}/{max_retries} failed: {error}. Retrying..."
        )
    else:
        print(
            f"✗ bitcoin-data.com {metric_key} failed after "
            f"{max_retries} attempts: {error}"
        )


def fetch_series(
    metric_key: str,
    startday: Optional[str] = None,
    max_retries: int = 2,
    budget: Optional["RequestBudget"] = None,
) -> Optional[list[tuple[str, float]]]:
    """Fetch one metric series; None when retries or the request budget run out.

    Every HTTP request (including retries) is spaced and counted against
    ``budget`` so a retry storm cannot exceed the free-tier ceiling. Client
    errors (4xx other than 429) are not retried — they will not fix themselves.
    """
    budget = budget or RequestBudget()
    url = f"{BASE_URL}{ONCHAIN_ENDPOINTS[metric_key]}"
    params = {"startday": startday} if startday else {}

    for attempt in range(max_retries):
        if not budget.can_request():
            print(
                f"✗ bitcoin-data.com {metric_key}: per-run request budget "
                f"({budget.max_requests}) exhausted; skipping"
            )
            return None
        budget.consume()
        try:
            response = requests.get(
                url, params=params, headers=_auth_headers(), timeout=30
            )
            response.raise_for_status()
            return parse_series(response.json())
        except requests.exceptions.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None and 400 <= status < 500 and status != 429:
                print(
                    f"✗ bitcoin-data.com {metric_key} client error {status}: "
                    f"{e}; not retrying"
                )
                return None
            _report_failure(metric_key, attempt, max_retries, e)
        except Exception as e:
            _report_failure(metric_key, attempt, max_retries, e)
    return None


def fetch_all_onchain_series(
    startday: Optional[str] = None,
    budget: Optional["RequestBudget"] = None,
) -> dict[str, list[tuple[str, float]]]:
    """Fetch every on-chain series sequentially under one shared request budget.

    Spacing and the per-run request cap are enforced by the shared ``budget``,
    so the whole run (including retries) stays within the free-tier quota.
    Returns only the series that succeeded (possibly none); callers degrade
    gracefully on partial data.
    """
    budget = budget or RequestBudget()
    results: dict[str, list[tuple[str, float]]] = {}
    for metric_key in ONCHAIN_ENDPOINTS:
        if not budget.can_request():
            print(
                f"✗ bitcoin-data.com: per-run request budget exhausted before "
                f"{metric_key}; returning {len(results)} series"
            )
            break
        series = fetch_series(metric_key, startday=startday, budget=budget)
        if series is not None:
            results[metric_key] = series
            print(f"✓ bitcoin-data.com {metric_key}: {len(series)} rows")
    return results
