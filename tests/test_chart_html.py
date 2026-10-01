"""
Tests for the HTML contract of generated Plotly charts.

The homepage embeds every chart in an iframe and owns its size, so each chart
page must fill its frame, share one Plotly bundle, render its title as HTML
(Plotly titles cannot wrap on narrow screens) and load the chart runtime.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from whenshouldubuybitcoin.visualization import (
    create_futures_oi_timeseries_chart,
    create_oi_quadrant_chart,
    plot_funding_credit_stress,
    plot_ma_cross_analysis,
    plot_macro_risk_score,
    plot_net_liquidity_dashboard,
    plot_price_comparison,
    plot_usdjpy_risk_map,
    plot_valuation_ratios,
)

DAYS = 900
START = datetime(2022, 1, 1)


@pytest.fixture
def btc_df():
    dates = pd.date_range(START, periods=DAYS, freq="D")
    i = np.arange(DAYS)
    price = 20_000 + 50 * i + 2_000 * np.sin(i / 30)
    df = pd.DataFrame(
        {
            "date": dates,
            "close_price": price,
            "ratio_dca": 0.8 + 0.4 * np.sin(i / 90) + 0.5,
            "ratio_trend": 0.7 + 0.3 * np.sin(i / 120) + 0.5,
            "ahr999": 0.4 + 0.3 * np.sin(i / 100) + 0.5,
            "is_double_undervalued": i % 50 < 5,
            "dca_cost": price * 0.95,
            "trend_value": price * 0.9,
        }
    )
    for window in (50, 200, 350, 700, 1400):
        df[f"ma_{window}"] = df["close_price"].rolling(min(window, 30), min_periods=1).mean()
    df["ma_spread"] = df["ma_50"] / df["ma_200"] - 1
    df["golden_cross"] = i % 200 == 100
    df["death_cross"] = i % 200 == 0
    return df


@pytest.fixture
def macro_df(btc_df):
    i = np.arange(DAYS)
    return pd.DataFrame(
        {
            "date": btc_df["date"],
            "walcl_bil": 8_500.0 + i,
            "tga_bil": 800.0,
            "rrp_bil": 500.0 - i * 0.1,
            "net_liquidity_bil": 7_200.0 + np.sin(i / 40) * 100,
            "sofr": 5.25 - i * 0.001,
            "move": 110.0 + np.sin(i / 20) * 10,
            "hy_oas": 3.8 + np.sin(i / 25) * 0.3,
        }
    )


@pytest.fixture
def chart_dir(tmp_path):
    return tmp_path


def _build(name, btc_df, macro_df, out_dir: Path) -> Path:
    path = out_dir / f"{name}.html"
    if name == "valuation_ratios":
        plot_valuation_ratios(btc_df, output_filename=str(path), auto_open=False)
    elif name == "price_comparison":
        plot_price_comparison(btc_df, output_filename=str(path), auto_open=False)
    elif name == "ma_cross_analysis":
        plot_ma_cross_analysis(btc_df, output_filename=str(path), auto_open=False)
    elif name == "net_liquidity":
        plot_net_liquidity_dashboard(
            btc_df[["date", "close_price"]], macro_df, output_filename=str(path), auto_open=False
        )
    elif name == "funding_credit_stress":
        plot_funding_credit_stress(
            btc_df[["date", "close_price"]], macro_df, output_filename=str(path), auto_open=False
        )
    elif name == "macro_risk_score":
        plot_macro_risk_score(
            btc_df[["date", "close_price"]], macro_df, output_filename=str(path), auto_open=False
        )
    elif name == "usdjpy_risk_map":
        usdjpy = pd.DataFrame({"date": btc_df["date"], "close_price": 140 + np.sin(np.arange(DAYS) / 50) * 10})
        yields = pd.DataFrame(
            {"date": btc_df["date"], "us_2y": 4.5, "jp_2y": 0.5, "spread": 4.0 - np.arange(DAYS) * 0.001}
        )
        plot_usdjpy_risk_map(usdjpy, yields, output_filename=str(path), auto_open=False)
    elif name in ("futures_oi", "oi_quadrant"):
        prices = btc_df.set_index("date")[["close_price"]].copy()
        oi = pd.DataFrame(
            {"oi_usd": 1.5e9 + np.sin(np.arange(30) / 3) * 1e8},
            index=pd.date_range(START + timedelta(days=DAYS - 30), periods=30, freq="D"),
        )
        if name == "futures_oi":
            create_futures_oi_timeseries_chart(btc_df=prices, oi_df=oi, output_path=str(path))
        else:
            create_oi_quadrant_chart(btc_df=prices, oi_df=oi, output_path=str(path))
    else:
        raise AssertionError(name)
    return path


ALL_CHARTS = [
    "valuation_ratios",
    "price_comparison",
    "ma_cross_analysis",
    "net_liquidity",
    "funding_credit_stress",
    "macro_risk_score",
    "usdjpy_risk_map",
    "futures_oi",
    "oi_quadrant",
]


def _plot_call(html: str):
    """Return (data, layout, config) passed to Plotly.newPlot in a chart page."""
    start = html.index("Plotly.newPlot(")
    decoder = json.JSONDecoder()
    pos = html.index(",", start) + 1  # skip the div id argument
    values = []
    for _ in range(3):
        while html[pos] in " \n\t,":
            pos += 1
        value, pos = decoder.raw_decode(html, pos)
        values.append(value)
    return values


@pytest.fixture(params=ALL_CHARTS)
def chart(request, btc_df, macro_df, chart_dir):
    path = _build(request.param, btc_df, macro_df, chart_dir)
    return request.param, path, path.read_text(encoding="utf-8")


def test_chart_is_a_full_page_with_mobile_viewport(chart):
    _, _, html = chart
    assert html.lstrip().lower().startswith("<html")
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html


def test_chart_loads_shared_plotly_bundle(chart):
    _, path, html = chart
    assert '<script charset="utf-8" src="plotly.min.js"></script>' in html
    assert "plotly.js v" not in html, "Plotly must not be inlined into every chart"
    assert (path.parent / "plotly.min.js").exists()


def test_chart_fills_its_frame(chart):
    _, _, html = chart
    _, layout, config = _plot_call(html)
    assert "height" not in layout
    assert "width" not in layout
    assert layout.get("autosize", True) is True
    assert config["responsive"] is True
    assert config["displaylogo"] is False


def test_chart_title_is_rendered_as_html(chart):
    name, _, html = chart
    _, layout, _ = _plot_call(html)
    title = layout.get("title", {})
    assert not title.get("text"), "The Plotly title is replaced by the HTML header"
    assert '<header class="chart-header">' in html
    header = html[html.index('<header class="chart-header">'):html.index("</header>")]
    assert re.search(r'<h1 class="chart-title">[^<]+</h1>', header), name


def test_chart_loads_runtime(chart):
    _, _, html = chart
    assert 'id="chart-runtime"' in html
    assert 'id="chart-runtime-style"' in html
    assert "add_yaxis_autoscale" not in html
    assert "isUpdatingYAxis" not in html, "The old y-axis script must be gone"


def test_runtime_is_loaded_once_even_with_info_modal(btc_df, macro_df, chart_dir):
    html = _build("macro_risk_score", btc_df, macro_df, chart_dir).read_text(encoding="utf-8")
    assert html.count('id="chart-runtime"') == 1
    assert "chart-info-button" in html
    assert "chart-header-actions" in html


def test_subtitle_segments_are_separate_items(btc_df, macro_df, chart_dir):
    html = _build("valuation_ratios", btc_df, macro_df, chart_dir).read_text(encoding="utf-8")
    header = html[html.index('<header class="chart-header">'):html.index("</header>")]
    assert header.count('class="chart-sub-item"') >= 3
    assert "&lt;" in header, "Title text is escaped, not injected as markup"


def test_valuation_ratios_uses_log_scale(btc_df, macro_df, chart_dir):
    html = _build("valuation_ratios", btc_df, macro_df, chart_dir).read_text(encoding="utf-8")
    _, layout, _ = _plot_call(html)
    assert layout["yaxis"]["type"] == "log"


def test_valuation_zone_labels_sit_on_their_lines_in_log_scale(btc_df, macro_df, chart_dir):
    html = _build("valuation_ratios", btc_df, macro_df, chart_dir).read_text(encoding="utf-8")
    _, layout, _ = _plot_call(html)
    labels = {a["text"]: a["y"] for a in layout["annotations"] if "Zone" in a.get("text", "")}
    assert labels, "Zone labels exist"
    for text, y in labels.items():
        level = 0.45 if "0.45" in text else 1.2
        assert y == pytest.approx(np.log10(level)), text


def test_futures_zone_labels_are_not_overwritten(btc_df, macro_df, chart_dir):
    html = _build("futures_oi", btc_df, macro_df, chart_dir).read_text(encoding="utf-8")
    _, layout, _ = _plot_call(html)
    texts = [a.get("text") for a in layout.get("annotations", [])]
    assert texts.count("Data: Binance") == 1
    assert "High Leverage" in texts
    assert "Deleveraged" in texts
