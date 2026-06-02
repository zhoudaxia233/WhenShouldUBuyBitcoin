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


def test_dashboard_uses_orange_bitcoin_visual_system():
    html = _dashboard_html()
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert 'href="/static/app.css"' in html
    assert "--dashboard-accent: #ff8a00;" in css
    assert "--dashboard-accent-strong: #f97316;" in css
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


def test_dashboard_wallet_uses_metric_cards_and_progress_ring():
    html = _dashboard_html()

    assert 'class="wallet-card-grid"' in html
    assert 'class="metric-card metric-card-primary"' in html
    assert 'class="metric-card progress-metric-card"' in html
    assert 'id="progressRing"' in html
    assert "--progress-value" in html
    assert "progressRingEl.style.setProperty('--progress-value'" in html


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

    wallet_index = html.index('class="wallet-overview-section')
    strategy_index = html.index('DCA Strategy')
    transactions_index = html.index('Transaction History')
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
    assert "width: 100%;" in html[html.index(".dashboard-accent-progress {") : html.index(".dashboard-accent-progress .progress-bar")]
    assert "max-width: none;" in html[html.index(".dashboard-accent-progress {") : html.index(".dashboard-accent-progress .progress-bar")]
    assert "background: var(--dashboard-ring-track);" in html[html.index(".dashboard-accent-progress {") : html.index(".dashboard-accent-progress .progress-bar")]
    assert "Spent $0.00 of $600.00" not in html
    assert 'id="transactionsCards"' in html


def test_dashboard_mobile_app_cards_are_hydrated_from_existing_data():
    html = _dashboard_html()

    assert "function setDashboardTextIfPresent(id, value)" in html
    assert "window.__dashboardTotalBtc = totalBtc;" in html
    assert "window.__dashboardPriceUsd = priceValue;" in html
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


def test_dashboard_mobile_keeps_reference_density_and_card_shapes():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert ".wallet-card-grid {" in mobile_css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_css
    assert ".metric-card-primary {" in mobile_css
    assert "background: linear-gradient(135deg, #ff9a16 0%, #ff7a00 100%);" in mobile_css
    assert "grid-column: 1 / -1;" in mobile_css
    assert "min-height: 128px;" in mobile_css
    assert ".progress-metric-card {" in mobile_css
    assert "min-height: 72px;" in mobile_css
    assert ".wallet-card-grid .mobile-card-icon {" in mobile_css
    assert ".progress-metric-card .progress-ring {" in mobile_css
    assert ".dca-budget-card {" not in mobile_css
    assert ".wallet-card-grid .metric-card:not(.metric-card-primary) .metric-value {" in mobile_css
    assert "white-space: nowrap;" in mobile_css
    assert ".strategy-metric-grid {" in mobile_css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in mobile_css
    assert "min-height: 44px;" in mobile_css
    assert "#bottomingSignalBox {" not in mobile_css
    assert 'id="bottomingSignalStatus"' in html
    assert 'id="bottomingSignalMetrics"' in html
    assert 'id="bottomingSignalMacro"' in html
    assert 'id="mobileBottomingSummary"' not in html
    assert 'href="/stats">View Details' not in html
    assert ".mobile-transaction-card-list {" in mobile_css
    assert ".transactions-table-wrap {" in mobile_css
    assert "display: none;" in mobile_css


def test_dashboard_mobile_strategy_badges_use_compact_single_row_labels():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert "function setResponsiveBadgeText(element, fullText, compactText)" in html
    assert "function refreshResponsiveBadgeText()" in html
    assert "setResponsiveBadgeText(scheduleDisplayEl, scheduleFullText, scheduleCompactText);" in html
    assert "const scheduleCompactText = `${freq} ${strategy.execution_time_utc}`;" in html
    assert "setResponsiveBadgeText(dataSourceBadgeEl, `Source: ${preview.metrics_source.label}`, preview.metrics_source.label);" in html
    assert "setResponsiveBadgeText(sourceBadge, `Source: ${metricsSource.label}`, metricsSource.label);" in html
    assert "setResponsiveBadgeText(badge, 'Mode: LIVE', 'LIVE');" in html
    assert "setResponsiveBadgeText(badge, 'Mode: Dry Run', 'Dry Run');" in html
    assert ".live-mode-dot {" in html
    assert "@keyframes liveModePulse" in html
    assert "ensureLiveModeBadgeDot(badge);" in html
    assert "badge.classList.add('live-mode-active');" in html
    assert "removeLiveModeBadgeDot(badge);" in html
    assert ".strategy-status-pills {" in mobile_css
    assert "flex-wrap: nowrap;" in mobile_css
    assert "overflow-x: hidden;" in mobile_css


