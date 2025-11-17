"""
Tests for data_fetcher module, specifically for real-time price fetching.
"""

import sys
from pathlib import Path

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from whenshouldubuybitcoin.data_fetcher import get_realtime_btc_price


class TestGetRealtimeBtcPrice:
    """Test cases for get_realtime_btc_price function."""

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_binance_success(self, mock_requests):
        """Test successful price fetch from Binance."""
        # Mock Binance API response
        mock_response = Mock()
        mock_response.json.return_value = {"price": "50000.50"}
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response

        # Call function
        timestamp, price = get_realtime_btc_price()

        # Assertions
        assert isinstance(timestamp, datetime)
        assert price == 50000.50
        assert 1000 < price < 200000  # Price validation
        mock_requests.get.assert_called_once_with(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=5,
        )

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_binance_fallback_to_coinbase(self, mock_requests):
        """Test fallback to Coinbase when Binance fails."""
        # Mock Binance failure
        mock_binance_response = Mock()
        mock_binance_response.raise_for_status.side_effect = Exception("Binance error")
        mock_requests.get.side_effect = [
            mock_binance_response,  # First call (Binance) fails
            Mock(  # Second call (Coinbase) succeeds
                json=lambda: {
                    "data": {"rates": {"USD": "51000.75"}}
                },
                raise_for_status=Mock(),
            ),
        ]

        # Call function
        timestamp, price = get_realtime_btc_price()

        # Assertions
        assert isinstance(timestamp, datetime)
        assert price == 51000.75
        assert 1000 < price < 200000
        assert mock_requests.get.call_count == 2

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_coinbase_success(self, mock_requests):
        """Test successful price fetch from Coinbase."""
        # Mock Binance failure, Coinbase success
        mock_binance_response = Mock()
        mock_binance_response.raise_for_status.side_effect = Exception("Binance error")

        mock_coinbase_response = Mock()
        mock_coinbase_response.json.return_value = {
            "data": {"rates": {"USD": "52000.25"}}
        }
        mock_coinbase_response.raise_for_status = Mock()

        mock_requests.get.side_effect = [mock_binance_response, mock_coinbase_response]

        # Call function
        timestamp, price = get_realtime_btc_price()

        # Assertions
        assert isinstance(timestamp, datetime)
        assert price == 52000.25
        assert 1000 < price < 200000

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_invalid_price_too_low(self, mock_requests):
        """Test rejection of price that's too low."""
        # Mock Binance with invalid price
        mock_response = Mock()
        mock_response.json.return_value = {"price": "500"}  # Too low
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response

        # Should fallback to Coinbase, but if that also fails, raise error
        mock_coinbase_response = Mock()
        mock_coinbase_response.raise_for_status.side_effect = Exception("Coinbase error")
        mock_requests.get.side_effect = [mock_response, mock_coinbase_response]

        # Should raise exception when all sources fail
        with pytest.raises(Exception, match="Failed to fetch real-time price"):
            get_realtime_btc_price()

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_invalid_price_too_high(self, mock_requests):
        """Test rejection of price that's too high."""
        # Mock Binance with invalid price
        mock_response = Mock()
        mock_response.json.return_value = {"price": "500000"}  # Too high
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response

        # Mock Coinbase also fails
        mock_coinbase_response = Mock()
        mock_coinbase_response.raise_for_status.side_effect = Exception("Coinbase error")
        mock_requests.get.side_effect = [mock_response, mock_coinbase_response]

        # Should raise exception
        with pytest.raises(Exception, match="Failed to fetch real-time price"):
            get_realtime_btc_price()

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_all_sources_fail(self, mock_requests):
        """Test behavior when all sources fail."""
        # Mock both sources failing
        mock_requests.get.side_effect = [
            Exception("Binance network error"),
            Exception("Coinbase network error"),
        ]

        # Should raise exception
        with pytest.raises(Exception, match="Failed to fetch real-time price"):
            get_realtime_btc_price()

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_binance_invalid_response_format(self, mock_requests):
        """Test handling of invalid response format from Binance."""
        # Mock Binance with invalid response
        mock_response = Mock()
        mock_response.json.return_value = {"error": "Invalid request"}
        mock_response.raise_for_status = Mock()
        mock_requests.get.return_value = mock_response

        # Mock Coinbase success
        mock_coinbase_response = Mock()
        mock_coinbase_response.json.return_value = {
            "data": {"rates": {"USD": "53000.00"}}
        }
        mock_coinbase_response.raise_for_status = Mock()
        mock_requests.get.side_effect = [mock_response, mock_coinbase_response]

        # Should fallback to Coinbase
        timestamp, price = get_realtime_btc_price()
        assert price == 53000.00

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_coinbase_invalid_response_format(self, mock_requests):
        """Test handling of invalid response format from Coinbase."""
        # Mock Binance failure
        mock_binance_response = Mock()
        mock_binance_response.raise_for_status.side_effect = Exception("Binance error")

        # Mock Coinbase with invalid response
        mock_coinbase_response = Mock()
        mock_coinbase_response.json.return_value = {"error": "Invalid request"}
        mock_coinbase_response.raise_for_status = Mock()

        mock_requests.get.side_effect = [mock_binance_response, mock_coinbase_response]

        # Should raise exception
        with pytest.raises(Exception, match="Failed to fetch real-time price"):
            get_realtime_btc_price()

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_requests_not_installed(self, mock_requests_module):
        """Test behavior when requests library is not installed."""
        # Simulate requests being None (not installed)
        import whenshouldubuybitcoin.data_fetcher as data_fetcher_module
        original_requests = data_fetcher_module.requests
        data_fetcher_module.requests = None

        try:
            # Should raise ImportError
            with pytest.raises(ImportError, match="requests library is required"):
                get_realtime_btc_price()
        finally:
            # Restore original requests
            data_fetcher_module.requests = original_requests

