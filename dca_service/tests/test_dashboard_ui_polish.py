import re
from pathlib import Path


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dca_service"
    / "templates"
    / "index.html"
)
TEMPLATE_DIR = TEMPLATE_PATH.parent
STATIC_CSS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dca_service"
    / "static"
    / "app.css"
)


def _dashboard_html() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_dashboard_uses_the_ledger_visual_system():
    html = _dashboard_html()
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert "href=\"{{ asset_url('app.css') }}\"" in html
    assert "--dashboard-accent: #15171b;" in css
    assert "--dashboard-btc: #f7931a;" in css
    assert "{% include \"_shared_header.html\" %}" in html
    assert "{% set active_page = 'dashboard' %}" in html


def test_product_name_is_satsflow_and_not_hardcoded_in_login():
    config = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dca_service"
        / "config.py"
    ).read_text(encoding="utf-8")
    login = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dca_service"
        / "templates"
        / "login.html"
    ).read_text(encoding="utf-8")
    auth_api = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "dca_service"
        / "api"
        / "auth_api.py"
    ).read_text(encoding="utf-8")

    assert 'PROJECT_NAME: str = "SatsFlow"' in config
    assert "<title>{{ project_name }} Dashboard</title>" in _dashboard_html()
    assert "<title>Login - {{ project_name }}</title>" in login
    assert 'class="brand-title">{{ project_name }}</span>' in login
    assert "<h1>{{ project_name }}</h1>" not in login
    assert '"project_name": settings.PROJECT_NAME' in auth_api


def test_dashboard_refresh_control_lives_in_header_not_standalone_bar():
    html = _dashboard_html()
    header = (TEMPLATE_DIR / "_shared_header.html").read_text(encoding="utf-8")

    assert 'class="refresh-panel mb-4"' not in html
    assert "Global Refresh Status Bar" not in html
    assert 'id="globalRefreshBtn"' in header
    assert 'dashboard-refresh-btn' in header
    assert "<strong>Last refresh:</strong>" not in html
    assert "updateGlobalRefreshTime(timestamp)" in html
    assert "globalBtn.disabled = true;" in html


def test_dashboard_mobile_reference_structure_prioritizes_wallet_hero():
    html = _dashboard_html()

    wallet_index = html.index('id="reserveChart"')
    strategy_index = html.index('id="strategyDetailsTitle">DCA Strategy')
    transactions_index = html.index('Recent buys')
    assert wallet_index < strategy_index < transactions_index
    assert 'class="dashboard-mobile-snapshot"' not in html
    assert 'id="totalBtcFiatValue"' not in html
    assert 'id="mobileHeroPrice"' not in html
    assert 'metric-market-price' not in html
    assert 'class="metric-card dca-budget-card dashboard-mobile-only-card"' not in html
    assert 'id="mobileDcaBudget"' not in html
    assert "DCA Budget" not in html
    assert "Quick Stats" not in html
    assert 'id="mobileDcaBudgetQuick"' not in html
    assert 'class="progress dashboard-accent-progress"' in html
    assert 'id="progressBar"' in html
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    progress_css = css[css.index(".dashboard-accent-progress {") : css.index(".dashboard-accent-progress .progress-bar")]
    assert "width: 100%;" in progress_css
    assert "max-width: none;" in progress_css
    assert "background: var(--dashboard-ring-track);" in progress_css
    assert "Spent $0.00 of $600.00" not in html
    assert 'id="transactionsCards"' in html


def test_dashboard_mobile_app_cards_are_hydrated_from_existing_data():
    html = _dashboard_html()

    assert "function setDashboardTextIfPresent(id, value)" in html
    assert "window.__dashboardTotalBtc = totalBtc;" in html
    assert "function updateDashboardRealtimePrice(payload)" in html
    assert "window.__dashboardPriceUsd = price;" in html
    assert "setDashboardTextIfPresent('mobileHeroPrice'" not in html
    assert "setDashboardTextIfPresent('mobileDcaBudget'" not in html
    assert "progressBarEl.style.width = `${progress}%`;" in html
    assert "progressBarEl.setAttribute('aria-valuenow', progress);" in html
    assert "document.getElementById('progressBar').style.width = progress + '%';" in html
    assert "document.getElementById('progressBar').setAttribute('aria-valuenow', progress);" in html
    assert "setDashboardTextIfPresent('mobileDcaBudgetQuick'" not in html
    assert "setDashboardTextIfPresent('mobileDailyDca'" not in html
    assert "renderMobileTransactionCards(pageTransactions);" in html


