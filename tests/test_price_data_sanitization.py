"""
Regression tests for incomplete BTC price rows (for example, an in-progress
Yahoo Finance daily candle with volume but no final close).
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from whenshouldubuybitcoin.data_fetcher import fetch_btc_history
from whenshouldubuybitcoin.metrics import (
    compute_valuation_metrics,
    get_dca_summary,
    get_double_undervaluation_summary,
    get_trend_summary,
)
from whenshouldubuybitcoin.persistence import load_existing_metrics, save_metrics


@patch("whenshouldubuybitcoin.data_fetcher.yf.Ticker")
def test_fetch_btc_history_drops_incomplete_rows(mock_ticker):
    history = pd.DataFrame(
        {
            "Close": [100.0, 110.0, np.nan],
            "Volume": [10, 20, 30],
        },
        index=pd.to_datetime(["2026-03-14", "2026-03-15", "2026-03-16"]),
    )
    history.index.name = "Date"
    mock_ticker.return_value.history.return_value = history

    df = fetch_btc_history(days=3)

    assert list(df["date"].dt.strftime("%Y-%m-%d")) == ["2026-03-14", "2026-03-15"]
    assert df["close_price"].tolist() == [100.0, 110.0]


def test_save_metrics_drops_invalid_close_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "whenshouldubuybitcoin.persistence.get_data_dir", lambda: tmp_path
    )

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-03-15", "2026-03-16"]),
            "close_price": [72789.91, np.nan],
            "dca_cost": [90000.0, 90100.0],
            "ratio_dca": [0.81, np.nan],
            "trend_value": [85000.0, 85100.0],
            "ratio_trend": [0.86, np.nan],
            "is_double_undervalued": [True, False],
            "ahr999": [0.70, np.nan],
        }
    )

    assert save_metrics(df)

    saved = pd.read_csv(tmp_path / "btc_metrics.csv")
    assert len(saved) == 1
    assert saved["date"].tolist() == ["2026-03-15"]
    assert saved["close_price"].tolist() == [72789.91]


def test_load_existing_metrics_drops_invalid_close_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "whenshouldubuybitcoin.persistence.get_data_dir", lambda: tmp_path
    )
    (tmp_path / "btc_metrics.csv").write_text(
        "date,close_price\n"
        "2026-03-15,72789.91\n"
        "2026-03-16,\n"
    )

    df = load_existing_metrics()

    assert df is not None
    assert list(df["date"].dt.strftime("%Y-%m-%d")) == ["2026-03-15"]
    assert df["close_price"].tolist() == [72789.91]


def test_metric_summaries_skip_trailing_nan_close_row():
    price_df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=260, freq="D"),
            "close_price": np.linspace(40000.0, 80000.0, 260),
        }
    )
    expected_latest_price = float(price_df["close_price"].iloc[-2])
    price_df.loc[price_df.index[-1], "close_price"] = np.nan

    metrics_df = compute_valuation_metrics(price_df, dca_window=200)

    dca_summary = get_dca_summary(metrics_df)
    trend_summary = get_trend_summary(metrics_df)
    double_uv_summary = get_double_undervaluation_summary(metrics_df)

    assert dca_summary["latest_price"] == expected_latest_price
    assert trend_summary["latest_price"] == expected_latest_price
    assert trend_summary["power_law_exponent"] is not None
    assert double_uv_summary["current_price"] == expected_latest_price
