"""Tests for Bitcoin distribution scraper."""
import pytest
from unittest.mock import MagicMock, patch
import requests
from dca_service.services import distribution_scraper
from dca_service.services.distribution_scraper import (
    fetch_distribution,
    fetch_distribution_with_status,
    clear_cache,
    _parse_percentile
)


SAMPLE_DISTRIBUTION_HTML = """
<table>
  <thead>
    <tr>
      <th>Balance, BTC</th>
      <th>Addresses</th>
      <th>% Addresses (Total)</th>
      <th>BTC</th>
      <th>USD</th>
      <th>% BTC (Total)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>[0.1 - 1)</td>
      <td>1000000</td>
      <td>5.99% (7.65%)</td>
      <td>250000</td>
      <td>$19100000000</td>
      <td>1.25%</td>
    </tr>
    <tr>
      <td>[1 - 10)</td>
      <td>200000</td>
      <td>1.40% (1.66%)</td>
      <td>500000</td>
      <td>$38200000000</td>
      <td>2.50%</td>
    </tr>
  </tbody>
</table>
"""


@pytest.fixture(autouse=True)
def reset_distribution_scraper_state():
    clear_cache()
    yield
    clear_cache()


def _mock_distribution_response(html: str = SAMPLE_DISTRIBUTION_HTML):
    response = MagicMock()
    response.text = html
    response.raise_for_status.return_value = None
    return response


def test_parse_percentile():
    """Test parsing percentile from '% Addresses (Total)' column values."""
    # '6.06% (7.77%)' means addresses with balance >= 0.1 BTC = Top 7.77% of holders
    # Preserves original decimal precision (7.77% not 7.8%)
    assert _parse_percentile("6.06% (7.77%)") == "Top 7.77%"
    # '1.44% (1.71%)' means addresses with balance >= 1 BTC = Top 1.71% of holders
    # Preserves original decimal precision (1.71% not 1.7%)
    assert _parse_percentile("1.44% (1.71%)") == "Top 1.71%"
    # '0% (100%)' means everyone = Top 100% (no decimal)
    assert _parse_percentile("0% (100%)") == "Top 100%"
    assert _parse_percentile("invalid") == "Unknown"


def test_fetch_distribution_parses_bitinfocharts_table_response():
    """Test parsing a BitInfoCharts distribution table response."""
    clear_cache()  # Ensure fresh fetch

    with patch("requests.get", return_value=_mock_distribution_response()) as mock_get:
        result = fetch_distribution(use_cache=False)
    
    # Should return a list of dicts
    assert isinstance(result, list)
    assert len(result) > 0
    assert result[0]["tier"] == "[0.1 - 1)"
    assert result[0]["percentile"] == "Top 7.65%"
    mock_get.assert_called_once()
    
    # Check structure
    for item in result:
        assert "tier" in item
        assert "percentile" in item
        assert isinstance(item["tier"], str)
        assert isinstance(item["percentile"], str)


def test_fetch_distribution_caching():
    """Test that caching works correctly."""
    clear_cache()

    with patch("requests.get", return_value=_mock_distribution_response()) as mock_get:
        # First call should fetch from network
        result1 = fetch_distribution(use_cache=True)

        # Second call should use cache (no network call)
        result2 = fetch_distribution(use_cache=True)
    
    # Should return same data
    assert result1 == result2
    mock_get.assert_called_once()


def test_fetch_distribution_does_not_use_stale_cache_on_failure_by_default():
    """Runtime callers should not silently show stale runtime cache as live data."""
    clear_cache()
    
    # First, populate cache with parsed BitInfoCharts data
    with patch("requests.get", return_value=_mock_distribution_response()):
        result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0
    
    with patch("requests.get", side_effect=Exception("Network error")):
        with pytest.raises(ValueError, match="Failed to fetch distribution data"):
            fetch_distribution(use_cache=False)


