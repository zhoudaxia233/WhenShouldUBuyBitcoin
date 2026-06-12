"""Tests for the prerendered bottom-signals dashboard page."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin import bottom_signals as bs
from whenshouldubuybitcoin import bottom_signals_page as page


def test_json_for_script_escapes_script_breakout():
    # a malicious string must not be able to close the <script> block
    out = page._json_for_script(["a</script><script>alert(1)</script>b", "x>y", "p&q"])
    assert "<" not in out and ">" not in out and "&" not in out
    assert "\\u003c" in out and "\\u003e" in out and "\\u0026" in out
    # ordinary date/number payloads are unchanged vs plain json.dumps
    import json as _json
    plain = ["2024-01-01", 1.5, None]
    assert page._json_for_script(plain) == _json.dumps(plain)


def test_json_for_script_escapes_line_separators():
    # U+2028 / U+2029 are illegal raw in JS string literals; they must be escaped
    out = page._json_for_script(["a b c"])
    assert " " not in out and " " not in out
    assert "\\u2028" in out and "\\u2029" in out


def test_generated_script_block_has_no_unescaped_breakout(tmp_path):
    # even if a date somehow contained markup, the embedded JSON stays inert
    scores_df, price_df, backtest = _synthetic_inputs()
    scores_df = scores_df.copy()
    scores_df.loc[scores_df.index[0], "date"] = "</script><x>"
    snapshot = page.generate_bottom_signals_page(
        scores_df, price_df, backtest,
        output_path=tmp_path / "p.html", info_path=tmp_path / "i.json",
    )
    html = (tmp_path / "p.html").read_text()
    script = html.split("<script>")[-1]
    assert "</script><x>" not in script  # the injected markup is escaped
    assert snapshot["composite"] >= 0


def test_homepage_card_renders_advice_and_caveat():
    # the homepage summary card is the real "first glance"; it must surface the
    # advice + a sentiment-gauge caveat, not just a bare "81 / Extremely Undervalued"
    html = Path(__file__).resolve().parent.parent / "docs" / "index.html"
    text = html.read_text()
    assert 'id="bscNote"' in text  # the note element exists
    assert "data.advice" in text  # JS renders the advice line from info JSON
    assert "Sentiment gauge, not a buy signal" in text


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
    # the standalone footer disclaimer was removed; the methodology note still
    # carries a one-line not-investment-advice statement, so the page is not
    # left with zero risk language
    assert "Personal research, not investment advice. DYOR." not in html
    assert 'class="disclaimer"' not in html
    assert "None of this is investment advice." in html
    # honest disclosures: warmer-than-reference bias + illustrative backtest
    assert "warmer" in html
    assert "Illustrative only" in html
    # the page must own its two biggest known flaws, not just generic caveats
    assert "missed the 2024 cycle low" in html
    assert "highly correlated" in html
    # quantified honesty + jargon gloss
    assert "39% of the time" in html  # random-baseline anchor for the matrix
    assert "expanding-window calculation" in html  # look-ahead magnitude
    assert "how far a value sits from its historical average" in html  # sigma gloss
    assert 'class="back-link"' in html
    assert "complete score through" in html
    assert "data through" not in html
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


def test_page_price_context_is_aligned_to_latest_score_date(tmp_path):
    scores_df, price_df, backtest = _synthetic_inputs()
    latest_score_date = pd.to_datetime(scores_df["date"].iloc[-1])
    future_prices = pd.DataFrame(
        {
            "date": pd.date_range(latest_score_date + pd.Timedelta(days=1), periods=2),
            "close_price": [250_000.0, 300_000.0],
        }
    )
    price_with_future_rows = pd.concat([price_df, future_prices], ignore_index=True)

    snapshot = page.generate_bottom_signals_page(
        scores_df,
        price_with_future_rows,
        backtest,
        output_path=tmp_path / "bottom_signals.html",
        info_path=tmp_path / "bottom_signals_info.json",
    )

    aligned_closes = pd.to_numeric(price_df["close_price"], errors="coerce")
    assert snapshot["date"] == scores_df["date"].iloc[-1]
    assert snapshot["ath"] == pytest.approx(float(aligned_closes.max()))
    assert snapshot["ma120"] == pytest.approx(float(aligned_closes.rolling(120).mean().iloc[-1]))
    assert snapshot["ma200"] == pytest.approx(float(aligned_closes.rolling(200).mean().iloc[-1]))


def test_page_shows_weights_explicitly(tmp_path):
    # the composite's weighting must be stated on the page, not implied by the
    # /20 denominator: equal-weight wording, the summation formula, and one
    # contribution segment per signal next to the gauge
    scores_df, price_df, backtest = _synthetic_inputs()
    html_path = tmp_path / "bottom_signals.html"
    page.generate_bottom_signals_page(
        scores_df, price_df, backtest,
        output_path=html_path, info_path=tmp_path / "i.json",
    )
    html = html_path.read_text()
    assert "equal weight" in html
    assert "S1 + S2 + S3 + S4 + S5" in html
    assert html.count('class="breakdown-seg"') == 5


def test_page_does_not_mention_reference_dashboard(tmp_path):
    # the page stands on its own: data sources stay attributed, but no
    # "inspired by" credit to any other dashboard
    scores_df, price_df, backtest = _synthetic_inputs()
    html_path = tmp_path / "bottom_signals.html"
    page.generate_bottom_signals_page(
        scores_df, price_df, backtest,
        output_path=html_path, info_path=tmp_path / "i.json",
    )
    html = html_path.read_text()
    assert "inspired by" not in html.lower()
    assert "Inspired by" not in html
    assert "bitcoin-data.com" in html and "alternative.me" in html


def test_homepage_card_states_signal_scale():
    # the S1..S5 chips on the homepage card are meaningless without the scale;
    # the card must say each signal is 0-20 with equal weight
    html = Path(__file__).resolve().parent.parent / "docs" / "index.html"
    text = html.read_text()
    assert "each 0–20 · equal weight" in text


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
