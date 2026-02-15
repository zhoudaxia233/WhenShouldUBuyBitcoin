from pathlib import Path
import re


def _load_stats_template() -> str:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dca_service"
        / "templates"
        / "stats.html"
    )
    return template_path.read_text(encoding="utf-8")


def test_saylor_btc_shows_8_decimals():
    html = _load_stats_template()
    # Keep BTC display precision consistent across summary fields.
    assert "saylorTotalBtc').textContent = Number(totalBtc).toFixed(8);" in html
    assert "saylorRangeBtc').textContent = Number(totalBtc).toFixed(8);" in html


def test_saylor_dates_use_english_short_month_format():
    html = _load_stats_template()
    # X-axis monthly ticks and "As of" date should use short English month names.
    assert "toLocaleDateString('en-US', { month: 'short', year: 'numeric' })" in html
    assert "toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })" in html


def test_theme_toggle_rerenders_saylor_chart_for_dynamic_drag_box_colors():
    html = _load_stats_template()
    assert "const dragBorderColor = isDark" in html
    assert "const dragFillColor = isDark" in html
    assert "borderColor: dragBorderColor" in html
    assert "backgroundColor: dragFillColor" in html
    assert re.search(
        r"themeBtn\.addEventListener\('click',[\s\S]*renderSaylorChart\(latestStatsPnlData\);",
        html,
    )


def test_total_btc_value_is_forced_single_line():
    html = _load_stats_template()
    assert "#saylorRangeBtc {" in html
    assert "white-space: nowrap;" in html


def test_pan_disabled_and_drag_zoom_is_direct():
    html = _load_stats_template()
    # Pan should be disabled.
    pan_block = re.search(r"pan:\s*\{[\s\S]*?\}", html)
    assert pan_block is not None
    assert "enabled: false" in pan_block.group(0)
    # Drag-to-zoom should be direct (no modifier key).
    drag_block = re.search(r"drag:\s*\{[\s\S]*?\}", html)
    assert drag_block is not None
    assert "modifierKey" not in drag_block.group(0)


def test_summary_card_uses_two_equal_columns_with_metric_value_style():
    html = _load_stats_template()
    assert 'class="saylor-summary-metrics"' in html
    assert 'class="saylor-summary-metric"' in html
    assert '<span class="metric-number" id="saylorPurchaseEvents">' in html
    assert '<span class="btc-symbol">₿</span><span class="metric-number" id="saylorRangeBtc">' in html


def test_saylor_total_btc_prefers_wallet_summary_source():
    html = _load_stats_template()
    assert "let latestWalletSummary = null;" in html
    assert "latestWalletSummary.total_btc" in html
    assert "latestWalletSummary = walletData;" in html


def test_saylor_reserve_value_uses_wallet_current_price_for_consistency():
    html = _load_stats_template()
    assert "latestWalletSummary.current_price" in html
    assert "const reserveValue = totalBtc * walletPrice;" in html


def test_saylor_summary_box_has_max_width_to_avoid_overflow():
    html = _load_stats_template()
    assert ".saylor-summary-box {" in html
    assert "max-width: 420px;" in html
    assert "margin-left: auto;" in html


def test_light_mode_summary_box_uses_light_palette():
    html = _load_stats_template()
    assert "html[data-bs-theme=\"light\"] .saylor-summary-box {" in html
    assert "background: linear-gradient(180deg, #f7f9fc 0%, #edf2f8 100%);" in html
    assert "html[data-bs-theme=\"light\"] .saylor-summary-box .metric-value {" in html
    assert "color: #1b2b40;" in html


def test_trading_style_supports_language_toggle_and_language_aware_request():
    html = _load_stats_template()
    assert 'id="tradingStyleLangEn"' in html
    assert 'id="tradingStyleLangZh"' in html
    assert "let tradingStyleLanguage = 'en';" in html
    assert "function applyTradingStyleLanguageUI()" in html
    assert "language=${encodeURIComponent(tradingStyleLanguage)}" in html