def test_fetch_distribution_can_use_stale_cache_when_explicitly_enabled():
    """Stale runtime cache is only used when a caller opts into it."""
    clear_cache()

    with patch("requests.get", return_value=_mock_distribution_response()):
        result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0

    with patch("requests.get", side_effect=Exception("Network error")):
        result2 = fetch_distribution(use_cache=False, allow_stale_cache=True)
        assert len(result2) > 0
        assert result2 == result1


def test_fetch_distribution_with_status_labels_stale_cache_on_failure():
    """Status-aware callers can use stale cache without presenting it as live."""
    clear_cache()

    with patch("requests.get", return_value=_mock_distribution_response()):
        result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0

    with patch("requests.get", side_effect=Exception("Network error")):
        snapshot = fetch_distribution_with_status(use_cache=False, allow_stale_cache=True)
        assert snapshot["data"] == result1
        assert snapshot["data_status"] == "stale"
        assert snapshot["source"] == "bitinfocharts_cache"
        assert snapshot["as_of"]


def test_fetch_distribution_raises_on_failure_without_cache_by_default():
    """Runtime callers should not silently show stale static data as if it were live."""
    clear_cache()
    
    with patch("requests.get", side_effect=Exception("Network error")):
        with pytest.raises(ValueError, match="Failed to fetch distribution data"):
            fetch_distribution(use_cache=False)


def test_fetch_distribution_can_use_static_fallback_when_explicitly_enabled():
    """Static bundled data is only used when a caller opts into offline fallback."""
    clear_cache()
    
    with patch("requests.get", side_effect=Exception("Network error")):
        result = fetch_distribution(use_cache=False, allow_static_fallback=True)
        assert len(result) > 0
        tiers = [item['tier'] for item in result]
        assert '[100,000 - 1,000,000)' in tiers


def test_fetch_distribution_timeout_records_sanitized_diagnostics():
    """Timeout diagnostics should help admins without exposing raw socket details."""
    clear_cache()

    raw_timeout = requests.exceptions.Timeout(
        "HTTPSConnectionPool(host='bitinfocharts.com', port=443): Read timed out. raw socket details"
    )
    with patch("requests.get", side_effect=raw_timeout):
        with pytest.raises(ValueError, match="Failed to fetch distribution data"):
            fetch_distribution_with_status(use_cache=False, allow_stale_cache=False)

    diagnostics = distribution_scraper.get_distribution_diagnostics()
    assert diagnostics["last_status"] == "unavailable"
    assert diagnostics["last_error_type"] == "Timeout"
    assert diagnostics["last_error_message_sanitized"] == "Request timed out while contacting BitInfoCharts."
    assert diagnostics["last_http_status"] is None
    assert diagnostics["target_url"] == "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html"
    assert isinstance(diagnostics["elapsed_ms"], int)
    assert "HTTPSConnectionPool" not in diagnostics["last_error_message_sanitized"]
    assert "raw socket details" not in diagnostics["last_error_message_sanitized"]


def test_stale_cache_diagnostics_preserve_live_http_failure_details():
    """Stale fallback should still show admins why the live refresh failed."""
    clear_cache()

    with patch("requests.get", return_value=_mock_distribution_response()):
        fetch_distribution(use_cache=False)

    response = MagicMock()
    response.status_code = 403
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Client Error")

    with patch("requests.get", return_value=response):
        snapshot = fetch_distribution_with_status(use_cache=False, allow_stale_cache=True)

    diagnostics = distribution_scraper.get_distribution_diagnostics()
    assert snapshot["data_status"] == "stale"
    assert diagnostics["last_status"] == "stale"
    assert diagnostics["last_error_type"] == "HTTPError"
    assert diagnostics["last_error_message_sanitized"] == "BitInfoCharts returned HTTP 403."
    assert diagnostics["last_http_status"] == 403
    assert isinstance(diagnostics["elapsed_ms"], int)
