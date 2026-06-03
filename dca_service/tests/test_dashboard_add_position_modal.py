from pathlib import Path


def test_dashboard_add_position_modal_and_safe_polling_are_present():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="openAddPositionBtn"' in html
    assert 'data-bs-target="#addPositionModal"' in html
    assert "Extra Buy" in html
    assert "Extra BTC Buy" in html
    assert "One-time buy outside your DCA schedule." in html
    assert "Check Strategy" in html
    assert "Confirm Extra Buy" in html
    assert "Add Position" not in html
    assert "Generate Advice" not in html
    assert "Buy (Confirm)" not in html
    assert "No advice yet." not in html
    assert "No strategy check yet." in html
    assert 'id="addPositionModal"' in html
    assert 'id="addPositionUsdcInput"' in html
    assert 'id="addPositionPriceInput"' in html
    assert 'id="addPositionPriceInput" type="number" min="1" step="0.01" class="form-control" required readonly' in html
    assert "const ADD_POSITION_PRICE_POLL_INTERVAL_MS = 3000;" in html
    assert "fetch('/api/stats/realtime-price?symbol=BTCUSDC')" in html
    assert "fetch('/api/stats/add-position/advice'" in html
    assert "fetch('/api/stats/add-position/confirm'" in html
    assert "previewCache.suggested_amount_usd" not in html
    assert "if (amountInput) amountInput.value = '';" in html
    assert 'id="fixedDcaCapBadge"' in html
    assert 'id="previewActionSubtext"' in html
    assert "Cap ≤" in html


def test_dashboard_current_price_uses_extra_buy_realtime_poll_interval():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "function updateDashboardRealtimePrice(payload)" in html
    assert "function fetchRealtimePriceForDashboard({ silent = true } = {})" in html
    assert "let dashboardPricePollTimer = null;" in html
    assert "setInterval(() => {\n                fetchRealtimePriceForDashboard({ silent: true });\n            }, ADD_POSITION_PRICE_POLL_INTERVAL_MS);" in html
    assert "previewPriceEl.textContent = `$${price.toLocaleString()}`;" in html
    assert "window.__dashboardPriceUsd = price;" in html
    assert "updateMobileFiatEstimate();" in html


def test_extra_buy_reuses_dashboard_realtime_price_polling_loop():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "function updateAddPositionRealtimePrice(payload)" in html
    assert "startAddPositionPricePolling() {\n            startDashboardPricePolling();\n        }" in html
    assert "let addPositionPricePollTimer = null;" not in html
    assert "fetchRealtimePriceForAddPosition({ silent: true });" not in html


def test_dashboard_copy_distinguishes_scheduled_action_from_extra_buy():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "Next Scheduled Action" in html
    assert "Suggested Action" not in html
    assert "function updatePreviewActionState(decision)" in html
    assert "actionText = `Will buy ${formatDashboardUsd(suggestedAmount)}`;" in html
    assert "actionText = 'Will wait';" in html
    assert "subtext = 'Price above cap';" in html
    assert "subtext = `Next run at ${getDashboardScheduleRunText(strategy)}`;" in html


def test_dashboard_early_hydration_guards_late_helper_calls():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    early_hydration_script = html[
        html.index("// Hydrate wallet and DCA preview from cache")
        : html.index("</script>", html.index("// Hydrate wallet and DCA preview from cache"))
    ]

    assert "if (typeof updateFixedDcaStopCapDisplay === 'function')" in early_hydration_script
    assert "if (typeof updatePreviewActionState === 'function')" in early_hydration_script


def test_fixed_dca_stop_cap_is_visible_without_disabling_extra_buy():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "function updateFixedDcaStopCapDisplay(strategy)" in html
    assert "fixed_dca_stop_price_usd" in html
    assert "strategy.strategy_type === 'fixed_dca'" in html
    assert "Cap ≤" in html
    assert 'id="fixedDcaCapBadge"' in html
    assert 'id="fixedDcaCapBadgeText"' in html
    assert 'class="badge d-none" id="fixedDcaCapBadge"' in html
    assert 'id="fixedDcaStopCapMetric"' not in html
    assert 'id="fixedDcaStopCapValue"' not in html
    assert 'id="fixedDcaGuardrail"' not in html
    assert 'id="fixedDcaGuardrailText"' not in html
    assert "Fixed DCA cap" not in html
    assert "Auto DCA only" not in html
    assert "toFiniteNumber(strategy?.fixed_dca_stop_price_usd)" not in html

    button_state_block = html[
        html.index("// Update extra buy button state"):
        html.index("const addAmountInput = document.getElementById('addPositionUsdcInput');")
    ]
    assert "decision.can_execute" not in button_state_block
    assert "fixed_dca_stop_price" not in button_state_block


