"""Tests for the look-ahead-free comparison of DCA weighting signals."""

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import signal_backtest as sb
from whenshouldubuybitcoin.metrics import calculate_dca_cost, fit_exponential_trend


def _prices(days: int = 1200, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", periods=days, freq="D")
    age = (dates - sb.GENESIS).days.to_numpy(dtype=float)
    trend = 1e-17 * age ** 5.8
    noise = np.exp(np.cumsum(rng.normal(0, 0.03, days)) * 0.3)
    return pd.DataFrame({"date": dates, "close_price": trend * noise})


class TestNoLookAhead:
    def test_causal_trend_matches_a_full_fit_on_the_last_day(self):
        df = _prices()
        causal = sb.causal_power_law_trend(df["date"], df["close_price"], min_points=100)
        full, _, _ = fit_exponential_trend(df)
        assert causal[-1] == pytest.approx(full.iloc[-1], rel=1e-9)

    def test_causal_trend_ignores_future_prices(self):
        df = _prices()
        short = sb.causal_power_law_trend(df["date"][:800], df["close_price"][:800], min_points=100)
        long = sb.causal_power_law_trend(df["date"], df["close_price"], min_points=100)
        np.testing.assert_allclose(short, long[:800], equal_nan=True)

    def test_causal_trend_waits_for_enough_history(self):
        df = _prices()
        trend = sb.causal_power_law_trend(df["date"], df["close_price"], min_points=100)
        assert np.isnan(trend[:99]).all()
        assert np.isfinite(trend[99:]).all()

    def test_expanding_percentile_ignores_future_values(self):
        values = np.array([5.0, 3.0, 8.0, 1.0, 9.0, 2.0, 7.0])
        short = sb.expanding_percentile(values[:4], min_history=2)
        long = sb.expanding_percentile(values, min_history=2)
        np.testing.assert_allclose(short, long[:4], equal_nan=True)

    def test_expanding_percentile_ranks_against_the_past_only(self):
        values = np.array([5.0, 3.0, 8.0, 1.0])
        # share of values so far (including today) at or below today's value
        np.testing.assert_allclose(
            sb.expanding_percentile(values, min_history=1),
            [100.0, 50.0, 100.0, 25.0],
        )

    def test_expanding_percentile_skips_missing_values(self):
        values = np.array([np.nan, 2.0, np.nan, 1.0])
        out = sb.expanding_percentile(values, min_history=1)
        assert np.isnan(out[0]) and np.isnan(out[2])
        assert out[3] == pytest.approx(50.0)


class TestSignals:
    def test_dca_cost_matches_the_site_formula(self):
        df = _prices()
        np.testing.assert_allclose(
            sb.harmonic_dca_cost(df["close_price"].to_numpy()),
            calculate_dca_cost(df["close_price"]).to_numpy(),
            equal_nan=True,
        )

    def test_mayer_multiple_is_price_over_200_day_average(self):
        prices = np.arange(1.0, 301.0)
        mayer = sb.mayer_multiple(prices)
        assert np.isnan(mayer[198])
        assert mayer[199] == pytest.approx(200.0 / np.mean(prices[:200]))

    def test_tier_multipliers_follow_the_site_defaults(self):
        pct = np.array([5.0, 10.0, 20.0, 40.0, 60.0, 95.0, np.nan])
        np.testing.assert_allclose(
            sb.tier_multipliers(pct),
            [5.0, 5.0, 2.0, 1.0, 0.0, 0.0, 1.0],
        )


class TestSimulation:
    def test_plain_dca_spends_every_deposit(self):
        prices = np.array([10.0, 20.0, 40.0])
        result = sb.simulate(prices, np.ones(3), daily_budget=10.0)
        assert result["contributed"] == pytest.approx(30.0)
        assert result["cash"] == pytest.approx(0.0)
        assert result["btc"] == pytest.approx(1.0 + 0.5 + 0.25)
        assert result["wealth"] == pytest.approx(1.75 * 40.0)

    def test_skipped_days_keep_the_cash_for_later(self):
        prices = np.array([10.0, 10.0, 5.0])
        result = sb.simulate(prices, np.array([0.0, 0.0, 5.0]), daily_budget=10.0)
        # 30 deposited; day 3 wants 50 but only 30 is there
        assert result["btc"] == pytest.approx(6.0)
        assert result["cash"] == pytest.approx(0.0)

    def test_unspent_cash_counts_toward_wealth(self):
        prices = np.array([10.0, 20.0])
        result = sb.simulate(prices, np.zeros(2), daily_budget=10.0)
        assert result["btc"] == 0.0
        assert result["wealth"] == pytest.approx(20.0)
        assert result["idle_cash_share"] == pytest.approx(1.0)


class TestComparison:
    def test_compare_reports_every_strategy_with_equal_contributions(self):
        df = _prices(days=1600)
        mvrv = pd.DataFrame({"date": df["date"], "mvrv": df["close_price"] / df["close_price"].rolling(300, min_periods=1).mean()})
        signals = sb.build_signals(df, mvrv, trend_min_points=200, percentile_min_history=200)
        window = signals[signals["date"] >= signals["date"].iloc[600]]
        table = sb.compare_strategies(window, daily_budget=10.0)
        assert list(table["strategy"]) == list(sb.STRATEGIES)
        assert table["contributed"].nunique() == 1
        plain = table.set_index("strategy").loc["plain_dca"]
        assert plain["vs_plain_pct"] == pytest.approx(0.0)

    def test_rolling_windows_cover_the_requested_horizon(self):
        df = _prices(days=1600)
        signals = sb.build_signals(df, None, trend_min_points=200, percentile_min_history=200)
        start = signals["date"].iloc[600]
        windows = sb.rolling_windows(signals, start=start, horizon_days=365, step_days=180)
        assert len(windows) >= 2
        for window in windows:
            assert (window["date"].iloc[-1] - window["date"].iloc[0]).days == 364


def test_compare_can_leave_out_a_strategy_without_its_data():
    df = _prices(days=1600)
    signals = sb.build_signals(df, None, trend_min_points=200, percentile_min_history=200)
    table = sb.compare_strategies(signals.iloc[600:], strategies=["ahr999", "mayer"])
    assert list(table["strategy"]) == ["plain_dca", "ahr999", "mayer"]


def test_causal_trend_has_no_overflow_warnings(recwarn):
    df = _prices()
    sb.causal_power_law_trend(df["date"], df["close_price"], min_points=100)
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_known_rank_is_a_zero_to_one_rank_against_the_past():
    values = pd.Series([5.0, 3.0, 8.0, 1.0])
    np.testing.assert_allclose(sb.known_rank(values, min_history=1), [1.0, 0.5, 1.0, 0.25])
    assert sb.known_rank(values, min_history=3).isna().sum() == 2
