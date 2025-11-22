import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import Session, select
from datetime import datetime, timezone

from dca_service.models import DCAStrategy
from dca_service.services.metrics_provider import MetricsSource, RealtimeMetricsBackend, CsvMetricsBackend

# Test Strategy Model Updates
def test_strategy_model_includes_day_of_week(session: Session):
    """Test that DCAStrategy model now supports execution_day_of_week"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0,
        execution_frequency="weekly",
        execution_day_of_week="friday",
        execution_time_utc="07:30"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    
    assert strategy.execution_frequency == "weekly"
    assert strategy.execution_day_of_week == "friday"

def test_strategy_day_of_week_nullable(session: Session):
    """Test that execution_day_of_week is optional (for daily frequency)"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5,
        target_btc_amount=1.0,
        execution_frequency="daily",
        # execution_day_of_week omitted
        execution_time_utc="07:30"
    )
    session.add(strategy)
    session.commit()
    session.refresh(strategy)
    
    assert strategy.execution_frequency == "daily"
    assert strategy.execution_day_of_week is None

# Test Metrics Source Labels
@patch('whenshouldubuybitcoin.realtime_check.check_realtime_status')
def test_realtime_backend_label(mock_check_realtime):
    """Test that RealtimeMetricsBackend returns the updated label"""
    mock_check_realtime.return_value = {
        "ahr999": 0.5,
        "realtime_price": 50000.0,
        "timestamp": datetime.now(timezone.utc)
    }
    
    backend = RealtimeMetricsBackend()
    metrics = backend.get_latest_metrics()
    
    assert metrics.source.backend == "realtime"
    assert metrics.source.label == "Binance"

@patch('dca_service.services.metrics_provider.Path')
@patch('builtins.open')
@patch('dca_service.services.metrics_provider.csv.DictReader')
def test_csv_backend_label(mock_csv_reader, mock_open, mock_path):
    """Test that CsvMetricsBackend returns the updated label"""
    # Mock Path
    mock_path.return_value.exists.return_value = True
    
    # Mock CSV Reader
    reader_instance = MagicMock()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = [
        {
            "date": today_str,
            "close_price": "50000.0",
            "ahr999": "0.5"
        }
    ]
    reader_instance.__iter__.side_effect = lambda: iter(data)
    reader_instance.fieldnames = ["date", "close_price", "ahr999"]
    mock_csv_reader.return_value = reader_instance
    
    backend = CsvMetricsBackend()
    metrics = backend.get_latest_metrics()
    
    assert metrics.source.backend == "csv"
    assert metrics.source.label == "Historical CSV"
