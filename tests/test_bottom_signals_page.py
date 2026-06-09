"""Tests for the prerendered bottom-signals dashboard page."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs
from whenshouldubuybitcoin import bottom_signals_page as page


def test_status_for_score_bands():
    assert page._status_for_score(None) == ("No data", "#71717a")
    assert page._status_for_score(17.0)[0] == "Bottom zone"
    assert page._status_for_score(12.0)[0] == "Leaning cheap"
    assert page._status_for_score(7.0)[0] == "Neutral"
    assert page._status_for_score(2.0)[0] == "Rich side"


def test_marker_pct():
    assert page.marker_pct(20.0) == pytest.approx(0.0)
    assert page.marker_pct(0.0) == pytest.approx(100.0)
    assert page.marker_pct(10.0) == pytest.approx(50.0)
    assert page.marker_pct(None) == pytest.approx(50.0)
    assert page.marker_pct(25.0) == pytest.approx(0.0)  # clamped


def test_gauge_svg_contains_needle_and_score():
    svg = page.gauge_svg(55.0, "Watch", "#6e6e73")
    assert svg.startswith("<svg")
    assert ">55<" in svg
    assert svg.count("<path") == 4  # one arc per zone band
    assert "<line" in svg and "<circle" in svg


def test_sparkline_points_shape():
    pts = page.sparkline_points([1.0, 2.0, 3.0, 2.0])
    pairs = [p.split(",") for p in pts.split()]
    assert len(pairs) == 4
    xs = [float(x) for x, _ in pairs]
    assert xs[0] == 0.0 and xs[-1] == pytest.approx(150.0)
    ys = [float(y) for _, y in pairs]
    assert min(ys) >= 0.0 and max(ys) <= 36.0


def test_sparkline_points_handles_flat_and_missing():
    assert page.sparkline_points([]) == ""
    assert page.sparkline_points([5.0]) == ""
    flat = page.sparkline_points([2.0, 2.0, 2.0])
    assert flat  # flat series still renders (mid-height line)
    gappy = page.sparkline_points([1.0, None, 3.0])
    assert len(gappy.split()) == 2


def _synthetic_inputs():
    n = 400
    dates = pd.date_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    onchain = pd.DataFrame(
        {
            "date": dates,
            "lth_realized_price": np.linspace(40_000, 49_000, n),
            "realized_price": np.linspace(45_000, 54_000, n),
            "sth_realized_price": np.linspace(60_000, 75_000, n),
            "mvrv": np.concatenate([np.full(n // 2, 1.0), np.full(n - n // 2, 2.4)]),
            "supply_loss_pct": np.linspace(5.0, 25.0, n),
            "realized_cap_change_30d_usd": np.linspace(-3e10, 3e10, n),
            "fear_greed": np.linspace(80.0, 10.0, n),
        }
    )
    price_df = pd.DataFrame(
        {"date": dates, "close_price": np.linspace(70_000, 63_000, n)}
    )
    scores_df = bs.compute_bottom_signal_scores(onchain, price_df)
    backtest = bs.build_backtest(scores_df)
    return scores_df, price_df, backtest


def test_generate_page_writes_html_and_info(tmp_path):
    scores_df, price_df, backtest = _synthetic_inputs()
    html_path = tmp_path / "bottom_signals.html"
    info_path = tmp_path / "bottom_signals_info.json"
    snapshot = page.generate_bottom_signals_page(
        scores_df, price_df, backtest, output_path=html_path, info_path=info_path
    )

    html = html_path.read_text()
    assert "On-Chain Bottom Signals" in html
    assert "const TRIG =" in html
    assert "const cycleBots =" in html
    assert page.PLOTLY_CDN in html
    for title in ("S1", "S2", "S3", "S4", "S5", "MA 120", "accuracy matrix"):
        assert title in html, f"missing {title}"
    assert "bitcoin-data.com" in html and "alternative.me" in html

    info = json.loads(info_path.read_text())
    assert info["composite"] == pytest.approx(snapshot["composite"])
    assert len(info["signals"]) == 5
    assert info["zone"] in {z[2] for z in bs.ZONES}
    assert snapshot["date"] == scores_df["date"].iloc[-1]


def test_generate_page_snapshot_values_are_finite(tmp_path):
    scores_df, price_df, backtest = _synthetic_inputs()
    snapshot = page.generate_bottom_signals_page(
        scores_df,
        price_df,
        backtest,
        output_path=tmp_path / "p.html",
        info_path=tmp_path / "i.json",
    )
    assert 0 <= snapshot["composite"] <= 100
    assert snapshot["price"] > 0
    assert snapshot["ath"] >= snapshot["price"]
    assert snapshot["ma200"] > 0
    for sig in snapshot["signals"]:
        assert 0 <= sig["score"] <= 20
