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
    assert "const totalBtcText = Number(totalBtc).toFixed(8);" in html
    assert "setRequiredText('saylorTotalBtc', totalBtcText);" in html
    assert "setTextIfPresent('saylorTotalBtcMobile', totalBtcText);" in html
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


def test_light_mode_summary_box_uses_satsflow_palette():
    html = _load_stats_template()
    assert "html[data-bs-theme=\"light\"] .saylor-summary-box {" in html
    assert (
        "background: linear-gradient(180deg, rgba(255, 138, 0, 0.12) 0%, "
        "rgba(255, 255, 255, 0.82) 100%);"
    ) in html
    assert "html[data-bs-theme=\"light\"] .saylor-summary-box .metric-value {" in html
    assert "color: var(--dashboard-text);" in html


def test_saylor_mobile_summary_kpis_are_above_chart():
    html = _load_stats_template()
    assert 'class="saylor-mobile-kpis"' in html
    assert 'id="saylorReserveValueMobile"' in html
    assert 'id="saylorTotalBtcMobile"' in html
    assert 'id="saylorAvgCostMobile"' in html
    assert 'id="saylorPnlMobile"' in html
    assert "function setTextIfPresent(id, value)" in html
    assert "saylorReserveValueMobile" in html
    assert ".saylor-mobile-kpis {" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert "white-space: nowrap;" in html


def test_saylor_required_summary_fields_use_strict_setters():
    html = _load_stats_template()
    assert "function setRequiredText(id, value)" in html
    assert "setRequiredText('saylorReserveValue', reserveValueText);" in html
    assert "setRequiredText('saylorTotalBtc', totalBtcText);" in html
    assert "setRequiredText('saylorAvgCost', avgCostText);" in html
    assert "setTextIfPresent('saylorReserveValue', reserveValueText);" not in html
    assert "setTextIfPresent('saylorTotalBtc', totalBtcText);" not in html
    assert "setTextIfPresent('saylorAvgCost', avgCostText);" not in html


def test_saylor_mobile_chart_disables_precision_zoom_and_has_reset_button():
    html = _load_stats_template()
    assert 'id="resetSaylorZoomBtn"' in html
    assert "resetSaylorZoomBtn.addEventListener('click', resetSaylorZoom)" in html
    assert "const isMobileViewport = window.matchMedia('(max-width: 575px)').matches;" in html
    assert "display: !isMobileViewport" in html
    assert "enabled: !isMobileViewport" in html
    assert "#saylorChart {" in html
    assert "touch-action: none;" in html
    assert "touch-action: pan-y;" in html


def test_saylor_desktop_x_axis_does_not_get_mobile_tick_limit():
    html = _load_stats_template()
    assert "maxTicksLimit: isMobileViewport ? 4 : 8" not in html
    assert "...(isMobileViewport ? { maxTicksLimit: 4 } : {})" in html


def test_performance_chart_has_mobile_safe_wrapper_and_legend_config():
    html = _load_stats_template()
    assert 'class="pnl-chart-wrap"' in html
    assert ".pnl-chart-wrap {" in html
    assert "height: 400px;" in html
    assert "height: 340px;" in html
    assert "const isMobileViewport = window.matchMedia('(max-width: 575px)').matches;" in html
    assert "display: !isMobileViewport" in html


def test_trading_style_supports_language_toggle_and_language_aware_request():
    html = _load_stats_template()
    assert 'id="tradingStyleLangEn"' in html
    assert 'id="tradingStyleLangZh"' in html
    assert "let tradingStyleLanguage = 'en';" in html
    assert "function applyTradingStyleLanguageUI()" in html
    assert "language=${encodeURIComponent(tradingStyleLanguage)}" in html


def test_trading_style_csv_export_ui_is_enabled():
    html = _load_stats_template()
    assert 'id="exportStyleCsvBtn"' in html
    assert 'id="tradingStylePromptPreview"' not in html
    assert "function downloadTradingStyleCsv()" in html
    assert "/api/stats/trading-style.csv?language=${encodeURIComponent(tradingStyleLanguage)}" in html
    assert "link.download = 'bitcoin-purchases.csv';" in html
    assert "trading-style-analysis.csv" not in html
    assert "await fetch(url)" in html
    assert "if (!response.ok)" in html
    assert "URL.createObjectURL(blob)" in html
    assert "window.location.href = url" not in html