def test_dashboard_mobile_transaction_cards_show_purchase_price_not_id():
    html = _dashboard_html()
    mobile_render = html[
        html.index("function renderMobileTransactionCards(pageTransactions)")
        : html.index("function renderTransactionPage()")
    ]

    assert "const priceDisplay = tx.price ? `$${tx.price.toFixed(2)}` : '-';" in mobile_render
    assert (
        '<span class="mobile-transaction-price">${escapeHtml(priceDisplay)}</span>'
        in mobile_render
    )
    assert "mobile-transaction-id" not in mobile_render
    assert "${escapeHtml(tx.id)}" not in mobile_render


def test_dashboard_mobile_keeps_dense_lists_and_hides_the_wide_table():
    html = _dashboard_html()
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert 'id="bottomingSignalStatus"' in html
    assert 'id="bottomingSignalMetrics"' in html
    assert 'id="bottomingSignalMacro"' in html
    assert 'id="mobileBottomingSummary"' not in html
    assert 'href="/stats">View Details' not in html
    assert ".mobile-transaction-card-list {" in mobile_css
    assert ".transactions-table-wrap {" in mobile_css
    assert "display: none;" in mobile_css

    phone_css = css[css.index("@media (max-width: 767.98px)", css.index("/* ---------- Home: holdings")) :]
    readout_row = phone_css[phone_css.index(".reserve-readout-row {") :]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in readout_row[: readout_row.index("}")]


def test_dashboard_mobile_strategy_badges_use_compact_single_row_labels():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert "function setResponsiveBadgeText(element, fullText, compactText)" in html
    assert "function refreshResponsiveBadgeText()" in html
    assert "setResponsiveBadgeText(scheduleDisplayEl, scheduleFullText, scheduleCompactText);" in html
    assert "const scheduleCompactText = `${freq} ${strategy.execution_time_utc}`;" in html
    # Labels sit next to their row titles, so the values drop "Source:" and "Mode:".
    assert "setResponsiveBadgeText(dataSourceBadgeEl, preview.metrics_source.label, preview.metrics_source.label);" in html
    assert "setResponsiveBadgeText(sourceBadge, metricsSource.label, metricsSource.label);" in html
    assert "setResponsiveBadgeText(badge, 'Live', 'Live');" in html
    assert "setResponsiveBadgeText(badge, 'Dry run', 'Dry run');" in html
    assert ".live-mode-dot {" in html
    assert "@keyframes liveModePulse" in html
    assert "ensureLiveModeBadgeDot(badge);" in html
    assert "badge.classList.add('live-mode-active');" in html
    assert "removeLiveModeBadgeDot(badge);" in html
    assert '<dt>Schedule</dt><dd class="is-text"><span id="scheduleDisplay">' in html
    assert '<span id="dataSourceBadge">' in html


def test_dashboard_extra_buy_lives_in_the_next_buy_card_above_the_fold():
    html = _dashboard_html()
    card = html[html.index('id="strategyActionPanel"') :]
    card = card[: card.index("</aside>")]

    assert 'id="openAddPositionBtn"' in card
    assert 'href="/strategy">Edit strategy</a>' in card
    assert html.index('id="strategyActionPanel"') < html.index('class="reserve-canvas"')
    assert "Re-sync" in html
    assert "clearBtn.textContent = 'Re-sync';" in html


