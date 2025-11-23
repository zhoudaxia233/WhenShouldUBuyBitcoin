"""
Comprehensive metrics tests covering CSV backend, realtime backend, fallback logic,
and integration with DCA engine.

Merged from: test_metrics.py, test_metrics_pluggable.py, test_metrics_source_and_transactions.py
"""
import pytest
from unittest.mock import patch, mock_open, MagicMock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlmodel import Session

from dca_service.services.metrics_provider import (
    CsvMetricsBackend,
    RealtimeMetricsBackend,
    get_latest_metrics,
    Metrics,
    COL_DATE, COL_PRICE, COL_AHR999
)
from dca_service.config import settings
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_csv_file(tmp_path):
    """Create a temporary CSV file with valid recent data"""
    d = tmp_path / "data"
    d.mkdir()
    p = d / "metrics.csv"
    
    content = f"{COL_DATE},{COL_PRICE},{COL_AHR999}\n"
    content += "2023-01-01,10000.0,0.5\n"
    content += f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')},50000.0,0.8\n"
    p.write_text(content)
    return p

@pytest.fixture
def strategy(session: Session):
    """Standard DCA strategy fixture"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0,
        execution_frequency="daily",
        execution_time_utc="07:30"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    return strategy

# ============================================================================
# CSV BACKEND TESTS
# ============================================================================

def test_csv_backend_valid(mock_csv_file):
    """Test CSV backend with valid recent data"""
    settings.METRICS_CSV_PATH = str(mock_csv_file)
    backend = CsvMetricsBackend()
    metrics = backend.get_latest_metrics()
    
    assert metrics.price_usd == 50000.0
    assert metrics.ahr999 == 0.8
    assert metrics.source.backend == "csv"
    assert metrics.timestamp.date() == datetime.now(timezone.utc).date()

def test_csv_backend_stale(tmp_path):
    """Test CSV backend rejects stale data (>48h old)"""
    p = tmp_path / "stale.csv"
    old_date = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime('%Y-%m-%d')
    content = f"{COL_DATE},{COL_PRICE},{COL_AHR999}\n{old_date},50000.0,0.8\n"
    p.write_text(content)
    
    settings.METRICS_CSV_PATH = str(p)
    backend = CsvMetricsBackend()
    
    with pytest.raises(ValueError, match="Metrics are stale"):
        backend.get_latest_metrics()

def test_csv_backend_missing_file():
    """Test CSV backend handles missing file gracefully"""
    settings.METRICS_CSV_PATH = "/non/existent/path.csv"
    backend = CsvMetricsBackend()
    with pytest.raises(FileNotFoundError):
        backend.get_latest_metrics()

def test_csv_backend_missing_columns(tmp_path):
    """Test CSV backend handles missing required columns"""
    p = tmp_path / "bad.csv"
    content = "date,other_col\n2025-11-21,123\n"
    p.write_text(content)
    
    settings.METRICS_CSV_PATH = str(p)
    backend = CsvMetricsBackend()
    
    # Should raise error due to missing columns
    with pytest.raises((KeyError, ValueError)):
        backend.get_latest_metrics()

# ============================================================================
# REALTIME BACKEND TESTS
# ============================================================================

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_realtime_backend_valid(mock_realtime_check):
    """Test realtime backend with valid data"""
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
    assert metrics.source.backend == "realtime"
    assert metrics.timestamp == now

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_realtime_backend_failure(mock_realtime_check):
    """Test realtime backend handles API failure"""
    mock_realtime_check.return_value = None
    backend = RealtimeMetricsBackend()
    with pytest.raises(ValueError, match="returned no data"):
        backend.get_latest_metrics()

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_realtime_backend_stale(mock_realtime_check):
    """Test realtime backend rejects stale data"""
    old_time = datetime.now(timezone.utc) - timedelta(hours=50)
    mock_realtime_check.return_value = {
        "ahr999": 0.45,
        "realtime_price": 60000.0,
        "timestamp": old_time
    }
    backend = RealtimeMetricsBackend()
    with pytest.raises(ValueError, match="Realtime metrics are stale"):
        backend.get_latest_metrics()

# ============================================================================
# FALLBACK LOGIC TESTS
# ============================================================================

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_fallback_to_csv_on_realtime_failure(mock_realtime_check, mock_csv_file):
    """Test fallback from realtime to CSV when API fails"""
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = True
    settings.METRICS_CSV_PATH = str(mock_csv_file)
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    
    assert metrics_dict is not None
    # Fallback may or may not add "(fallback)" to source field depending on implementation
    assert "csv" in metrics_dict.get("source", "")
    assert metrics_dict["price_usd"] == 50000.0

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_fallback_disabled(mock_realtime_check):
    """Test that fallback respects disabled setting"""
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = False
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    assert metrics_dict is None

@patch("whenshouldubuybitcoin.realtime_check.check_realtime_status")
def test_fallback_both_fail(mock_realtime_check):
    """Test when both realtime and CSV fallback fail"""
    settings.METRICS_BACKEND = "realtime"
    settings.METRICS_FALLBACK_TO_CSV = True
    settings.METRICS_CSV_PATH = "/non/existent/path.csv"
    
    mock_realtime_check.side_effect = Exception("API Error")
    
    metrics_dict = get_latest_metrics()
    assert metrics_dict is None

# ============================================================================
# INTEGRATION WITH DCA ENGINE
# ============================================================================

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_metrics_source_in_dca_preview(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that DCA preview includes metrics_source with backend and label"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file)"
    }
    
    decision = calculate_dca_decision(session)
    
    assert "metrics_source" in decision.model_dump()
    assert isinstance(decision.metrics_source, dict)
    assert "backend" in decision.metrics_source
    assert "label" in decision.metrics_source
    assert decision.metrics_source["backend"] == "csv"
    assert "CSV" in decision.metrics_source["label"]

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_metrics_source_when_unavailable(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test metrics_source is present even when metrics unavailable"""
    mock_metrics.return_value = None
    
    decision = calculate_dca_decision(session)
    
    assert decision.can_execute is False
    assert "metrics_source" in decision.model_dump()
    assert decision.metrics_source["backend"] == "unknown"
    assert decision.metrics_source["label"] == "Unknown"

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_realtime_metrics_source_label(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that realtime metrics source is properly labeled"""
    mock_metrics.return_value = {
        "ahr999": 0.7,
        "price_usd": 95000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "realtime",
        "source_label": "Realtime (WhenShouldUBuyBitcoin + Binance)"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.metrics_source["backend"] == "realtime"
    assert "Realtime" in decision.metrics_source["label"]
    assert "Binance" in decision.metrics_source["label"]

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_fallback_metrics_source_label(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that fallback to CSV is properly labeled"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file) [fallback]"
    }
    
    decision = calculate_dca_decision(session)
    
    assert decision.metrics_source["backend"] == "csv"
    assert "[fallback]" in decision.metrics_source["label"]

# ============================================================================
# TRANSACTION METRICS FIELDS
# ============================================================================

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_transaction_populates_metrics_fields(mock_metrics, session: Session, strategy: DCAStrategy):
    """Test that transactions populate new metrics tracking fields"""
    mock_metrics.return_value = {
        "ahr999": 0.6,
        "price_usd": 90000.0,
        "timestamp": datetime.now(timezone.utc),
        "source": "csv",
        "source_label": "CSV (WhenShouldUBuyBitcoin metrics file)"
    }
    
    decision = calculate_dca_decision(session)
    assert decision.can_execute is True
    
    # Simulate transaction creation
    btc_amount = decision.suggested_amount_usd / decision.price_usd
    
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=decision.suggested_amount_usd,
        btc_amount=btc_amount,
        price=decision.price_usd,
        ahr999=decision.ahr999_value,
        notes="SIMULATED",
        intended_amount_usd=decision.suggested_amount_usd,
        executed_amount_usd=decision.suggested_amount_usd,
        executed_amount_btc=btc_amount,
        avg_execution_price_usd=decision.price_usd,
        fee_amount=0.0,
        fee_asset=None
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    # Verify all fields populated
    assert transaction.intended_amount_usd == decision.suggested_amount_usd
    assert transaction.executed_amount_usd == decision.suggested_amount_usd
    assert transaction.executed_amount_btc == btc_amount
    assert transaction.avg_execution_price_usd == decision.price_usd
    assert transaction.fee_amount == 0.0

def test_transaction_backwards_compatibility(session: Session):
    """Test that old transactions without new fields still work"""
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.5,
        notes="Test"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    # New fields should be None (nullable)
    assert transaction.intended_amount_usd is None
    assert transaction.executed_amount_usd is None
    assert transaction.executed_amount_btc is None
    assert transaction.avg_execution_price_usd is None
    assert transaction.fee_amount is None
    assert transaction.fee_asset is None