def test_fixed_dca_stop_cap_badge_lives_in_strategy_status_pills():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    pills_start = html.index('<div class="strategy-status-pills">')
    pills_end = html.index("</div>", pills_start)
    pills_markup = html[pills_start:pills_end]
    metric_grid_start = html.index('<div class="strategy-metric-grid')

    assert 'id="fixedDcaCapBadge"' in pills_markup
    assert html.index('id="fixedDcaCapBadge"') < metric_grid_start


def test_optional_fixed_dca_stop_cap_badge_has_no_default_cap_copy():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    cap_badge_start = html.index('<span class="badge d-none" id="fixedDcaCapBadge"')
    cap_badge_end = html.index("</span>", html.index('id="fixedDcaCapBadgeText"', cap_badge_start)) + len("</span>")
    cap_badge_markup = html[cap_badge_start:cap_badge_end]

    assert 'id="fixedDcaCapBadgeText"></span>' in cap_badge_markup
    assert "textEl.textContent = '';" in html
    assert "Pause Above --" not in html
    assert "Cap ≤ --" not in html


def test_fixed_dca_stop_cap_badge_mobile_text_stays_compact():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    mobile_css = html[html.index("@media (max-width: 768px)"):]

    assert "#fixedDcaCapBadge" in mobile_css
    assert "max-width: 8.6rem;" in mobile_css
    assert "overflow: hidden;" in mobile_css
    assert "text-overflow: ellipsis;" in mobile_css


def test_strategy_action_panel_is_inline_on_desktop_and_separate_on_mobile():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'class="strategy-metric strategy-action-metric"' not in html
    assert 'class="strategy-action-panel strategy-action-panel-desktop is-waiting"' in html
    assert 'class="strategy-action-panel strategy-action-panel-mobile is-waiting"' in html
    assert 'id="strategyActionPanelMobile"' in html
    assert 'id="previewActionSubtext"' in html
    assert 'id="previewActionMobile"' in html
    assert 'id="previewActionSubtextMobile"' in html
    assert "Price above cap" in html
    assert "Next run at" in html

    grid_start = html.index('class="strategy-metric-grid')
    desktop_action_start = html.index('id="strategyActionPanel"')
    mobile_action_start = html.index('id="strategyActionPanelMobile"')

    assert grid_start < desktop_action_start < mobile_action_start

    mobile_css = html[html.index("@media (max-width: 768px)"):]

    assert "grid-template-columns: repeat(5, minmax(0, 1fr));" in html
    assert ".strategy-action-panel-desktop .strategy-label {" in html
    assert "white-space: nowrap;" in html[
        html.index(".strategy-action-panel-desktop .strategy-label {") :
        html.index("}", html.index(".strategy-action-panel-desktop .strategy-label {"))
    ]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_css
    assert ".strategy-action-panel-desktop" in mobile_css
    assert "display: none;" in mobile_css
    assert ".strategy-action-panel-mobile" in mobile_css
    assert "display: flex;" in mobile_css
    assert "min-height: 94px;" in mobile_css
    assert ".strategy-action-main" in mobile_css
    assert ".strategy-action-panel.is-buying .strategy-action" in html
    assert ".strategy-action-panel.is-waiting .strategy-action" in html
    assert "#8fca57" not in html
    assert "color: var(--dashboard-accent-strong) !important;" in html


def test_dashboard_add_position_button_uses_accent_class_without_success_flash():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")
    button_markup = html[
        html.index('<button id="openAddPositionBtn"')
        : html.index("</button>", html.index('<button id="openAddPositionBtn"'))
    ]

    assert 'class="btn btn-dashboard-accent"' in button_markup
    assert "btn-success" not in button_markup
    assert ".btn-dashboard-accent {" in html
    assert ".btn-dashboard-accent:hover," in html


def test_add_position_no_buy_advice_does_not_enable_confirm_buy():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "const actionCode = payload?.guidance?.action_code;" in html
    assert "if (actionCode === 'NO_BUY')" in html
    assert "Strategy check says no extra buy right now." in html
    assert "setAddPositionActionMode('advice');" in html
