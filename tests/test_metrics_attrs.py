"""
Regression tests for metrics pipeline metadata (DataFrame.attrs) preservation.
"""

import sys
from pathlib import Path

import pandas as pd

# Add src directory to Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from whenshouldubuybitcoin.metrics import add_rsi_metrics, add_volume_relative_metrics


def _sample_df(n: int = 100) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "close_price": [40000 + i * 10 for i in range(n)],
            "volume": [1000 + (i % 7) * 100 for i in range(n)],
        }
    )
    df.attrs["trend_a"] = 1.23
    df.attrs["trend_b"] = 4.56
    return df


def test_add_rsi_metrics_preserves_dataframe_attrs():
    df = _sample_df()
    out = add_rsi_metrics(df)

    assert out.attrs.get("trend_a") == 1.23
    assert out.attrs.get("trend_b") == 4.56


def test_add_volume_relative_metrics_preserves_dataframe_attrs():
    df = _sample_df()
    out = add_volume_relative_metrics(df)

    assert out.attrs.get("trend_a") == 1.23
    assert out.attrs.get("trend_b") == 4.56