def test_dashboard_mobile_strategy_cta_stays_above_bottom_nav():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert ".dca-strategy-panel .dashboard-panel-header {" in mobile_css
    assert "padding: 0.48rem 0.72rem !important;" in mobile_css
    assert ".dca-strategy-panel .card-body {" in mobile_css
    assert "padding: 0.42rem 0.58rem 0.56rem !important;" in mobile_css
    assert ".strategy-metric {" in mobile_css
    assert "min-height: 44px;" in mobile_css
    assert ".strategy-metric-content {" in mobile_css
    assert "min-height: 32px;" in mobile_css
    assert ".strategy-actions .btn {" in mobile_css
    assert "min-height: 32px;" in mobile_css
    assert "padding: 0.3rem 0.5rem;" in mobile_css


def test_dashboard_dca_strategy_uses_structured_reference_cards():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert 'class="card dashboard-panel dca-strategy-panel mb-4"' in html
    assert 'class="strategy-status-pills"' in html
    assert 'class="strategy-metric-content"' in html
    assert 'id="previewAhrState"' not in html
    assert 'strategy-mini-chip' not in html
    assert 'class="strategy-action-coin"' in html
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
    assert "min-height: 84px;" in html
    assert "padding: 0.95rem 1.2rem;" in html
    assert "font-size: 1.16rem;" in html
    assert ".strategy-metric .strategy-label {" in html
    assert "margin-bottom: 0.45rem !important;" in html
    assert ".strategy-metric-content {" in html
    assert ".strategy-action {" in html
    assert "white-space: nowrap;" in html
    assert ".strategy-value-row {" in html
    assert "justify-content: space-between;" in html
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

    assert 'html[data-bs-theme="dark"]' in css
    assert "--dashboard-bg: #12100d;" in css
    assert "--dashboard-card-bg: #181512;" in css
    assert "--dashboard-border: #352a1f;" in css
    assert "--dashboard-accent-soft: rgba(255, 138, 0, 0.16);" in css


def test_dashboard_mobile_layout_is_explicitly_scoped():
    html = _dashboard_html()
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert "@media (max-width: 768px)" in css
    assert ".wallet-card-grid" in html
    assert ".strategy-metric-grid" in html
    assert ".dashboard-nav" in css


def test_authenticated_templates_share_satsflow_header_and_nav():
    header = (TEMPLATE_DIR / "_shared_header.html").read_text(encoding="utf-8")
    assert 'class="brand-lockup"' in header
    assert 'class="brand-mark"' in header
    assert 'class="brand-title">{{ project_name }}</span>' in header
    assert 'class="nav-actions dashboard-nav' in header
    assert 'class="mobile-bottom-nav"' in header
    assert 'href="/" class="btn dashboard-nav-btn{% if active_page == \'dashboard\' %} active{% endif %}"' in header
    assert 'href="/" class="mobile-bottom-nav-item{% if active_page == \'dashboard\' %} active{% endif %}"' in header
    assert 'id="settingsDropdown"' in header
    assert 'class="dropdown-item" href="/strategy"' in header
    assert 'class="dropdown-item" href="/settings/binance"' in header
    assert 'href="/settings/binance#email-settings"' not in header
    assert 'href="/stats" class="btn dashboard-nav-btn{% if active_page == \'stats\' %} active{% endif %}"' in header
    assert 'href="/stats" class="mobile-bottom-nav-item{% if active_page == \'stats\' %} active{% endif %}"' in header
    assert 'href="/admin/data-sources" class="btn dashboard-nav-btn nav-accent admin-diagnostics-link{% if active_page == \'admin\' %} active{% endif %}"' in header
    assert 'href="/admin/data-sources" class="mobile-bottom-nav-item' not in header
    assert '<a class="dropdown-item" href="/admin/data-sources"><i class="bi bi-database-check"></i> Diagnostics</a>' in header
    assert 'href="/analysis/" class="btn dashboard-nav-btn"' in header
    assert 'class="mobile-bottom-nav-item mobile-bottom-nav-button' in header
    for label in ["Dashboard", "Settings", "Diagnostics", "Analytics", "WSUB", "More"]:
        assert f'aria-label="{label}"' in header
        assert f'title="{label}"' in header

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