def test_distribution_and_percentile_label_browser_cache_as_stale_data():
    html = _load_stats_template()
    assert "const STATS_CACHE_VERSION = 'v2';" in html
    assert "const PERCENTILE_CACHE_KEY = `stats_percentile_${STATS_CACHE_VERSION}`;" in html
    assert "const DISTRIBUTION_CACHE_KEY = `stats_distribution_${STATS_CACHE_VERSION}`;" in html
    assert "loadFromCache(PERCENTILE_CACHE_KEY) || loadFromCache('stats_percentile')" in html
    assert "loadFromCache(DISTRIBUTION_CACHE_KEY) || loadFromCache('stats_distribution')" in html
    assert "clearLegacyStatsCaches();" not in html
    assert "data_status: 'stale'" in html
    assert "Cached BitInfoCharts data" in html
    assert "stale BitInfoCharts data" in html
    assert "Distribution request failed" in html
    assert "return { ok: true, stale: true" in html
    assert "Promise.allSettled" in html


def test_update_charts_button_is_admin_only_and_does_not_show_raw_logs():
    html = _load_stats_template()
    assert "{% if user and user.is_admin %}" in html
    assert 'id="regenerateStaticBtn"' in html
    assert "const regenerateStaticBtn = document.getElementById('regenerateStaticBtn');" in html
    assert "if (regenerateStaticBtn)" in html
    assert "statusData.log_tail" not in html
    assert "stderr_preview" not in html
    assert "stdout_preview" not in html
    assert "shortDetails" not in html
    assert "Check logs:" not in html
    assert "Update Charts failed. Please ask an admin to check server logs." in html


def test_trading_style_uses_rule_data_only_without_ai_call():
    html = _load_stats_template()
    assert "/api/stats/trading-style?include_ai=false&language=${encodeURIComponent(tradingStyleLanguage)}" in html
    assert "const cacheKey = `stats_trading_style_${tradingStyleLanguage}`;" in html


def test_stats_page_uses_reference_dashboard_layout_without_visible_title_block():
    html = _load_stats_template()

    assert '<div class="page-title-block' not in html
    assert '<h1>Stats & Analytics</h1>' not in html
    assert 'class="stats-actions-row"' in html
    assert 'class="stats-rank-hero dashboard-panel"' in html
    assert 'class="stats-rank-watermark"' in html
    assert 'class="stats-metrics-grid"' in html
    assert html.count('class="stats-metric-card dashboard-panel"') == 5
    assert 'class="stats-analytics-grid"' in html
    assert 'class="stats-saylor-panel dashboard-panel saylor-card"' in html
    assert 'class="trading-style-list"' in html


def test_distribution_table_has_rank_column_and_bar_renderer():
    html = _load_stats_template()

    assert "<th>Your Rank</th>" in html
    assert "colspan=\"3\"" in html
    assert "function percentileRankBarWidth(percentile)" in html
    assert 'class="rank-bar"' in html


def test_distribution_header_does_not_show_app_version_badge():
    html = _load_stats_template()
    header_start = html.index('<div class="dashboard-panel stats-distribution-card">')
    header_end = html.index('<div class="card-body p-0">', header_start)
    distribution_header = html[header_start:header_end]

    assert "Global Wealth Distribution" in distribution_header
    assert "version-badge" not in distribution_header
    assert 'class="stats-footer-version"' in html


def test_trading_style_uses_row_based_layout():
    html = _load_stats_template()

    assert 'class="trading-style-row"' in html
    assert 'class="trading-style-row-icon"' in html
    assert 'class="trading-style-row-label" id="tradingStyleLabelTags"' in html
    assert 'class="trading-style-row-content" id="tradingStyleStats"' in html


def test_trading_style_status_is_aligned_under_header_title():
    html = _load_stats_template()

    header_start = html.index('<div class="dashboard-panel stats-trading-panel">')
    body_start = html.index('<div class="card-body">', header_start)
    header_html = html[header_start:body_start]
    body_html = html[body_start:html.index('<div class="trading-style-list">', body_start)]

    assert 'class="trading-style-heading"' in header_html
    assert 'id="tradingStyleTitle"' in header_html
    assert 'id="tradingStyleStatus"' in header_html
    assert 'id="tradingStyleStatus"' not in body_html


def test_stats_uses_only_inline_version_badge_to_avoid_fixed_overlap():
    html = _load_stats_template()

    assert 'class="version-badge position-static m-0"' in html
    assert html.count('class="version-badge') == 1


def test_distribution_current_row_highlight_is_reapplied_after_percentile_loads():
    html = _load_stats_template()

    assert "let latestPercentileDisplay = '';" in html
    assert "function applyCurrentDistributionHighlight()" in html
    assert "applyCurrentDistributionHighlight();" in html
    assert "tr.dataset.percentile = String(row.percentile || '').trim();" in html
    assert "row.classList.toggle('current-rank-row', row.dataset.percentile === currentPercentile);" in html
