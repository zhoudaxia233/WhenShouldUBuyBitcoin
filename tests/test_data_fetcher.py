"""
Tests for data_fetcher module, specifically for real-time price fetching.
"""

import sys
from pathlib import Path

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

import pytest
import pandas as pd
from unittest.mock import Mock, patch
from datetime import datetime

from whenshouldubuybitcoin.data_fetcher import (
    get_realtime_btc_price,
    fetch_fred_series_csv_public,
    fetch_macro_liquidity_indicators,
)


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
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDC",
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
                json=lambda: {"data": {"rates": {"USD": "51000.75"}}},
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
        mock_coinbase_response.raise_for_status.side_effect = Exception(
            "Coinbase error"
        )
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
        mock_coinbase_response.raise_for_status.side_effect = Exception(
            "Coinbase error"
        )
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


class TestFredPublicCsvFetcher:
    """Test cases for public FRED CSV fetching without API key."""

    @patch("whenshouldubuybitcoin.data_fetcher.requests")
    def test_fetch_fred_series_csv_public_parses_and_filters(self, mock_requests):
        """Should parse CSV and drop invalid numeric rows."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.text = (
            "observation_date,SOFR\n"
            "2024-01-01,5.30\n"
            "2024-01-02,.\n"
            "2024-01-03,5.31\n"
        )
        mock_requests.get.return_value = mock_response

        df = fetch_fred_series_csv_public("SOFR", start_date="2024-01-01")

        assert list(df.columns) == ["date", "close_price"]
        assert len(df) == 2
        assert float(df["close_price"].iloc[0]) == 5.30
        assert float(df["close_price"].iloc[1]) == 5.31


class TestMacroLiquidityIndicators:
    """Test cases for macro liquidity indicator aggregation."""

    @patch("whenshouldubuybitcoin.data_fetcher.yf.Ticker")
    @patch("whenshouldubuybitcoin.data_fetcher.fetch_fred_series_csv_public")
    def test_fetch_macro_liquidity_indicators_builds_net_liquidity(
        self, mock_fetch_fred_csv, mock_ticker
    ):
        """Should merge all series and compute net liquidity in billion USD."""
        base_dates = [datetime(2024, 1, 1), datetime(2024, 1, 2)]

        def fred_side_effect(series_id, days=None, start_date=None):
            series_values = {
                "WALCL": [900000.0, 901000.0],  # million USD
                "WTREGEN": [80000.0, 81000.0],  # million USD
                "RRPONTSYD": [500.0, 490.0],    # billion USD
                "SOFR": [5.3, 5.29],
                "BAMLH0A0HYM2": [3.5, 3.45],
            }
            return pd.DataFrame(
                {"date": base_dates, "close_price": series_values[series_id]}
            )

        mock_fetch_fred_csv.side_effect = fred_side_effect

        move_df = pd.DataFrame(
            {
                "Close": [120.0, 121.0],
            },
            index=pd.to_datetime(base_dates),
        )
        mock_ticker.return_value.history.return_value = move_df

        result = fetch_macro_liquidity_indicators(start_date="2024-01-01")

        assert "net_liquidity_bil" in result.columns
        assert "sofr" in result.columns
        assert "hy_oas" in result.columns
        assert "move" in result.columns

        latest = result.dropna(subset=["net_liquidity_bil"]).iloc[-1]
        # 901000/1000 - 81000/1000 - 490 = 330
        assert round(float(latest["net_liquidity_bil"]), 2) == 330.0
