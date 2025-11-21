import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, mock_open
from dca_service.services.metrics_provider import get_latest_metrics
from dca_service.config import settings

# Mock CSV content
MOCK_CSV_VALID = """date,close_price,ahr999
2025-11-21,95000.0,0.85
"""

MOCK_CSV_STALE = """date,close_price,ahr999
2020-01-01,10000.0,0.5
"""

MOCK_CSV_MISSING_COLS = """date,other_col
2025-11-21,123
"""

@pytest.fixture
def mock_settings():
    with patch("dca_service.services.metrics_provider.settings") as mock_settings:
        mock_settings.METRICS_CSV_PATH = "dummy.csv"
        mock_settings.METRICS_MAX_AGE_HOURS = 48
        yield mock_settings

def test_get_metrics_valid(mock_settings):
    # Mock file existence and open
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=MOCK_CSV_VALID)):
            # Mock datetime.now to be close to the CSV date
            # CSV date is 2025-11-21 (00:00 UTC)
            # Set "now" to 2025-11-21 12:00 UTC
            mock_now = datetime(2025, 11, 21, 12, 0, tzinfo=timezone.utc)
            with patch("dca_service.services.metrics_provider.datetime") as mock_datetime:
                mock_datetime.now.return_value = mock_now
                mock_datetime.strptime.side_effect = datetime.strptime # Pass through strptime
                
                metrics = get_latest_metrics()
                
                assert metrics is not None
                assert metrics["price_usd"] == 95000.0
                assert metrics["ahr999"] == 0.85
                assert metrics["timestamp"] == datetime(2025, 11, 21, 0, 0, tzinfo=timezone.utc)

def test_get_metrics_stale(mock_settings):
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=MOCK_CSV_STALE)):
            # "Now" is far in the future relative to 2020
            mock_now = datetime(2025, 11, 21, 12, 0, tzinfo=timezone.utc)
            with patch("dca_service.services.metrics_provider.datetime") as mock_datetime:
                mock_datetime.now.return_value = mock_now
                mock_datetime.strptime.side_effect = datetime.strptime
                
                metrics = get_latest_metrics()
                assert metrics is None # Should return None due to staleness

def test_get_metrics_file_not_found(mock_settings):
    with patch("pathlib.Path.exists", return_value=False):
        metrics = get_latest_metrics()
        assert metrics is None

def test_get_metrics_missing_columns(mock_settings):
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=MOCK_CSV_MISSING_COLS)):
            metrics = get_latest_metrics()
            assert metrics is None
