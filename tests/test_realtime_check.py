"""
Tests for realtime_check module, especially resilience when trend metadata is missing.
"""

import sys
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

import pandas as pd

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from whenshouldubuybitcoin.realtime_check import check_realtime_status


def _build_realtime_df(rows: int = 260) -> pd.DataFrame:
    """Build a synthetic dataset with required columns for realtime_check."""
    dates = pd.date_range("2025-01-01", periods=rows, freq="D")
    # Smoothly increasing prices to keep denominators sane
    close = pd.Series([40000.0 + i * 20.0 for i in range(rows)], dtype=float)
    # Synthetic trend series (positive and smooth)
    trend = pd.Series([35000.0 + i * 18.0 for i in range(rows)], dtype=float)
    ratio_dca = close / close.rolling(30, min_periods=1).mean()
    ratio_trend = close / trend

    df = pd.DataFrame(
        {
            "date": dates,
            "close_price": close,
            "trend_value": trend,
            "ratio_dca": ratio_dca,
            "ratio_trend": ratio_trend,
        }
    )
    # Explicitly simulate the broken metadata case
    df.attrs["trend_a"] = None
    df.attrs["trend_b"] = None
    return df


@patch("whenshouldubuybitcoin.realtime_check.calculate_ahr999_percentile_below_one", return_value=50.0)
@patch("whenshouldubuybitcoin.realtime_check.calculate_ahr999_percentile", return_value=50.0)
@patch("whenshouldubuybitcoin.realtime_check.get_ahr999_zone", return_value={"label": "test"})
@patch("whenshouldubuybitcoin.realtime_check.get_realtime_btc_price")
@patch("whenshouldubuybitcoin.realtime_check.load_existing_metrics")
def test_realtime_check_derives_trend_params_when_metadata_missing(
    mock_load_existing,
    mock_get_realtime_price,
    _mock_zone,
    _mock_pct,
    _mock_pct_below_one,
):
    """
    Core regression test:
    realtime_check should still work when btc_metadata.json lost trend_a/trend_b.
    """
    df = _build_realtime_df()
    mock_load_existing.return_value = df
    mock_get_realtime_price.return_value = (datetime(2026, 2, 22, 12, 0, 0), 67414.71)

    result = check_realtime_status(verbose=False)

    assert result is not None
    assert result["realtime_price"] == 67414.71
    assert result["trend_value"] > 0
    assert result["ahr999"] > 0
    # Fallback should backfill attrs on the in-memory DataFrame for downstream use
    assert df.attrs.get("trend_a") is not None
    assert df.attrs.get("trend_b") is not None


@patch("whenshouldubuybitcoin.realtime_check.get_realtime_btc_price")
@patch("whenshouldubuybitcoin.realtime_check.load_existing_metrics")
def test_realtime_check_returns_none_if_no_trend_metadata_and_no_trend_series(
    mock_load_existing,
    mock_get_realtime_price,
):
    """
    If both metadata and trend_value series are unavailable, function should fail gracefully.
    """
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    df = pd.DataFrame({"date": dates, "close_price": [50000.0] * 260})
    df.attrs["trend_a"] = None
    df.attrs["trend_b"] = None

    mock_load_existing.return_value = df
    mock_get_realtime_price.return_value = (datetime(2026, 2, 22, 12, 0, 0), 67414.71)

    result = check_realtime_status(verbose=False)
    assert result is None

