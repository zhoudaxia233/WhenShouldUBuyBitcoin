"""Historical trend metrics must use only prices known on each day."""

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import metrics


def _prices(days: int = 1500, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2014-09-17", periods=days, freq="D")
    age = (dates - pd.Timestamp("2009-01-03")).days.to_numpy(dtype=float)
    noise = np.exp(np.cumsum(rng.normal(0, 0.03, days)) * 0.3)
    return pd.DataFrame({"date": dates, "close_price": 1e-17 * age ** 5.8 * noise})


def test_history_does_not_change_when_future_prices_arrive():
    df = _prices()
    early = metrics.add_trend_metrics(df.iloc[:1000])
    later = metrics.add_trend_metrics(df)
    for column in ("trend_value", "ratio_trend"):
        np.testing.assert_allclose(
            early[column].to_numpy(), later[column].iloc[:1000].to_numpy(), equal_nan=True
        )


def test_today_matches_a_fit_on_all_prices():
    df = _prices()
    full, a, n = metrics.fit_exponential_trend(df)
    out = metrics.add_trend_metrics(df)
    assert out["trend_value"].iloc[-1] == pytest.approx(full.iloc[-1], rel=1e-9)
    # The stored parameters describe today's fit, used for live checks and forecasts
    assert out.attrs["trend_a"] == pytest.approx(a)
    assert out.attrs["trend_b"] == pytest.approx(n)


def test_trend_needs_two_years_of_prices():
    df = _prices()
    out = metrics.add_trend_metrics(df)
    assert out["trend_value"].iloc[: metrics.TREND_MIN_DAYS - 1].isna().all()
    assert out["trend_value"].iloc[metrics.TREND_MIN_DAYS - 1:].notna().all()


def test_double_undervaluation_history_uses_the_trend_known_then():
    df = _prices()
    early = metrics.compute_valuation_metrics(df.iloc[:1000].copy())
    later = metrics.compute_valuation_metrics(df.copy())
    np.testing.assert_array_equal(
        early["is_double_undervalued"].to_numpy(), later["is_double_undervalued"].iloc[:1000].to_numpy()
    )
    np.testing.assert_allclose(
        early["ahr999"].to_numpy(), later["ahr999"].iloc[:1000].to_numpy(), equal_nan=True
    )
