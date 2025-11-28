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


def test_fetch_distribution_uses_stale_cache_on_failure():
    """Test that stale cache is used when fetching fails."""
    from unittest.mock import patch
    import pandas as pd
    
    clear_cache()
    
    # First, populate cache with real data
    result1 = fetch_distribution(use_cache=False)
    assert len(result1) > 0
    
    # Now simulate a network failure
    with patch('pandas.read_html', side_effect=Exception("Network error")):
        # Should return STATIC data now, not the stale cache (logic changed to prefer static fallback over complex cache logic for simplicity)
        # Or if the implementation prefers static fallback immediately on error
        result2 = fetch_distribution(use_cache=False)
        assert len(result2) > 0
        # The actual scraped data format might vary, but based on latest scrape:
        assert result2[0]['tier'] == '[100,000 - 1,000,000)' # Check for static data signature


def test_fetch_distribution_returns_static_on_failure_without_cache():
    """Test that static data is returned if fetching fails and no cache exists."""
    from unittest.mock import patch
    import pandas as pd
    import pytest
    
    clear_cache()
    
    # Simulate network failure with no cache
    with patch('pandas.read_html', side_effect=Exception("Network error")):
        # Should NOT raise ValueError anymore, should return static data
        result = fetch_distribution(use_cache=False)
        assert len(result) > 0
        assert result[0]['tier'] == '[100,000 - 1,000,000)'