def test_dashboard_dca_strategy_uses_structured_reference_cards():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert 'class="home-section dca-strategy-panel"' in html
    assert 'class="strategy-metric-content"' not in html
    assert 'id="previewAhrState"' not in html
    assert 'strategy-mini-chip' not in html
    assert 'class="strategy-advanced-panel mobile-collapsible is-collapsed mb-3"' in html
    assert 'class="strategy-advanced-header" role="button" tabindex="0" data-strategy-accordion-toggle aria-expanded="false" aria-controls="strategyAdvancedBody"' in html
    assert "<strong>Advanced</strong>" in html
    assert "Status · Drawdown Context · Bottoming Checklist" in html
    assert 'class="strategy-advanced-body strategy-card-grid" id="strategyAdvancedBody"' in html
    assert 'class="dashboard-info-panel strategy-detail-card strategy-status-card mobile-collapsible is-collapsed"' in html
    assert 'class="strategy-detail-card-header" role="button" tabindex="0" data-strategy-accordion-toggle aria-expanded="false" aria-controls="strategyStatusBody"' in html
    assert 'class="dashboard-info-panel strategy-detail-card strategy-drawdown-card mobile-collapsible is-collapsed"' in html
    assert 'class="strategy-detail-card-header" role="button" tabindex="0" data-strategy-accordion-toggle aria-expanded="false" aria-controls="drawdownCardBody"' in html
    assert 'class="dashboard-info-panel strategy-detail-card strategy-bottoming-card mobile-collapsible is-collapsed"' in html
    assert 'class="strategy-detail-card-header" role="button" tabindex="0" data-strategy-accordion-toggle aria-expanded="false" aria-controls="bottomingCardBody"' in html
    assert 'class="btn-group btn-group-sm mobile-drawdown-mode-controls"' in html
    assert 'aria-label="Mobile Drawdown Mode"' in html
    assert 'button class="strategy-card-collapse-toggle"' not in html
    assert 'class="strategy-card-header-meta" id="drawdownCompactLabel"' in html
    assert 'class="strategy-card-header-meta" id="bottomingSignalDate"' in html
    assert 'strategy-quick-card' not in html
    assert 'strategy-quick-stats-strip' not in html
    assert "function formatDashboardStatusReason(reasonText)" in html
    assert r"replace(/\s*\|\s*/g, '\n')" in html
    assert "startsWith('Budget:')" not in html
    assert "startsWith('Monthly Spent=')" not in html
    assert "formatDashboardStatusReason(preview.reason)" in html
    assert "formatDashboardStatusReason(decision.reason)" in html
    assert 'data-strategy-accordion-toggle' in html
    assert 'id="drawdownPercent"' in html
    assert 'id="drawdownPercentile"' in html
    assert 'id="drawdownComparableDate"' in html
    assert 'id="bottomingVolumeRatio"' in html
    assert 'id="bottomingMacroRisk"' in html
    assert 'id="bottomingMaRegime"' in html
    assert 'id="quickPurchaseEvents"' not in html
    assert "getDashboardAhrBadge" not in html
    assert "getDashboardAhrState" not in html
    assert 'document.querySelectorAll(\'[data-strategy-accordion-toggle]\')' in html
    assert "function toggleStrategyCard(toggle)" in html
    assert "event.target.closest('.desktop-drawdown-mode-controls, .drawdown-mode-btn')" in html
    assert "event.key !== 'Enter' && event.key !== ' '" in html
    assert "setDashboardTextIfPresent('bottomingVolumeRatio'" in html
    assert "setDashboardTextIfPresent('drawdownPercent'" in html
    assert "setDashboardTextIfPresent('quickPurchaseEvents'" not in html

    assert ".strategy-card-grid {" in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in html
    assert "grid-template-columns: 1fr;" in html
    assert ".strategy-metric-icon" not in html
    assert "font-family: var(--bs-body-font-family);" in html
    assert ".strategy-card-collapse-toggle {" in mobile_css
    assert ".strategy-advanced-header {" in mobile_css
    assert ".strategy-advanced-panel.is-collapsed .strategy-advanced-body {" in mobile_css
    assert "display: none;" in mobile_css
    assert ".strategy-advanced-panel:not(.is-collapsed) .strategy-advanced-body {" in mobile_css
    assert ".strategy-card-header-meta {" in mobile_css
    assert "font-size: 0.96rem;" in mobile_css
    assert ".strategy-detail-card-title strong {" in mobile_css
    assert "#drawdownCompactLabel {" in mobile_css
    drawdown_label_css = mobile_css[
        mobile_css.index("#drawdownCompactLabel {") :
        mobile_css.index("}", mobile_css.index("#drawdownCompactLabel {"))
    ]
    assert "display: block;" in drawdown_label_css
    assert ".strategy-status-card:not(.is-collapsed) {" not in mobile_css
    assert "margin-bottom: 56px;" not in mobile_css
    assert ".mobile-drawdown-mode-controls {" in mobile_css
    assert "display: inline-flex;" in mobile_css
    assert ".mobile-collapsible.is-collapsed .strategy-detail-card-body {" in mobile_css
    assert "display: none;" in mobile_css


