"""
Bitcoin wealth distribution scraper from BitInfoCharts.
Fetches live, daily-updated distribution data.
"""

import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
import logging
import requests
import io
import json
import pkgutil
import threading
import time
from pathlib import Path


logger = logging.getLogger(__name__)
BITINFOCHARTS_DISTRIBUTION_URL = "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html"

# Simple in-memory cache
_cache = {"data": None, "timestamp": None}
_state_lock = threading.RLock()
_diagnostics = {
    "last_attempt_at": None,
    "last_success_at": None,
    "last_status": "unavailable",
    "last_source": None,
    "last_as_of": None,
    "last_error_type": None,
    "last_error_message_sanitized": None,
    "last_http_status": None,
    "elapsed_ms": None,
    "target_url": BITINFOCHARTS_DISTRIBUTION_URL,
    "cache_age_seconds": None,
}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_age_seconds_unlocked() -> Optional[int]:
    timestamp = _cache.get("timestamp")
    if isinstance(timestamp, datetime):
        return max(0, int((datetime.now() - timestamp).total_seconds()))
    return None


def _set_diagnostics(**updates) -> Dict[str, object]:
    with _state_lock:
        _diagnostics.update(updates)
        _diagnostics["target_url"] = BITINFOCHARTS_DISTRIBUTION_URL
        _diagnostics["cache_age_seconds"] = _cache_age_seconds_unlocked()
        return dict(_diagnostics)


def _sanitize_scrape_error(exc: Exception, http_status: Optional[int]) -> tuple[str, str]:
    if isinstance(exc, requests.exceptions.Timeout):
        return "Timeout", "Request timed out while contacting BitInfoCharts."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "ConnectionError", "Could not connect to BitInfoCharts."
    if isinstance(exc, requests.exceptions.HTTPError):
        status = http_status or getattr(getattr(exc, "response", None), "status_code", None)
        if status:
            return "HTTPError", f"BitInfoCharts returned HTTP {status}."
        return "HTTPError", "BitInfoCharts returned an HTTP error."
    if isinstance(exc, requests.exceptions.RequestException):
        return exc.__class__.__name__, "BitInfoCharts request failed."

    message = str(exc)
    if isinstance(exc, ValueError):
        if "No tables found" in message:
            return "ParseError", "BitInfoCharts HTML did not contain readable tables."
        if "Unexpected table structure" in message:
            return "ParseError", "BitInfoCharts table structure did not match expected columns."
        if "Failed to parse any" in message:
            return "ParseError", "BitInfoCharts table was present but no valid distribution rows were parsed."
        return "ValueError", "BitInfoCharts distribution data could not be parsed."

    return exc.__class__.__name__, "Live BitInfoCharts fetch failed."


def _record_scrape_failure(
    exc: Exception,
    *,
    attempt_at: Optional[str],
    elapsed_ms: Optional[int],
    http_status: Optional[int],
) -> None:
    error_type, sanitized_message = _sanitize_scrape_error(exc, http_status)
    _set_diagnostics(
        last_attempt_at=attempt_at,
        last_status="unavailable",
        last_source="bitinfocharts",
        last_error_type=error_type,
        last_error_message_sanitized=sanitized_message,
        last_http_status=http_status,
        elapsed_ms=elapsed_ms,
    )


def _record_status(
    *,
    status: str,
    source: str,
    as_of: Optional[str],
    elapsed_ms: Optional[int] = None,
    http_status: Optional[int] = None,
    attempted_at: Optional[str] = None,
    clear_error: bool = False,
) -> None:
    updates = {
        "last_status": status,
        "last_source": source,
        "last_as_of": as_of,
    }
    if http_status is not None:
        updates["last_http_status"] = http_status
    if elapsed_ms is not None:
        updates["elapsed_ms"] = elapsed_ms
    if attempted_at is not None:
        updates["last_attempt_at"] = attempted_at
    if status == "live":
        updates["last_success_at"] = as_of or _now_utc_iso()
    if clear_error:
        updates["last_error_type"] = None
        updates["last_error_message_sanitized"] = None
        if http_status is None:
            updates["last_http_status"] = None
    _set_diagnostics(**updates)


def get_distribution_diagnostics() -> Dict[str, object]:
    """Return a copy of current BitInfoCharts scrape diagnostics."""
    with _state_lock:
        snapshot = dict(_diagnostics)
        snapshot["target_url"] = BITINFOCHARTS_DISTRIBUTION_URL
        snapshot["cache_age_seconds"] = _cache_age_seconds_unlocked()
        return snapshot