def test_tablet_header_stacks_before_navigation_wraps():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    tablet_css = css[css.index("@media (max-width: 991.98px)") :]

    assert ".shared-header-layout" in tablet_css
    assert ".shared-header-right" in tablet_css
    assert "flex-direction: column;" in tablet_css
    assert "align-items: center;" in tablet_css


def test_mobile_authenticated_pages_share_compact_header_and_panel_density():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    mobile_css = css[css.index("@media (max-width: 768px)") :]

    assert ".dashboard-header {" in mobile_css
    assert "margin-bottom: 10px;" in mobile_css
    assert ".brand-mark {" in mobile_css
    assert "width: 36px;" in mobile_css
    assert ".brand-title {" in mobile_css
    assert "font-size: 1.34rem;" in mobile_css
    assert ".dashboard-nav {" in mobile_css
    assert "display: none !important;" in mobile_css
    assert ".header-utility .user-chip {" in mobile_css
    assert "display: none;" in mobile_css
    assert ".mobile-bottom-nav {" in mobile_css
    assert "position: fixed;" in mobile_css
    assert ".mobile-bottom-nav-item {" in mobile_css
    assert "min-height: 44px;" in mobile_css
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


def test_dashboard_inline_mobile_styles_do_not_override_shared_compact_header():
    html = _dashboard_html()
    mobile_css = html[html.index("@media (max-width: 768px)") :]

    assert ".brand-mark {" in mobile_css
    assert "width: 36px;" in mobile_css
    assert ".brand-title {" in mobile_css
    assert "font-size: 1.34rem;" in mobile_css
    assert ".dashboard-nav {" in mobile_css
    assert "display: none !important;" in mobile_css
    assert ".header-utility .user-chip {" in mobile_css
    assert "display: none !important;" in mobile_css
    assert ".theme-toggle-btn {" in mobile_css
    assert "width: 36px;" in mobile_css
    assert "height: 36px;" in mobile_css


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


def test_narrow_authenticated_pages_allow_header_nav_to_wrap():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert "@media (max-width: 991.98px)" in css
    assert ".app-shell-narrow .dashboard-nav" in css
    assert ".app-shell-settings .dashboard-nav" in css
    assert "flex-wrap: wrap !important;" in css


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

    mobile_css = css[css.index("@media (max-width: 768px)") :]
    assert ".dashboard-nav {" in mobile_css
    assert "display: none !important;" in mobile_css
    assert ".mobile-bottom-nav {" in mobile_css
    assert "position: fixed;" in mobile_css
    assert "grid-template-columns:" in mobile_css

    dashboard_mobile_css = dashboard[dashboard.find("@media (max-width: 768px)") :]
    assert ".dashboard-nav {" in dashboard_mobile_css
    assert "display: none !important;" in dashboard_mobile_css
    assert ".transactions-table-wrap {" in dashboard_mobile_css
    assert "display: none;" in dashboard_mobile_css


def test_diagnostics_nav_accent_is_distinct_from_active_state():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert ".dashboard-nav-btn.active,\n.dashboard-nav-btn.nav-accent" not in css
    assert ".dashboard-nav-btn.nav-accent:not(.active)" in css
    assert ".dashboard-nav-btn.nav-accent.active" in css


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