def test_dashboard_drawdown_comparable_shows_peak_and_price_dates():
    html = _dashboard_html()

    assert "function _formatPeakToPrice(item)" in html
    assert "item.peak_date" in html
    assert "item.date" in html
    assert "peakDate ? ` (${peakDate})` : ''" in html
    assert "priceDate ? ` (${priceDate})` : ''" in html


def test_dashboard_drawdown_context_shows_history_freshness():
    html = _dashboard_html()

    assert 'id="drawdownHistoryMeta"' in html
    assert "item.history_end_date" in html
    assert "item.history_stale" in html
    assert "History stale: through" in html
    assert "History through" in html


def test_dashboard_history_resync_action_uses_short_mobile_friendly_label():
    html = _dashboard_html()

    assert "Reset & Sync History" not in html
    assert "Re-sync" in html
    assert "clearBtn.textContent = 'Re-sync';" in html


def test_dashboard_dark_mode_has_matching_tokens():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    dark = css[css.index('html[data-bs-theme="dark"],\nhtml[data-theme="dark"] {') :]
    dark = dark[: dark.index("}")]

    assert "--dashboard-bg: #111214;" in dark
    assert "--dashboard-card-bg: #18191c;" in dark
    assert "--dashboard-border: #26282c;" in dark
    assert "--dashboard-accent: #ececee;" in dark
    assert "--dashboard-on-accent: #111214;" in dark


def test_dashboard_mobile_layout_is_explicitly_scoped():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert "@media (max-width: 768px)" in css
    assert "@media (max-width: 991.98px)" in css
    assert ".holdings-top" in css
    assert ".home-trio" in css
    assert ".app-sidebar" in css


def test_authenticated_templates_share_satsflow_header_and_nav():
    header = (TEMPLATE_DIR / "_shared_header.html").read_text(encoding="utf-8")
    assert 'class="brand-lockup"' in header
    assert 'class="brand-mark"' in header
    assert 'class="brand-title">{{ project_name }}</span>' in header
    assert 'class="mobile-bottom-nav"' in header
    # The phone tab bar lists pages only; recent buys live on Overview.
    mobile = header[header.index('class="mobile-bottom-nav"') :]
    tabs = re.findall(r'<span>([^<]+)</span>', mobile)
    assert tabs == ["Overview", "Insights", "Strategy", "More"]
    assert 'href="/" class="mobile-bottom-nav-item{% if active_page == \'dashboard\' %} active{% endif %}"' in header
    assert 'href="/stats" class="mobile-bottom-nav-item{% if active_page == \'stats\' %} active{% endif %}"' in header
    assert 'href="/strategy" class="mobile-bottom-nav-item{% if active_page == \'strategy\' %} active{% endif %}"' in header
    assert 'class="dropdown-item" href="/settings/binance"' in mobile
    assert '<a class="dropdown-item" href="/admin/data-sources"><i class="bi bi-database-check"></i> Diagnostics</a>' in mobile
    assert 'href="/settings/binance#email-settings"' not in header
    assert "{% if active_page in ['settings', 'admin'] %} active{% endif %}" in mobile
    assert 'class="dropdown-item" href="/analysis/" target="_blank"' in mobile
    assert 'class="mobile-bottom-nav-item mobile-bottom-nav-button' in header
    for label in ["Overview", "Insights", "Strategy", "More"]:
        assert f'aria-label="{label}"' in mobile
        assert f'title="{label}"' in mobile

    expected_active = {
        "index.html": "{% set active_page = 'dashboard' %}",
        "stats.html": "{% set active_page = 'stats' %}",
        "strategy.html": "{% set active_page = 'strategy' %}",
        "binance_settings.html": "{% set active_page = 'settings' %}",
        "admin_data_sources.html": "{% set active_page = 'admin' %}",
    }

    for template_name, active_marker in expected_active.items():
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'class="container app-shell' in html, template_name
        assert active_marker in html, template_name
        assert '{% include "_shared_header.html" %}' in html, template_name


