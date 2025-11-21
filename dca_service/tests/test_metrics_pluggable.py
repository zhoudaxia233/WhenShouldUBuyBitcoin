import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Ensure src is in path
sys.path.append("src")
# Add parent project src for whenshouldubuybitcoin
sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

from dca_service.services.metrics_provider import (
    CsvMetricsBackend, 
    RealtimeMetricsBackend, 
    get_latest_metrics, 
    Metrics,
    COL_DATE, COL_PRICE, COL_AHR999
)
from dca_service.config import settings

# Explicitly import to ensure it's loaded and path is correct
import whenshouldubuybitcoin.realtime_check

# --- Fixtures ---

@pytest.fixture
def mock_csv_file(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    p = d / "metrics.csv"
    
    # Create a valid CSV
    content = f"{COL_DATE},{COL_PRICE},{COL_AHR999}\n"
    content += "2023-01-01,10000.0,0.5\n"
    content += f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')},50000.0,0.8\n"
    p.write_text(content)
    return p

@pytest.fixture
def mock_realtime_check():
    with patch("whenshouldubuybitcoin.realtime_check.check_realtime_status") as mock:
        yield mock

# --- CSV Backend Tests ---

def test_csv_backend_valid(mock_csv_file):
    settings.METRICS_CSV_PATH = str(mock_csv_file)
    backend = CsvMetricsBackend()
    metrics = backend.get_latest_metrics()
    
    assert metrics.price_usd == 50000.0
    assert metrics.ahr999 == 0.8
    assert metrics.source == "csv"
    assert metrics.timestamp.date() == datetime.now(timezone.utc).date()

def test_csv_backend_stale(tmp_path):
    p = tmp_path / "stale.csv"
    # Date older than 48h
    old_date = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime('%Y-%m-%d')
    content = f"{COL_DATE},{COL_PRICE},{COL_AHR999}\n{old_date},50000.0,0.8\n"
    p.write_text(content)
    
    settings.METRICS_CSV_PATH = str(p)
    backend = CsvMetricsBackend()
    
    with pytest.raises(ValueError, match="Metrics are stale"):
        backend.get_latest_metrics()

def test_csv_backend_missing_file():
    settings.METRICS_CSV_PATH = "/non/existent/path.csv"
    backend = CsvMetricsBackend()
    with pytest.raises(FileNotFoundError):
        backend.get_latest_metrics()

# --- Realtime Backend Tests ---

def test_realtime_backend_valid(mock_realtime_check):
    now = datetime.now(timezone.utc)
    mock_realtime_check.return_value = {
        "ahr999": 0.45,
        "realtime_price": 60000.0,
        "timestamp": now
    }
    
    backend = RealtimeMetricsBackend()
    metrics = backend.get_latest_metrics()
    
    assert metrics.ahr999 == 0.45
    assert metrics.price_usd == 60000.0
    assert metrics.source == "realtime"
    assert metrics.timestamp == now

def test_realtime_backend_failure(mock_realtime_check):
    mock_realtime_check.return_value = None
    backend = RealtimeMetricsBackend()
    with pytest.raises(ValueError, match="returned no data"):
        backend.get_latest_metrics()

def test_realtime_backend_stale(mock_realtime_check):
    old_time = datetime.now(timezone.utc) - timedelta(hours=50)
    mock_realtime_check.return_value = {
        "ahr999": 0.45,
        "realtime_price": 60000.0,
        "timestamp": old_time
    }
    backend = RealtimeMetricsBackend()
    with pytest.raises(ValueError, match="Realtime metrics are stale"):
        backend.get_latest_metrics()

# --- Fallback Logic Tests ---

def test_fallback_logic_success(mock_realtime_check, mock_csv_file):
    # Setup: Realtime fails, CSV succeeds
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = True
    settings.METRICS_CSV_PATH = str(mock_csv_file)
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    
    assert metrics_dict is not None
    assert metrics_dict["source"] == "csv (fallback)"
    assert metrics_dict["price_usd"] == 50000.0

def test_fallback_logic_disabled(mock_realtime_check):
    # Setup: Realtime fails, Fallback disabled
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = False
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    assert metrics_dict is None

def test_fallback_logic_both_fail(mock_realtime_check):
    # Setup: Realtime fails, CSV fails (invalid path)
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = True
    settings.METRICS_CSV_PATH = "/non/existent/path.csv"
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    assert metrics_dict is None
