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


def _load_shared_header_template() -> str:
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dca_service"
        / "templates"
        / "_shared_header.html"
    )
    return template_path.read_text(encoding="utf-8")


def test_stats_mobile_clears_floating_bottom_nav():
    """The stats page reserves bottom space so the chart and its range buttons
    clear the fixed mobile bottom nav."""
    html = _load_stats_template()
    mobile_css = html.split("@media (max-width: 767.98px)", 1)[1]

    assert "env(safe-area-inset-bottom)" in mobile_css
    nav_clear_block = mobile_css[
        mobile_css.index("body.stats-page {") : mobile_css.index("body.stats-page {") + 220
    ]
    assert "padding-bottom:" in nav_clear_block
    assert "env(safe-area-inset-bottom)" in nav_clear_block


def test_performance_chart_has_mobile_safe_wrapper_and_legend_config():
    html = _load_stats_template()
    assert 'class="pnl-chart-wrap"' in html
    assert ".pnl-chart-wrap {" in html
    assert "height: 400px;" in html
    assert "height: 340px;" in html
    assert "const isMobileViewport = window.matchMedia('(max-width: 575px)').matches;" in html
    assert "display: !isMobileViewport" in html


def test_performance_chart_uses_dedicated_performance_series():
    html = _load_stats_template()
    assert "function buildPerformanceChartSeries(data)" in html
    assert "const performanceLabels = Array.isArray(data.performance_dates)" in html
    assert "data: performanceInvested" in html
    assert "data: performanceValue" in html
    assert "latestWalletSummary.current_price" in html
    assert "renderChart(latestStatsPnlData);" in html


def test_performance_chart_does_not_reprice_invested_capital_from_wallet_avg_cost():
    html = _load_stats_template()
    chart_series_match = re.search(
        r"function buildPerformanceChartSeries\(data\) \{(?P<body>[\s\S]*?)\n        \}\n\n        function renderChart",
        html,
    )
    assert chart_series_match is not None
    chart_series_body = chart_series_match.group("body")

    assert "latestWalletSummary.total_btc * latestWalletSummary.hot_wallet_avg_price" not in chart_series_body
    assert "const walletInvested = performanceInvested[performanceInvested.length - 1] || 0;" in chart_series_body
    assert "performanceValue.push(walletValue);" in chart_series_body


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


def test_distribution_and_percentile_label_static_fallback_data():
    html = _load_stats_template()
    assert "Bundled BitInfoCharts data" in html
    assert "Source: bundled BitInfoCharts data" in html
    assert "data.data_status === 'static'" in html
    assert "meta.data_status === 'static'" in html


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
    # No decorative watermark or made-up sparklines: every mark on Insights is data.
    assert 'class="stats-rank-watermark"' not in html
    assert "metric-sparkline" not in html
    assert 'class="stats-metrics-grid"' in html
    assert html.count('stats-metric-card dashboard-panel') == 5
    assert 'class="stats-analytics-grid"' in html
    assert 'class="trading-style-list"' in html


def test_stats_refresh_control_lives_in_header_not_actions_row():
    html = _load_stats_template()
    header = _load_shared_header_template()
    actions_start = html.index('<div class="stats-actions-row">')
    actions_end = html.index('</div>', actions_start)
    actions_html = html[actions_start:actions_end]

    assert 'id="refreshStatsBtn"' not in actions_html
    assert "Force Refresh Data" not in actions_html
    assert 'id="refreshStatsBtn"' in header
    assert "Refresh analytics" in header
    assert "document.getElementById('refreshStatsBtn').addEventListener" not in html


def test_stats_mobile_hides_transactions_metric_card():
    html = _load_stats_template()
    mobile_css = html.split("@media (max-width: 575px)", 1)[1]

    assert 'class="stats-metric-card dashboard-panel stats-transaction-card"' in html
    assert ".stats-transaction-card {" in mobile_css
    assert "display: none;" in mobile_css[
        mobile_css.index(".stats-transaction-card {") : mobile_css.index(".pnl-chart-wrap {")
    ]


def test_stats_mobile_layout_keeps_metrics_dense_before_charts():
    html = _load_stats_template()
    mobile_css = html.split("@media (max-width: 575px)", 1)[1]

    assert ".stats-actions-row {" in mobile_css
    assert "margin: 0 0 10px;" in mobile_css
    assert ".stats-metrics-grid {" in mobile_css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_css
    assert "grid-template-columns: 1fr;" not in mobile_css
    assert "gap: 10px;" in mobile_css
    assert ".stats-metric-card {" in mobile_css
    assert "min-height: 96px;" in mobile_css
    assert "padding: 12px;" in mobile_css


def test_stats_mobile_action_buttons_keep_readable_labels():
    html = _load_stats_template()
    mobile_css = html.split("@media (max-width: 575px)", 1)[1]

    assert ".stats-actions-row .btn {" in mobile_css
    assert "min-height: 36px;" in mobile_css
    assert ".stats-actions-row .btn-text {" not in mobile_css
    assert "Force Refresh Data" not in html
    assert "Update Charts</span>" in html


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