def parse_tier_range(tier_str: str) -> Optional[tuple[float, float]]:
    """
    Parse tier string from distribution scraper to extract min_btc and max_btc.
    
    Examples:
        "1000000+" -> (1000000, float('inf'))
        "100000-1000000" -> (100000, 1000000)
        "[0.1 - 1 BTC)" -> (0.1, 1)
        "[0.001-0.01 BTC)" -> (0.001, 0.01)
    """
    try:
        tier_str = tier_str.strip()
        
        # Handle format like '[0.1 - 1 BTC)' or '[0.1-1 BTC)'
        # Remove brackets and 'BTC)' suffix
        tier_str = tier_str.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
        if 'BTC' in tier_str:
            tier_str = tier_str.split('BTC')[0].strip()
        
        # Handle "X+" format (e.g., "1000000+")
        if tier_str.endswith('+'):
            min_btc = float(tier_str[:-1].replace(',', '').strip())
            return (min_btc, float('inf'))
        
        # Handle "X-Y" format (e.g., "100000-1000000" or "0.1 - 1")
        if '-' in tier_str:
            parts = tier_str.split('-')
            if len(parts) == 2:
                min_btc = float(parts[0].strip().replace(',', ''))
                max_btc = float(parts[1].strip().replace(',', ''))
                return (min_btc, max_btc)
        
        # Try to parse as a single number
        try:
            value = float(tier_str.replace(',', '').strip())
            return (value, float('inf'))
        except ValueError:
            pass
        
        logger.warning(f"Could not parse tier string: '{tier_str}'")
        return None
    except Exception as e:
        logger.warning(f"Error parsing tier string '{tier_str}': {e}")
        return None


def parse_percentile_value(percentile_str: str) -> Optional[float]:
    """
    Parse percentile string to extract numeric value.
    
    Examples:
        "Top 27.38%" -> 27.38
        "Top 0.00002%" -> 0.00002
        "Top 100.0%" -> 100.0
    """
    import re
    try:
        # Extract number from strings like "Top 27.38%" or "Top 0.00002%"
        match = re.search(r'([\d.]+)', percentile_str)
        if match:
            return float(match.group(1))
        return None
    except Exception as e:
        logger.warning(f"Error parsing percentile string '{percentile_str}': {e}")
        return None


def _parse_percentile(addresses_total_str: str) -> str:
    """
    Parse '% Addresses (Total)' column like '6.06% (7.77%)' to extract percentile.
    The value in parentheses represents the cumulative percentage of addresses
    with balance >= this tier's minimum. This IS the "Top X%" value directly.

    Preserves the original decimal precision from the website.

    Example: '6.06% (7.77%)' means addresses with balance >= this tier's min = Top 7.77%
    So if you hold 0.1 BTC (the min of [0.1-1) tier), you are in Top 7.77% of holders.
    """
    try:
        # Extract the value in parentheses: '6.06% (7.77%)' -> 7.77
        if "(" in addresses_total_str and ")" in addresses_total_str:
            top_percentile_str = (
                addresses_total_str.split("(")[1].split(")")[0].replace("%", "").strip()
            )
            top_percentile = float(top_percentile_str)

            # Preserve original decimal precision from the string
            # Count decimal places in the original string
            if "." in top_percentile_str:
                decimal_places = len(top_percentile_str.split(".")[1])
            else:
                decimal_places = 0

            # Format with preserved precision
            if decimal_places == 0:
                return f"Top {int(top_percentile)}%"
            else:
                return f"Top {top_percentile:.{decimal_places}f}%"
        return "Unknown"
    except Exception as e:
        logger.warning(f"Failed to parse percentile from '{addresses_total_str}': {e}")
        return "Unknown"


def _load_static_distribution() -> List[Dict[str, str]]:
    """Load bundled distribution data for explicit offline fallback callers."""
    try:
        data = pkgutil.get_data("dca_service", "data/wealth_distribution.json")
        if data:
            return json.loads(data.decode("utf-8"))

        json_path = Path(__file__).parent.parent / "data" / "wealth_distribution.json"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)

        logger.error(
            "Failed to load static distribution data: File not found via pkgutil "
            f"or at {json_path}"
        )
        raise ValueError("Static distribution data missing")
    except Exception as load_err:
        logger.error(f"Error loading static data: {load_err}")
        raise ValueError("Failed to load fallback distribution data") from load_err


