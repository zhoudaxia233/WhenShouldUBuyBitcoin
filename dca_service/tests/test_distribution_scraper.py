"""Tests for Bitcoin distribution scraper."""
import pytest
from dca_service.services.distribution_scraper import (
    fetch_distribution,
    clear_cache,
    _parse_percentile
)


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


def test_fetch_distribution_live():
    """Test fetching live distribution data from BitInfoCharts."""
    clear_cache()  # Ensure fresh fetch
    
    # This makes a real network call
    result = fetch_distribution(use_cache=False)
    
    # Should return a list of dicts
    assert isinstance(result, list)
    assert len(result) >0
    
    # Check structure
    for item in result:
        assert "tier" in item
        assert "percentile" in item
        assert isinstance(item["tier"], str)
        assert isinstance(item["percentile"], str)


def test_fetch_distribution_caching():
    """Test that caching works correctly."""
    clear_cache()
    
    # First call should fetch from network
    result1 = fetch_distribution(use_cache=True)
    
    # Second call should use cache (no network call)
    result2 = fetch_distribution(use_cache=True)
    
    # Should return same data
    assert result1 == result2


def test_fetch_distribution_does_not_use_stale_cache_on_failure_by_default():
    """Runtime callers should not silently show stale runtime cache as live data."""
    from unittest.mock import patch
    
    clear_cache()
    
    # First, populate cache with real data
    result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0
    
    with patch('requests.get', side_effect=Exception("Network error")):
        with pytest.raises(ValueError, match="Failed to fetch distribution data"):
            fetch_distribution(use_cache=False)


def test_fetch_distribution_can_use_stale_cache_when_explicitly_enabled():
    """Stale runtime cache is only used when a caller opts into it."""
    from unittest.mock import patch

    clear_cache()

    result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0

    with patch('requests.get', side_effect=Exception("Network error")):
        result2 = fetch_distribution(use_cache=False, allow_stale_cache=True)
        assert len(result2) > 0
        assert result2 == result1


def test_fetch_distribution_raises_on_failure_without_cache_by_default():
    """Runtime callers should not silently show stale static data as if it were live."""
    from unittest.mock import patch
    
    clear_cache()
    
    with patch('requests.get', side_effect=Exception("Network error")):
        with pytest.raises(ValueError, match="Failed to fetch distribution data"):
            fetch_distribution(use_cache=False)


def test_fetch_distribution_can_use_static_fallback_when_explicitly_enabled():
    """Static bundled data is only used when a caller opts into offline fallback."""
    from unittest.mock import patch
    
    clear_cache()
    
    with patch('requests.get', side_effect=Exception("Network error")):
        result = fetch_distribution(use_cache=False, allow_static_fallback=True)
        assert len(result) > 0
        tiers = [item['tier'] for item in result]
        assert '[100,000 - 1,000,000)' in tiers
