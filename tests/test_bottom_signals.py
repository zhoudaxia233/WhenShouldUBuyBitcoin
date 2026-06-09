"""Tests for on-chain bottom-signal scoring and backtest."""
import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs


# ---------- S1: holder cost ----------

def test_s1_anchor_points():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    assert bs.score_s1_holder_cost(sth, lth, avg, sth) == pytest.approx(5.0)
    assert bs.score_s1_holder_cost(avg, lth, avg, sth) == pytest.approx(10.0)
    assert bs.score_s1_holder_cost(lth, lth, avg, sth) == pytest.approx(15.0)
    assert bs.score_s1_holder_cost(0.8 * lth, lth, avg, sth) == pytest.approx(20.0)
    assert bs.score_s1_holder_cost(1.2 * sth, lth, avg, sth) == pytest.approx(0.0)


def test_s1_clamps_outside_anchors():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    assert bs.score_s1_holder_cost(200_000.0, lth, avg, sth) == pytest.approx(0.0)
    assert bs.score_s1_holder_cost(10_000.0, lth, avg, sth) == pytest.approx(20.0)


def test_s1_monotonic_decreasing_in_price():
    lth, avg, sth = 48_000.0, 53_000.0, 74_000.0
    prices = np.linspace(30_000, 100_000, 50)
    scores = [bs.score_s1_holder_cost(p, lth, avg, sth) for p in prices]
    assert all(a >= b for a, b in zip(scores, scores[1:]))


def test_s1_crossed_lines_do_not_crash():
    # mid-bear regime: STH cost can fall below the average cost line
    score = bs.score_s1_holder_cost(50_000.0, 48_000.0, 60_000.0, 55_000.0)
    assert 0.0 <= score <= 20.0


def test_s1_missing_inputs():
    assert bs.score_s1_holder_cost(None, 1.0, 2.0, 3.0) is None
    assert bs.score_s1_holder_cost(50_000.0, float("nan"), 2.0, 3.0) is None
    assert bs.score_s1_holder_cost(50_000.0, -1.0, 2.0, 3.0) is None


# ---------- sigma helpers / S2 / S3 ----------

def _bimodal_series() -> pd.Series:
    # 100 ones and 100 threes: mean 2.0, population std 1.0
    return pd.Series([1.0] * 100 + [3.0] * 100)


def test_full_sample_deviation():
    d = bs.full_sample_deviation(_bimodal_series())
    assert d.iloc[0] == pytest.approx(-1.0)
    assert d.iloc[-1] == pytest.approx(1.0)


def test_full_sample_deviation_needs_min_observations():
    short = pd.Series([1.0] * 50 + [3.0] * 50)  # 100 < MIN_OBSERVATIONS
    assert bs.full_sample_deviation(short).isna().all()


def test_s2_scores():
    s = bs.score_s2_mvrv(_bimodal_series())
    # d=-1: between -1.5 (20) and 0 (8) -> 8 + (1/1.5)*12 = 16
    assert s.iloc[0] == pytest.approx(16.0)
    # d=+1: between 0 (8) and +2 (0) -> 8 - (1/2)*8 = 4
    assert s.iloc[-1] == pytest.approx(4.0)


def test_s3_scores():
    s = bs.score_s3_supply_loss(_bimodal_series())
    # d=-1 -> 0
    assert s.iloc[0] == pytest.approx(0.0)
    # d=+1: between +0.5 (10) and +2 (20) -> 10 + (0.5/1.5)*10
    assert s.iloc[-1] == pytest.approx(10.0 + 10.0 / 3.0)


# ---------- S4 ----------

def test_s4_percentile_scores():
    s = bs.score_s4_capital_flow(pd.Series(np.arange(1.0, 201.0)))
    assert s.iloc[0] > 19.8  # deepest outflow -> highest score
    assert s.iloc[-1] == pytest.approx(0.0)  # biggest inflow -> 0


def test_s4_needs_min_observations():
    assert bs.score_s4_capital_flow(pd.Series(np.arange(50.0))).isna().all()


# ---------- S5 ----------

def test_s5_anchor_points():
    assert bs.score_s5_fear_greed(10) == pytest.approx(20.0)
    assert bs.score_s5_fear_greed(0) == pytest.approx(20.0)
    assert bs.score_s5_fear_greed(75) == pytest.approx(0.0)
    assert bs.score_s5_fear_greed(100) == pytest.approx(0.0)
    assert bs.score_s5_fear_greed(42.5) == pytest.approx(10.0)
    assert bs.score_s5_fear_greed(None) is None


# ---------- composite ----------

def _scores_frame(n: int = 200) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": 48_000.0,
            "realized_price": 53_000.0,
            "sth_realized_price": 74_000.0,
            "mvrv": [1.0] * (n // 2) + [3.0] * (n - n // 2),
            "supply_loss_pct": [10.0] * (n // 2) + [30.0] * (n - n // 2),
            "realized_cap_change_30d_usd": np.linspace(-4e10, 4e10, n),
            "fear_greed": 10.0,
        }
    )
    prices = pd.DataFrame({"date": dates, "close_price": 60_000.0})
    return bs.compute_bottom_signal_scores(onchain, prices)


def test_compute_scores_has_all_columns_and_composite():
    df = _scores_frame()
    for col in ["s1", "s2", "s3", "s4", "s5", "composite", "zone", "zone_color",
                "s2_dev", "s3_dev", "s4_pctile"]:
        assert col in df.columns
    last = df.iloc[-1]
    expected = last["s1"] + last["s2"] + last["s3"] + last["s4"] + last["s5"]
    assert last["composite"] == pytest.approx(expected)
    assert last["zone"] in {z[2] for z in bs.ZONES}


def test_compute_scores_composite_null_when_any_signal_missing():
    dates = pd.date_range("2024-01-01", periods=200).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": 48_000.0,
            "realized_price": 53_000.0,
            "sth_realized_price": 74_000.0,
            "mvrv": pd.NA,  # S2 unavailable
            "supply_loss_pct": 20.0,
            "realized_cap_change_30d_usd": -1e10,
            "fear_greed": 10.0,
        }
    )
    prices = pd.DataFrame({"date": dates, "close_price": 60_000.0})
    df = bs.compute_bottom_signal_scores(onchain, prices)
    assert df["composite"].isna().all()


def test_zone_for():
    assert bs.zone_for(0)[0] == "Watch"
    assert bs.zone_for(59.9)[0] == "Watch"
    assert bs.zone_for(60)[0] == "Mildly Undervalued"
    assert bs.zone_for(70)[0] == "Undervalued"
    assert bs.zone_for(80)[0] == "Extremely Undervalued"
    assert bs.zone_for(100)[0] == "Extremely Undervalued"
    assert bs.zone_for(None) is None