def _cache_as_of() -> Optional[str]:
    with _state_lock:
        timestamp = _cache.get("timestamp")
        if isinstance(timestamp, datetime):
            return timestamp.isoformat()
        return None


def fetch_distribution_with_status(
    use_cache: bool = True,
    allow_static_fallback: bool = False,
    allow_stale_cache: bool = False,
) -> Dict[str, object]:
    """
    Fetch distribution data with provenance for callers that need to label stale data.
    """
    with _state_lock:
        cached_data = _cache["data"]
        cached_timestamp = _cache["timestamp"]

    if use_cache and cached_data is not None and cached_timestamp is not None:
        age = datetime.now() - cached_timestamp
        if age < timedelta(hours=24):
            logger.info(f"Using cached distribution data (age: {age})")
            as_of = _cache_as_of()
            _record_status(
                status="cached",
                source="bitinfocharts_cache",
                as_of=as_of,
                elapsed_ms=0,
                http_status=None,
            )
            return {
                "data": cached_data,
                "data_status": "cached",
                "source": "bitinfocharts_cache",
                "as_of": as_of,
            }

    try:
        data = fetch_distribution(
            use_cache=False,
            allow_static_fallback=False,
            allow_stale_cache=False,
        )
        return {
            "data": data,
            "data_status": "live",
            "source": "bitinfocharts",
            "as_of": _cache_as_of(),
        }
    except ValueError:
        with _state_lock:
            cached_data = _cache["data"]
            cached_timestamp = _cache["timestamp"]

        if allow_stale_cache and cached_data is not None:
            age = (
                datetime.now() - cached_timestamp
                if cached_timestamp
                else timedelta(days=999)
            )
            logger.warning(f"Using stale cached distribution data (age: {age})")
            as_of = _cache_as_of()
            _record_status(
                status="stale",
                source="bitinfocharts_cache",
                as_of=as_of,
            )
            return {
                "data": cached_data,
                "data_status": "stale",
                "source": "bitinfocharts_cache",
                "as_of": as_of,
            }
        if allow_static_fallback:
            _record_status(
                status="static",
                source="bundled_static",
                as_of=None,
            )
            return {
                "data": _load_static_distribution(),
                "data_status": "static",
                "source": "bundled_static",
                "as_of": None,
            }
        raise