def test_shared_header_uses_compact_account_cluster():
    header = (TEMPLATE_DIR / "_shared_header.html").read_text(encoding="utf-8")
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert 'class="header-utility"' in header
    assert 'aria-label="Signed in account"' in header
    assert 'class="user-avatar"' in header
    assert 'class="user-email" title="{{ user.email }}"' in header
    assert 'class="logout-form"' in header
    assert 'border-start ps-lg-3' not in header
    assert 'border-top border-top-lg-0' not in header
    assert ".header-utility" in css
    assert ".user-email" in css
    assert "text-overflow: ellipsis;" in css


def test_tablets_swap_the_sidebar_for_a_top_bar_and_tabs():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    tablet_css = css[css.index("@media (max-width: 991.98px)") :]
    tablet_css = tablet_css[: tablet_css.index("@media (max-width: 768px)")]

    assert ".app-sidebar {" in tablet_css
    assert ".page-topbar .brand-lockup {" in tablet_css
    assert "display: inline-flex;" in tablet_css
    assert ".mobile-bottom-nav {" in tablet_css
    assert "position: fixed;" in tablet_css


def test_mobile_authenticated_pages_share_compact_header_and_panel_density():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    tablet_css = css[css.index("@media (max-width: 991.98px)") :]
    mobile_css = css[css.index("@media (max-width: 768px)") :]

    assert ".mobile-bottom-nav-item {" in tablet_css
    assert "min-height: 48px;" in tablet_css
    assert ".page-topbar {" in mobile_css
    assert "min-height: 60px;" in mobile_css
    assert ".page-title-block {" in mobile_css
    assert "margin-bottom: 12px;" in mobile_css
    assert ".satsflow-page .card-body," in mobile_css
    assert ".dashboard-page .card-body {" in mobile_css
    assert "padding: 1rem;" in mobile_css


def test_mobile_authenticated_pages_use_compact_form_and_alert_density():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    mobile_css = css[css.index("@media (max-width: 768px)") :]

    assert ".satsflow-page .alert-satsflow," in mobile_css
    assert ".satsflow-page .alert-satsflow-danger {" in mobile_css
    assert "padding: 0.72rem 0.82rem;" in mobile_css
    assert ".satsflow-page .form-label {" in mobile_css
    assert "margin-bottom: 0.25rem;" in mobile_css
    assert ".satsflow-page .form-control," in mobile_css
    assert "min-height: 38px;" in mobile_css
    assert ".satsflow-soft-panel.card-body," in mobile_css
    assert "padding: 0.82rem;" in mobile_css
    assert ".app-shell-settings .dashboard-panel + .dashboard-panel {" in mobile_css
    assert "margin-top: 0.75rem !important;" in mobile_css


def test_settings_mobile_deprioritizes_long_explainer_lists():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    mobile_css = css[css.index("@media (max-width: 768px)") :]

    assert ".app-shell-settings .alert-satsflow ul," in mobile_css
    assert ".app-shell-settings .alert-satsflow-danger ul {" in mobile_css
    assert "display: none;" in mobile_css
    assert ".app-shell-settings .dashboard-panel-header," in mobile_css
    assert "padding: 0.72rem 0.85rem;" in mobile_css
    assert ".app-shell-settings .satsflow-soft-panel .mb-3 {" in mobile_css
    assert "margin-bottom: 0.45rem !important;" in mobile_css


def test_admin_mobile_diagnostics_reduce_log_and_grid_height():
    html = (TEMPLATE_DIR / "admin_data_sources.html").read_text(encoding="utf-8")
    mobile_css = html[html.index("@media (max-width: 576px)") :]

    assert ".log-tail {" in mobile_css
    assert "max-height: 240px;" in mobile_css
    assert ".diagnostics-grid dt," in mobile_css
    assert "padding-top: 0.35rem;" in mobile_css
    assert "#copyDiagnosticsBtn," in mobile_css
    assert "flex: 1 1 120px;" in mobile_css


def test_strategy_mobile_tiers_are_dense_not_full_height_cards():
    html = (TEMPLATE_DIR / "strategy.html").read_text(encoding="utf-8")
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert ".tier-row {" in mobile_css
    assert "gap: 6px;" in mobile_css
    assert "padding: 10px 9px;" in mobile_css
    assert ".tier-input {" in mobile_css
    assert "width: 96px;" in mobile_css


