import pandas as pd
import pytest

from whenshouldubuybitcoin import daily_report


def _macro_metrics(monkeypatch, scores, forward_returns):
    dates = pd.date_range("2026-09-01", periods=len(scores), freq="D")
    btc_df = pd.DataFrame(
        {
            "date": dates,
            "close_price": 100_000.0,
            "ma_50": 100_000.0,
            "ma_200": 90_000.0,
            "ma_spread": 10_000.0,
            "golden_cross": False,
            "death_cross": False,
        }
    )
    macro_df = pd.DataFrame(
        {
            "date": dates,
            "net_liquidity_bil": 6_000.0,
            "walcl_bil": 7_000.0,
            "tga_bil": 800.0,
            "rrp_bil": 200.0,
            "sofr": 4.0,
            "move": 100.0,
            "hy_oas": 4.0,
        }
    )
    scored_df = pd.DataFrame(
        {
            "date": dates,
            "close_price": 100_000.0,
            "macro_risk_score": scores,
            "fwd_30d_return_pct": forward_returns,
        }
    )
    monkeypatch.setattr(daily_report, "_calc_macro_score_df", lambda *_: scored_df)
    payload = daily_report.build_report_payload(btc_df, macro_df=macro_df)
    return next(
        section["metrics"]
        for section in payload["sections"]
        if section["chart"] == "Macro Risk Score"
    )


def test_macro_hit_rate_excludes_unobserved_returns_and_keeps_latest_score(monkeypatch):
    metrics = _macro_metrics(
        monkeypatch,
        scores=[80, 80, 20, 90, 95],
        forward_returns=[-10.0, 5.0, -3.0, None, None],
    )

    assert metrics["high_risk_hit_rate"] == 50.0
    assert metrics["high_risk_sample_count"] == 2
    assert metrics["validation_through"] == "2026-09-03"
    assert metrics["score"] == 95.0
    assert metrics["regime"] == "high"
    assert metrics["fwd_30d_return"] is None


@pytest.mark.parametrize(
    ("forward_returns", "validation_through"),
    [([0.0, None, None], "2026-09-01"), ([None, None, None], None)],
)
def test_macro_hit_rate_is_unknown_without_mature_high_risk_samples(
    monkeypatch, forward_returns, validation_through
):
    metrics = _macro_metrics(
        monkeypatch, scores=[20, 90, 95], forward_returns=forward_returns
    )

    assert metrics["high_risk_hit_rate"] is None
    assert metrics["high_risk_sample_count"] == 0
    assert metrics["validation_through"] == validation_through
    assert metrics["score"] == 95.0


def test_macro_score_history_uses_only_data_known_each_day():
    import numpy as np

    days = 600
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    i = np.arange(days)
    btc_df = pd.DataFrame({"date": dates, "close_price": 50_000.0 + 100.0 * i})
    macro_df = pd.DataFrame(
        {
            "date": dates,
            "net_liquidity_bil": 6_000.0 + 200.0 * np.sin(i / 40.0),
            "sofr": 4.0 + np.sin(i / 50.0),
            "move": 100.0 + 20.0 * np.sin(i / 30.0),
            "hy_oas": 4.0 + np.sin(i / 60.0),
        }
    )
    early = daily_report._calc_macro_score_df(btc_df.iloc[:400], macro_df.iloc[:400])
    full = daily_report._calc_macro_score_df(btc_df, macro_df)
    compare = early[["date", "macro_risk_score"]].merge(
        full[["date", "macro_risk_score"]], on="date", suffixes=("_early", "_full")
    )
    assert len(compare) == len(early) > 0
    np.testing.assert_allclose(compare["macro_risk_score_early"], compare["macro_risk_score_full"])


def test_macro_score_ranks_use_macro_history_before_btc_prices_start():
    import numpy as np

    macro_dates = pd.date_range("2020-01-01", periods=900, freq="D")
    i = np.arange(900)
    macro_df = pd.DataFrame(
        {
            "date": macro_dates,
            "net_liquidity_bil": 6_000.0 + 200.0 * np.sin(i / 40.0),
            "sofr": 4.0 + np.sin(i / 50.0),
            "move": 100.0 + 20.0 * np.sin(i / 30.0),
            "hy_oas": 4.0 + np.sin(i / 60.0),
        }
    )
    # BTC prices only cover the last 100 macro days
    btc_df = pd.DataFrame({"date": macro_dates[-100:], "close_price": 60_000.0})
    scored = daily_report._calc_macro_score_df(btc_df, macro_df)
    assert len(scored) == 100