def fetch_distribution(
    use_cache: bool = True,
    allow_static_fallback: bool = False,
    allow_stale_cache: bool = False,
) -> List[Dict[str, str]]:
    """
    Fetch Bitcoin wealth distribution from BitInfoCharts.

    Args:
        use_cache: If True, return cached data if it's less than 24 hours old
        allow_static_fallback: If True, use bundled static data when live fetch fails
            and no runtime cache is available. Runtime API callers should keep this
            False to avoid presenting stale packaged data as live BitInfoCharts data.
        allow_stale_cache: If True, return expired runtime cache when live fetch
            fails. Runtime API callers should keep this False so stale data is not
            presented as live.

    Returns:
        List of dicts with 'tier' and 'percentile' keys

    Raises:
        ValueError: If fetching fails and no cache exists
    """
    # Check cache
    with _state_lock:
        cached_data = _cache["data"]
        cached_timestamp = _cache["timestamp"]

    if use_cache and cached_data is not None and cached_timestamp is not None:
        age = datetime.now() - cached_timestamp
        if age < timedelta(hours=24):
            logger.info(f"Using cached distribution data (age: {age})")
            _record_status(
                status="cached",
                source="bitinfocharts_cache",
                as_of=_cache_as_of(),
                elapsed_ms=0,
                http_status=None,
            )
            return cached_data

    attempt_at = _now_utc_iso()
    started = time.perf_counter()
    http_status: Optional[int] = None
    diagnostics_recorded = False
    try:
        logger.info("Fetching live distribution data from BitInfoCharts...")

        # Fetch tables from the page
        url = BITINFOCHARTS_DISTRIBUTION_URL
        
        # Try to fetch live data with a short timeout
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            }
            response = requests.get(url, headers=headers, timeout=5)
            http_status = getattr(response, "status_code", None)
            response.raise_for_status()
            tables = pd.read_html(io.StringIO(response.text))
        except Exception as e:
            logger.warning(f"Failed to scrape live distribution data: {e}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _record_scrape_failure(
                e,
                attempt_at=attempt_at,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
            )
            diagnostics_recorded = True
            if allow_static_fallback:
                logger.warning("Using bundled static distribution fallback by explicit request.")
                _record_status(
                    status="static",
                    source="bundled_static",
                    as_of=None,
                    elapsed_ms=elapsed_ms,
                    http_status=http_status,
                )
                return _load_static_distribution()
            raise

        if not tables:
            diagnostics_recorded = True
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            exc = ValueError("No tables found on page")
            _record_scrape_failure(
                exc,
                attempt_at=attempt_at,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
            )
            raise exc

        # The first table contains the distribution data
        df = tables[0]

        # Expected columns: ['Balance, BTC', 'Addresses', '% Addresses (Total)', 'BTC', 'USD', '% BTC (Total)']
        if "% Addresses (Total)" not in df.columns or "Balance, BTC" not in df.columns:
            diagnostics_recorded = True
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            exc = ValueError(
                f"Unexpected table structure. Columns: {df.columns.tolist()}"
            )
            _record_scrape_failure(
                exc,
                attempt_at=attempt_at,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
            )
            raise exc

        # Parse the data
        result = []
        for _, row in df.iterrows():
            tier = row["Balance, BTC"]
            addresses_total = row["% Addresses (Total)"]

            # Skip if invalid
            if pd.isna(tier) or pd.isna(addresses_total):
                continue

            # Parse percentile from % Addresses (Total) column (not % BTC (Total))
            # The value in parentheses is the cumulative % of addresses with balance >= this tier
            percentile = _parse_percentile(str(addresses_total))

            result.append({
                "tier": str(tier),
                "balance": str(tier),
                "addresses": str(row.get("Addresses", "")),
                "coins": str(row.get("BTC", "")),
                "usd": str(row.get("USD", "")),
                "percent_coins": str(row.get("% BTC (Total)", "")),
                "percentile": percentile
            })

        if not result:
            diagnostics_recorded = True
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            exc = ValueError("Failed to parse any distribution data")
            _record_scrape_failure(
                exc,
                attempt_at=attempt_at,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
            )
            raise exc

        # Update cache
        with _state_lock:
            _cache["data"] = result
            _cache["timestamp"] = datetime.now()

        as_of = _cache_as_of()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _record_status(
            status="live",
            source="bitinfocharts",
            as_of=as_of,
            elapsed_ms=elapsed_ms,
            http_status=http_status,
            attempted_at=attempt_at,
            clear_error=True,
        )

        logger.info(f"Successfully fetched {len(result)} distribution tiers")
        return result

    except Exception as e:
        logger.error(f"Failed to fetch distribution data: {e}")
        if not diagnostics_recorded:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _record_scrape_failure(
                e,
                attempt_at=attempt_at,
                elapsed_ms=elapsed_ms,
                http_status=http_status,
            )

        # Use stale cache only when the caller explicitly allows it.
        with _state_lock:
            cached_data = _cache["data"]
            cached_timestamp = _cache["timestamp"]

        if allow_stale_cache and cached_data is not None:
            age = (
                datetime.now() - cached_timestamp
                if cached_timestamp
                else timedelta(days=999)
            )
            logger.warning(f"Using stale cached data (age: {age})")
            _record_status(
                status="stale",
                source="bitinfocharts_cache",
                as_of=_cache_as_of(),
            )
            return cached_data

        if allow_static_fallback:
            logger.warning("Using bundled static distribution fallback by explicit request.")
            _record_status(
                status="static",
                source="bundled_static",
                as_of=None,
            )
            return _load_static_distribution()

        # No cache available, must fail
        logger.error("No cached data available, cannot provide distribution data")
        raise ValueError("Failed to fetch distribution data and no cache available")


def clear_cache():
    """Clear the distribution cache (useful for testing)."""
    with _state_lock:
        _cache["data"] = None
        _cache["timestamp"] = None
        _diagnostics.update(
            {
                "last_attempt_at": None,
                "last_success_at": None,
                "last_status": "unavailable",
                "last_source": None,
                "last_as_of": None,
                "last_error_type": None,
                "last_error_message_sanitized": None,
                "last_http_status": None,
                "elapsed_ms": None,
                "target_url": BITINFOCHARTS_DISTRIBUTION_URL,
                "cache_age_seconds": None,
            }
        )