def test_compact_phone_header_comes_from_the_shared_stylesheet():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    tablet_css = css[css.index("@media (max-width: 991.98px)") :]

    assert ".page-topbar .brand-lockup {" in tablet_css
    assert ".page-topbar-title {" in tablet_css

    html = _dashboard_html()
    styles = "".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))
    assert ".brand-mark" not in styles
    assert ".app-sidebar" not in styles
    assert ".sidebar-link" not in styles


def test_shared_version_badge_class_is_used_across_templates():
    for template_name in [
        "admin_data_sources.html",
        "binance_settings.html",
        "index.html",
        "login.html",
        "stats.html",
        "strategy.html",
    ]:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'class="version-badge' in html, template_name


def test_narrow_and_settings_pages_share_the_shell_gutters():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    tablet_css = css[css.index("@media (max-width: 991.98px)") :]

    assert ".app-shell-narrow,\n    .app-shell-settings {\n        padding-left: 20px;" in tablet_css


def test_mobile_navigation_and_action_labels_remain_visible():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert ".btn .btn-text" not in css
    for template_name in [
        "admin_data_sources.html",
        "binance_settings.html",
        "index.html",
        "stats.html",
        "strategy.html",
    ]:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert ".btn .btn-text" not in html, template_name


def test_mobile_navigation_uses_bottom_tab_bar_instead_of_top_icon_row():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    dashboard = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")

    tablet_css = css[css.index("@media (max-width: 991.98px)") :]
    assert ".mobile-bottom-nav {" in tablet_css
    assert "position: fixed;" in tablet_css
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in tablet_css

    dashboard_mobile_css = dashboard[dashboard.find("@media (max-width: 768px)") :]
    assert ".transactions-table-wrap {" in dashboard_mobile_css
    assert "display: none;" in dashboard_mobile_css


def test_diagnostics_link_is_only_active_on_the_diagnostics_page():
    header = (TEMPLATE_DIR / "_shared_header.html").read_text(encoding="utf-8")
    link = header[header.index('<a href="/admin/data-sources" class="sidebar-link') :]
    link = link[: link.index("</a>")]
    assert "{% if active_page == 'admin' %} active{% endif %}" in link
    assert "nav-accent" not in header


def test_mobile_version_badge_does_not_overlay_content():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    base_badge_css = css[css.index(".version-badge {") : css.index(".login-shell")]
    assert "position: static;" in base_badge_css
    assert "position: fixed;" not in base_badge_css

    mobile_css = css[css.index("@media (max-width: 768px)") :]
    assert ".version-badge" in mobile_css
    assert "position: static;" in mobile_css


def test_stats_uses_satsflow_badge_and_reserve_palette():
    html = (TEMPLATE_DIR / "stats.html").read_text(encoding="utf-8")

    assert 'class="stats-balance-badge"' in html
    assert "badge bg-light text-dark" not in html
    assert "#071323" not in html
    assert "#edf3fa" not in html


def test_stats_dark_table_uses_satsflow_tokens():
    html = (TEMPLATE_DIR / "stats.html").read_text(encoding="utf-8")

    assert "--bs-table-bg: var(--dashboard-card-bg-solid);" in html
    assert "--bs-table-border-color: var(--dashboard-border);" in html
    assert "--bs-table-bg: #1b2430;" not in html
    assert "#2f3a49" not in html


def test_dashboard_info_badges_do_not_use_bootstrap_cyan():
    html = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")

    assert "bg-info" not in html
    assert "MANUAL (blue)" not in html
    assert "satsflow-info-badge" in html


def test_binance_settings_uses_satsflow_status_surfaces():
    html = (TEMPLATE_DIR / "binance_settings.html").read_text(encoding="utf-8")

    assert "alert-info" not in html
    assert "btn-info" not in html
    assert "card bg-light" not in html
    assert "card-header bg-danger" not in html
    assert "alert-satsflow" in html
    assert "satsflow-soft-panel" in html


def test_binance_settings_does_not_constrain_shared_header_container():
    html = (TEMPLATE_DIR / "binance_settings.html").read_text(encoding="utf-8")
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert ".container { max-width: 900px; }" not in html
    assert ".app-shell-settings > .dashboard-panel" in css
