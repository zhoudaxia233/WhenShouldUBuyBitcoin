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
