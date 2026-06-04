from pathlib import Path


def test_dashboard_add_position_modal_and_safe_polling_are_present():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="openAddPositionBtn"' in html
    assert 'data-bs-target="#addPositionModal"' in html
    assert "Extra Buy" in html
    assert "Extra BTC Buy" in html
    assert "This action won't change your DCA settings." not in html
    assert "Check Strategy" not in html
    assert "Confirm Extra Buy" not in html
    assert "Preview ${formatExtraBuyUsdcCompact(amount)} USDC buy" in html
    assert "Confirm ${formatExtraBuyUsdcCompact(amount)} USDC buy" in html
    assert "Enter amount to preview" in html
    assert "Check strategy before purchase" not in html
    assert "Add Position" not in html
    assert "Generate Advice" not in html
    assert "Buy (Confirm)" not in html
    assert "No advice yet." not in html
    assert "Strategy decision pending" in html
    assert 'id="addPositionModal"' in html
    assert 'id="addPositionUsdcInput"' in html
    assert 'id="addPositionPriceInput"' in html
    assert 'id="addPositionCtaIcon"' in html
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


def test_extra_buy_cta_icon_tracks_current_action_state():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    update_block = html[
        html.index("function updateAddPositionInputState()")
        : html.index("function formatExtraBuySignedUsd(value)")
    ]

    assert '<i class="bi bi-pencil-square" id="addPositionCtaIcon" aria-hidden="true"></i>' in html
    assert "function setAddPositionCtaIcon(iconName)" in html
    assert "setAddPositionCtaIcon('lock');" in update_block
    assert "setAddPositionCtaIcon(hasAmount ? 'check-circle' : 'pencil-square');" in update_block
    assert "setAddPositionCtaIcon(hasAmount ? 'eye' : 'pencil-square');" in update_block
    assert '<i class="bi bi-lock" aria-hidden="true"></i>' not in html


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


def test_extra_buy_realtime_price_shows_live_numeric_value_on_desktop_and_mobile():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    realtime_price_block = html[
        html.index("function updateAddPositionRealtimePrice(payload)")
        : html.index("async function fetchRealtimePriceForDashboard")
    ]

    assert "const displayEl = document.getElementById('addPositionPriceDisplay');" in realtime_price_block
    assert "displayEl.textContent = hasPrice ? formatExtraBuyUsd(price) : '$--';" in realtime_price_block
    assert "metaEl.textContent = hasPrice ? 'Updated just now' : 'Price pending';" in realtime_price_block
    assert '<strong class="extra-buy-price-label" id="addPositionPriceDisplay">$--</strong>' in html
    assert '<strong class="extra-buy-price-label">BTC price</strong>' not in html
    assert "Loading realtime BTC price" not in html
    assert "Failed to refresh BTC price" not in html
    assert "Enter a valid BTC price first." not in html
    assert ".extra-buy-price-strip {\n            display: flex;" in html
    assert "gap: 0.62rem;" in html
    assert ".extra-buy-price-card .form-text {\n            color: var(--dashboard-muted);" in html
    assert "font-size: 0.96rem;" in html
    assert "font-weight: 650;" in html

    mobile_css = html[html.index("@media (max-width: 768px)"):]
    assert ".extra-buy-price-strip {\n                display: flex;" in mobile_css
    assert "flex-wrap: wrap;" in mobile_css
    assert ".extra-buy-price-card .form-text {\n                font-size: 0.72rem;" in mobile_css


def test_extra_buy_mobile_inputs_use_ios_safe_font_size():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")
    mobile_css = html[html.index("@media (max-width: 768px)"):]
    mobile_input_rule = mobile_css[
        mobile_css.index(".extra-buy-control-card .form-control {") :
        mobile_css.index("}", mobile_css.index(".extra-buy-control-card .form-control {"))
    ]

    assert "font-size: 16px;" in mobile_input_rule
    assert "font-size: 0.82rem;" not in mobile_input_rule


def test_extra_buy_advice_request_does_not_send_dashboard_valuation_override():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    request_body = html[
        html.index("function buildAddPositionAdviceRequestBody")
        : html.index("async function fetchAddPositionAdvice")
    ]
    realtime_update = html[
        html.index("function updateDashboardRealtimePrice")
        : html.index("function updateAddPositionRealtimePrice")
    ]

    assert "dashboard_ahr999" not in request_body
    assert "window.__latestDrawdownDecision?.ahr999_value" not in request_body
    assert "toExtraBuyFiniteNumber(guidance.dashboard_ahr999)" not in html
    assert "const ahr999 = Number(payload?.ahr999);" in realtime_update
    assert "window.__latestDrawdownDecision.ahr999_value = ahr999;" in realtime_update


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
        html.index("async function loadPreview()")
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
    assert "if (actionCode === 'NO_BUY' || payload?.confirm_blocked)" in html
    assert "renderAddPositionDecisionReason(payload);" in html
    assert "getAddPositionDecisionReason(guidance)" in html
    assert "Strategy says wait" in html
    assert "setAddPositionHardBlocked(true);" in html
    assert "function setAddPositionAmountDisabled(disabled)" in html
    assert "setAddPositionActionMode('advice');" in html


def test_extra_buy_no_buy_disables_amount_entry_and_hides_buy_signal_cards():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]
    hard_blocked_block = html[
        html.index("function setAddPositionHardBlocked(blocked)")
        : html.index("function updateDashboardRealtimePrice")
    ]
    no_buy_block = html[
        html.index("if (actionCode === 'NO_BUY' || payload?.confirm_blocked)")
        : html.index("} else if (addPositionConfirmToken)")
    ]
    reset_block = html[
        html.index("function resetAddPositionGuidanceSummary()")
        : html.index("function renderAddPositionGuidanceSummary(payload)")
    ]

    assert 'id="addPositionAmountLock"' in modal_markup
    assert 'class="extra-buy-input-lock"' in modal_markup
    assert "amountWrap.classList.toggle('is-disabled', Boolean(disabled));" in html
    assert ".extra-buy-input-lock {" in html
    assert ".extra-buy-amount-input-wrap.is-disabled .extra-buy-input-lock {" in html
    assert ".extra-buy-amount-input-wrap.is-disabled .form-control {" in html
    assert "amountInput.disabled = Boolean(disabled);" in html
    assert "setAddPositionAmountDisabled(addPositionHardBlocked);" in hard_blocked_block
    assert "hideAddPositionBuySignals();" in no_buy_block
    assert "setAddPositionAmountDisabled(false);" in reset_block


def test_extra_buy_no_buy_decision_reason_prefers_backend_reason_fields():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]
    reason_helper = html[
        html.index("function getAddPositionDecisionReason(guidance)")
        : html.index("function renderAddPositionDecisionReason(payload)")
    ]
    decision_renderer = html[
        html.index("function renderAddPositionDecisionReason(payload)")
        : html.index("function scrollAddPositionModalToTop")
    ]
    no_buy_decision_branch = decision_renderer[
        decision_renderer.index("if (actionCode === 'NO_BUY' || payload?.confirm_blocked)")
        : decision_renderer.index("return;", decision_renderer.index("if (actionCode === 'NO_BUY' || payload?.confirm_blocked)"))
    ]
    tone_renderer = html[
        html.index("function setAddPositionDecisionTone(tone)")
        : html.index("function setAddPositionDecisionReason")
    ]

    assert 'id="addPositionSignalCopy"' in modal_markup
    assert "guidance?.call_reason" in reason_helper
    assert "guidance?.final_call" in reason_helper
    assert "guidance?.analysis_text" in reason_helper
    assert "sanitizeExtraBuySuggestionCopy" in reason_helper
    assert "setExtraBuyText('addPositionSignalCopy', getAddPositionDecisionReason(guidance));" in no_buy_decision_branch
    assert "setAddPositionDecisionReason(" in no_buy_decision_branch
    assert "'Strategy says wait'" in no_buy_decision_branch
    assert "panel.classList.toggle('d-none', tone === 'ready' || tone === 'waiting');" in tone_renderer
    assert "Strategy check says no extra buy right now." not in no_buy_decision_branch


def test_extra_buy_buy_decision_does_not_surface_amount_sizing_reason():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    decision_renderer = html[
        html.index("function renderAddPositionDecisionReason(payload)")
        : html.index("function scrollAddPositionModalToTop")
    ]
    tone_renderer = html[
        html.index("function setAddPositionDecisionTone(tone)")
        : html.index("function setAddPositionDecisionReason")
    ]
    ready_branch = decision_renderer[
        decision_renderer.index("setAddPositionDecisionReason(\n                'Strategy signals available'")
        :
    ]

    assert "const ADD_POSITION_DEFAULT_SIGNAL_COPY =" in html
    assert "'Choose your own amount, then preview before confirming.'" in ready_branch
    assert "setExtraBuyText('addPositionSignalCopy', ADD_POSITION_DEFAULT_SIGNAL_COPY);" in decision_renderer
    assert "getAddPositionDecisionReason(guidance)" not in ready_branch
    assert "call_reason" not in ready_branch
    assert "panel.classList.toggle('d-none', tone === 'ready' || tone === 'waiting');" in tone_renderer


def test_extra_buy_buy_status_does_not_announce_backend_amount_suggestion():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    strategy_check_block = html[
        html.index("async function runAddPositionAdvice()")
        : html.index("async function confirmAddPositionBuy()")
    ]
    status_block = strategy_check_block[
        strategy_check_block.index("if (statusEl) {")
        : strategy_check_block.index("}\n                if (actionCode === 'NO_BUY' || payload?.confirm_blocked)")
    ]

    assert "statusEl.textContent = 'Strategy check complete.';" in status_block
    assert "finalCall" not in status_block
    assert "statusEl.textContent = `Strategy check: ${finalCall}`;" not in status_block


def test_extra_buy_modal_surfaces_are_opaque_over_dashboard_content():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "background-color: #0d141b;" in html
    assert "rgba(18, 27, 36, 0.74)" not in html
    assert "rgba(18, 27, 36, 0.72)" not in html
    assert "rgba(18, 27, 36, 0.76)" not in html


def test_extra_buy_modal_uses_readable_dark_surface_tokens_in_light_theme():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_content_rule = html[
        html.index(".extra-buy-modal-content {")
        : html.index("}", html.index(".extra-buy-modal-content {"))
    ]

    assert "--dashboard-text: #f5f7fa;" in modal_content_rule
    assert "--dashboard-muted: #aeb7c2;" in modal_content_rule
    assert ".extra-buy-modal-content .btn-close {" in html
    assert "filter: invert(1);" in html


def test_extra_buy_modal_uses_streamlined_decision_flow_without_recommendation_amounts():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]

    assert 'extra-buy-modal-content' in modal_markup
    assert 'class="modal-dialog modal-lg modal-dialog-scrollable extra-buy-modal-dialog"' in modal_markup
    assert 'class="extra-buy-header-icon"' in modal_markup
    assert 'id="addPositionRecommendedAmount"' not in modal_markup
    assert 'id="addPositionRecommendedCaption"' not in modal_markup
    assert 'id="addPositionBuySignalsPanel"' in modal_markup
    assert 'id="addPositionSummaryGrid"' in modal_markup
    assert 'id="addPositionMarketSnapshotGrid"' not in modal_markup
    assert 'id="addPositionImpactPanel"' in modal_markup
    assert 'id="addPositionAdvancedPanel"' not in modal_markup
    assert 'id="addPositionAdvancedToggle"' not in modal_markup
    assert 'id="addPositionAdviceText"' not in modal_markup
    assert 'id="addPositionDecisionPanel"' in modal_markup
    assert 'id="addPositionDecisionTitle"' in modal_markup
    assert 'id="addPositionDecisionReason"' in modal_markup
    assert '<pre id="addPositionAdviceText"' not in modal_markup
    assert "MARKET ASSESSMENT" not in modal_markup
    assert "Suggested Range" not in modal_markup
    assert "SUGGESTED RANGE" not in modal_markup
    assert "Current recommendation" not in modal_markup
    assert 'id="addPositionRecommendedRange"' not in modal_markup
    assert 'id="addPositionRangeMinLabel"' not in modal_markup
    assert 'id="addPositionRangeMaxLabel"' not in modal_markup
    assert 'id="addPositionRangeMarker"' not in modal_markup
    assert 'id="addPositionBestAmount"' not in modal_markup
    assert "Best Amount" not in modal_markup
    assert "This is a market-based suggestion and is independent of the amount you choose to buy." not in modal_markup
    assert "Strategy signals available" in modal_markup
    assert "Review the signal, choose your own amount, then preview before confirming." in modal_markup
    assert "This is not financial advice." in modal_markup
    assert "Amount to Buy" in modal_markup
    assert "Enter USDC amount" in modal_markup
    assert 'class="extra-buy-amount-mode-grid"' not in modal_markup
    assert 'data-extra-buy-size' not in modal_markup
    assert "Small" not in modal_markup
    assert "Regular" not in modal_markup
    assert "Large" not in modal_markup
    assert "Custom" not in modal_markup
    assert 'id="addPositionPriceDisplay"' in modal_markup
    assert "BTC price" not in modal_markup
    assert "Price pending" in modal_markup
    assert "Refresh" in modal_markup
    assert "YOUR ORDER" not in modal_markup
    assert "Impact preview" in modal_markup
    assert modal_markup.count("Enter an amount to preview impact") == 1
    assert "Impact on your position" not in modal_markup
    assert "Average cost" in modal_markup
    assert "Position impact" in modal_markup
    assert "Decision reason" in modal_markup
    assert "Strategy decision pending" in modal_markup
    assert "Why this signal?" not in modal_markup
    assert "Key indicators supporting the current market view" not in modal_markup
    assert "Below Avg Cost" not in modal_markup
    assert "AHR999" not in modal_markup
    assert "Fear &amp; Greed" not in modal_markup
    assert "Bottoming Signals" not in modal_markup
    assert "Advanced analysis" not in modal_markup
    assert "Why this makes sense" not in modal_markup
    assert "Market snapshot" not in modal_markup
    assert "Quick amount shortcuts" not in modal_markup
    assert "data-add-amount" not in modal_markup

    assert "function renderAddPositionGuidanceSummary(payload)" in html
    assert "const input = payload?.input || {};" in html
    assert "toExtraBuyFiniteNumber(input.current_price_usd)" in html
    assert "function sanitizeExtraBuySuggestionCopy(text)" in html
    assert "function formatExtraBuyAnalysisText(guidance)" in html
    assert "renderAddPositionDecisionReason(payload);" in html
    assert "setExtraBuyText('addPositionDecisionReason', reason);" in html
    assert "Current recommendation loaded." not in html
    assert "Loading current recommendation" not in html
    assert "function resetAddPositionGuidanceSummary()" in html
    assert "renderAddPositionGuidanceSummary(payload);" in html
    assert "resetAddPositionGuidanceSummary();" in html
    assert ".extra-buy-modal-content" in html
    assert ".extra-buy-recommendation-value" not in html
    assert ".extra-buy-quick-grid" not in html
    assert ".extra-buy-quick-btn" not in html
    assert ".extra-buy-amount-mode-grid" not in html
    assert ".extra-buy-amount-mode-btn" not in html
    assert ".extra-buy-signal-tags" not in html
    assert ".extra-buy-decision-panel" in html
    assert ".extra-buy-buy-signals" in html
    assert ".extra-buy-summary-grid" in html
    assert ".extra-buy-preview-grid" in html
    assert "const extraBuyAmountModeBtns = document.querySelectorAll('[data-extra-buy-size]');" not in html
    assert "extraBuyAmountModeBtns.forEach" not in html
    assert ".extra-buy-range-track" not in html
    assert ".extra-buy-range-rail" not in html
    assert "function updateExtraBuyRangeRail(range, recommendedAmount)" not in html
    assert "updateExtraBuyRangeRail(recommendedRange, recommendedAmount);" not in html
    assert "max-width: 1180px;" not in html
    assert '"why why"' not in html
    assert 'grid-template-areas:\n                "hero controls"\n                "impact impact"\n                "cta cta"\n                "advanced advanced";' not in html
    assert 'grid-template-areas:\n                "hero"\n                "controls"\n                "impact"\n                "decision"\n                "signals"\n                "cta"\n                "footnote";' in html
    assert ".extra-buy-hero {\n            grid-area: hero;" in html
    assert ".extra-buy-signals {" not in html
    assert ".extra-buy-controls {\n            grid-area: controls;" in html
    assert ".extra-buy-section {\n            grid-area: impact;" in html
    assert ".extra-buy-buy-signals {\n            grid-area: signals;" in html
    assert ".extra-buy-cta-btn {\n            grid-area: cta;" in html
    assert ".extra-buy-advanced-panel" not in html
    assert ".extra-buy-decision-panel {\n            grid-area: decision;" in html
    assert "max-width: min(92vw, 840px);" in html
    assert "max-width: min(96vw, 1500px);" not in html
    assert "grid-template-columns: 1fr;" in html
    assert "gap: 0.52rem;\n            padding: 0.72rem 0.8rem 0.78rem;" in html
    assert '"why"' not in html
    assert "grid-template-columns: 1fr;\n                grid-template-areas:\n                    \"hero\"\n                    \"controls\"\n                    \"signals\"\n                    \"impact\"\n                    \"cta\"\n                    \"advanced\";" not in html
    assert "grid-template-columns: 1fr;\n                grid-template-areas:\n                    \"hero\"\n                    \"controls\"\n                    \"impact\"\n                    \"decision\"\n                    \"signals\"\n                    \"cta\"\n                    \"footnote\";" in html
    assert ".extra-buy-market-copy" not in html
    assert ".extra-buy-suggestion-note" not in html
    assert ".extra-buy-preview-grid {\n                grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);" in html
    assert ".extra-buy-preview-divider {" in html
    assert ".extra-buy-advanced-title" not in html
    assert "max-width: 700px;" not in html
    assert "max-width: 800px;" not in html
    assert "max-width: 1120px;" not in html
    assert "font-size: clamp(2.2rem, 3.4vw, 2.8rem);" not in html
    assert "width: 72px;\n            height: 72px;" not in html
    assert "font-size: clamp(2.45rem, 5.2vw, 4.35rem);" not in html
    assert "font-size: 2.45rem;" not in html
    assert "width: 90px;\n            height: 90px;" not in html
    assert "width: 60px;\n            height: 60px;" not in html
    assert "width: 48px;\n            height: 48px;" in html
    preview_icon_rule = html[
        html.index(".extra-buy-preview-icon {")
        : html.index("}", html.index(".extra-buy-preview-icon {"))
    ]
    assert "width: 48px;" not in preview_icon_rule
    assert "height: 48px;" not in preview_icon_rule
    assert "width: 34px;\n            height: 34px;" in html
    assert "min-height: 218px;" not in html
    assert "min-height: 270px;" not in html
    assert "gap: 0.52rem;\n            padding: 0.72rem 0.8rem 0.78rem;" in html
    assert ".extra-buy-modal-content .modal-header {\n            align-items: flex-start;\n            border-color: var(--dashboard-border);\n            padding: 0.84rem 1rem 0.78rem;" in html
    assert "min-height: 72px;" not in html[
        html.index(".extra-buy-cta-btn {") :
        html.index("}", html.index(".extra-buy-cta-btn {"))
    ]
    assert "min-height: 46px;" in html[
        html.index(".extra-buy-cta-btn {") :
        html.index("}", html.index(".extra-buy-cta-btn {"))
    ]
    assert "min-height: 112px;" not in html
    assert "min-height: 138px;" not in html
    assert "@media (min-width: 768px) and (max-height: 760px)" in html
    assert "min-height: 178px;" not in html
    assert "min-height: 88px;" not in html
    assert ".extra-buy-decision-panel {\n                gap: 0.55rem;\n                padding: 0.62rem 0.72rem;" in html
    assert ".extra-buy-summary-grid {\n            display: grid;" in html
    assert ".extra-buy-signal-tags" not in html
    assert "grid-template-areas:\n                \"icon title\"\n                \"icon value\"\n                \"icon status\";" in html
    assert ".extra-buy-section {\n            grid-area: impact;" in html
    assert ".extra-buy-control-card .form-text:not(#addPositionPriceMeta) {\n                display: none;" in html
    assert ".extra-buy-section-subtitle {\n                display: none;" in html
    assert ".extra-buy-manual-note {\n                display: none;" in html
    assert ".extra-buy-price-strip {\n                display: flex;" in html
    assert "flex-wrap: wrap;" in html
    assert "#addPositionPriceMeta" in html
    assert ".extra-buy-status {\n                display: none;" in html
    assert ".extra-buy-modal-content .modal-header {\n                padding: 0.76rem 0.9rem;" in html
    assert ".extra-buy-layout {\n                grid-template-columns: 1fr;\n                grid-template-areas:" in html
    assert "gap: 0.42rem;\n                padding: 0.42rem;" in html
    assert ".extra-buy-reason-card {\n                min-height: 72px;" not in html
    assert "font-size: 1.28rem;\n                margin: 0.18rem 0 0.08rem;" not in html
    assert "const useCents = Math.abs(num) < 100 && Math.abs(num % 1) > 0.005;" in html


def test_extra_buy_allowed_path_renders_four_buy_signal_cards_from_guidance_only():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]

    assert 'id="addPositionReasonFearTitle"' not in modal_markup
    assert 'id="addPositionMarketFear"' not in modal_markup
    assert "Fear and Greed data will appear here when available." not in html
    assert "Fear &amp; Greed" not in modal_markup
    assert "function buildAddPositionSummaryCards(guidance)" in html
    assert "function renderAddPositionBuySignals(payload)" in html
    assert "function hideAddPositionBuySignals()" in html
    assert "function buildAddPositionMarketCards(guidance, payload)" not in html
    assert "renderExtraBuyCards(\n                'addPositionMarketSnapshotGrid'" not in html
    assert "extra-buy-market-snapshot" not in html
    assert "type === 'market'" not in html
    assert "function formatExtraBuyCardCopy(value, maxLength = 118)" in html
    assert "return formatExtraBuyCardCopy(cleanedReason, 180)" in html
    assert "copy: guidance.call_reason," not in html
    assert "title: priceVsAvg !== null && priceVsAvg <= 0 ? 'Below Avg Cost' : 'Above Avg Cost'," in html
    assert "title: 'AHR999'," in html
    assert "title: 'Fear & Greed'," in html
    assert "title: 'Bottoming Signals'," in html
    assert "renderAddPositionBuySignals(payload);" in html


def test_extra_buy_advice_does_not_overwrite_user_entered_amount():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "function syncAddPositionAmountToGuidance(recommendedAmount)" not in html
    assert "syncAddPositionAmountToGuidance(recommendedAmount);" not in html
    assert "amountInput.value = recommendedAmount.toFixed(2);" not in html
    assert "addAmountInput.value = Number(decision.suggested_amount_usd).toFixed(2);" not in html
    assert "setExtraBuyText('addPositionRecommendedAmount', formatExtraBuyUsd(recommendedAmount));" not in html
    assert "setExtraBuyText('addPositionBestAmount', formatExtraBuyUsdCompact(recommendedAmount));" not in html
    assert "addPositionBestAmount" not in html
    assert "const enteredAmount = toExtraBuyFiniteNumber(document.getElementById('addPositionUsdcInput')?.value);" in html
    assert "enteredAmount !== null &&\n                currentPrice !== null" in html
    assert "? enteredAmount / currentPrice" in html
    assert "const amount = Number(document.getElementById('addPositionUsdcInput')?.value);" in html
    assert "Confirm ${formatExtraBuyUsdcCompact(amount)} USDC buy" in html


def test_extra_buy_modal_keeps_recommendation_amounts_out_of_user_input_flow():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]

    assert "Strong Buy Opportunity" not in modal_markup
    assert "Strategy signals available" in modal_markup
    assert "Suggested Range" not in modal_markup
    assert "SUGGESTED RANGE" not in modal_markup
    assert 'id="addPositionRecommendedRange"' not in modal_markup
    assert 'id="addPositionRecommendedCaption"' not in modal_markup
    assert 'id="addPositionAmountStatus"' not in modal_markup
    assert 'id="addPositionAmountAlignment"' not in modal_markup
    assert 'extra-buy-input-state' not in modal_markup
    assert '<span class="extra-buy-impact-label">Estimated BTC</span>' in modal_markup
    assert '<span class="extra-buy-estimate-label">Estimated BTC <i' not in modal_markup
    assert 'data-add-amount="10"' not in modal_markup
    assert 'data-add-amount="25"' not in modal_markup
    assert 'data-add-amount="50"' not in modal_markup
    assert 'data-add-amount="100"' not in modal_markup
    assert "Small" not in modal_markup
    assert "Regular" not in modal_markup
    assert "Large" not in modal_markup
    assert "Custom" not in modal_markup
    assert 'data-extra-buy-size' not in modal_markup

    assert "const recommendedRange = getAddPositionRecommendedRange(guidance);" not in html
    assert "function getAddPositionRecommendedRange(guidance)" not in html
    assert "setExtraBuyText('addPositionRecommendedRange', formatExtraBuyUsdRange(recommendedRange));" not in html
    assert "setExtraBuyText('addPositionRecommendedCaption', formatExtraBuyRecommendationCaption(recommendedAmount));" not in html
    assert "function updateAddPositionInputState()" in html
    assert "function formatExtraBuyAmountAlignment(amount, range)" not in html
    assert "formatExtraBuyAmountAlignment(amount, addPositionLastRecommendedRange)" not in html
    assert "Below suggested range" not in html
    assert "addPositionLastRecommendedRange = recommendedRange;" not in html
    assert "addPositionLastRecommendedAmount = recommendedAmount;" not in html
    assert "function scrollAddPositionModalToTop()" in html
    assert "scrollAddPositionModalToTop();" in html
    assert "addPositionActionMode === 'confirm'" in html
    assert "'Strategy check first. No purchase yet.'" in html
    assert "setExtraBuyText('addPositionConfirmSubtext', 'Records this manual buy now.');" in html
    assert "addPositionQuickAmountBtns.forEach" not in html
    assert "const extraBuyAmountModeBtns = document.querySelectorAll('[data-extra-buy-size]');" not in html
    assert "extraBuyAmountModeBtns.forEach" not in html
    assert "function updateAddPositionImpactFromInputs()" in html
    assert "const proposedBtc = amount / price;" in html
    assert "const afterCost = (totalInvestedUsd + amount) / afterBtc;" in html
    assert "toExtraBuyFiniteNumber(cost.suggested_avg_cost_after_buy_usd)" not in html
    assert "toExtraBuyFiniteNumber(cost.suggested_avg_cost_delta_usd)" not in html
    assert ".extra-buy-control-card .form-control[type=\"number\"]" in html
    assert "-moz-appearance: textfield;" in html
    assert "appearance: textfield;" in html
    assert ".extra-buy-control-card .form-control[type=\"number\"]::-webkit-inner-spin-button" in html


def test_extra_buy_amount_edits_recalculate_impact_and_invalidate_confirmation():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "function clearAddPositionImpact()" in html
    assert "function updateAddPositionImpactFromInputs()" in html
    assert "function invalidateAddPositionConfirmState()" in html
    assert "let addPositionConfirmToken = null;" in html
    assert "let addPositionLastImpactBasis = null;" in html
    assert "setExtraBuyText('addPositionOpportunityTitle', 'Strategy signals available');" in html
    assert "setExtraBuyText('addPositionImpactCurrentCost', 'Enter an amount');" in html
    assert "setExtraBuyText('addPositionImpactAfterCost', '--');" in html
    assert "setExtraBuyText('addPositionImpactDelta', '--');" in html
    assert "function setAddPositionImpactUnavailable()" in html
    assert "setExtraBuyText('addPositionImpactCurrentCost', 'Position data unavailable');" in html
    assert "setExtraBuyText('addPositionImpactAfterCost', 'Cannot preview yet');" in html
    assert "setExtraBuyText('addPositionImpactDelta', 'No cost basis');" in html

    start = html.index("if (amountInput) {")
    end = html.index("if (priceInput) {")
    amount_input_block = html[start:end]

    assert "clearAddPositionImpact();" not in amount_input_block
    assert "updateAddPositionImpactFromInputs();" in amount_input_block
    assert "invalidateAddPositionConfirmState();" in amount_input_block


def test_extra_buy_modal_preloads_recommendation_range_before_amount_entry():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "async function loadAddPositionRecommendation()" in html
    assert "await runAddPositionRecommendationOnly(price);" in html
    assert "function buildAddPositionAdviceRequestBody(price, amount = null)" in html
    assert "if (amount !== null) {\n                body.amount_usdc = amount;\n            }" in html
    assert "const payload = await fetchAddPositionAdvice(price);" in html
    assert "const payload = await fetchAddPositionAdvice(price, amount);" in html
    assert "body: JSON.stringify(buildAddPositionAdviceRequestBody(price, amount))" in html
    assert "setAddPositionActionMode('advice');\n                    await fetchRealtimePriceForAddPosition();\n                    await loadAddPositionRecommendation();" in html
    assert "Enter amount to preview" in html


def test_extra_buy_strategy_check_does_not_show_success_toasts_that_cover_the_modal():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    start = html.index("async function runAddPositionAdvice()")
    end = html.index("async function confirmAddPositionBuy()")
    strategy_check_block = html[start:end]

    assert "notyf.success('Strategy check ready" not in strategy_check_block
    assert "notyf.success(\"Strategy check ready" not in strategy_check_block
    assert "setAddPositionActionMode('confirm');" in strategy_check_block
    assert "setAddPositionHardBlocked(true);" in strategy_check_block
    assert "notyf.error('Extra buy strategy check failed')" in strategy_check_block


def test_extra_buy_confirm_posts_strategy_check_token_only_after_preflight():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    advice_start = html.index("async function runAddPositionAdvice()")
    advice_end = html.index("async function confirmAddPositionBuy()")
    advice_block = html[advice_start:advice_end]
    assert "addPositionConfirmToken = payload?.confirm_token || null;" in advice_block
    assert "setAddPositionActionMode('confirm');" in advice_block

    confirm_start = html.index("async function confirmAddPositionBuy()")
    confirm_end = html.index("function startAddPositionPricePolling()")
    confirm_block = html[confirm_start:confirm_end]
    assert "if (!addPositionConfirmToken)" in confirm_block
    assert "confirm_token: addPositionConfirmToken" in confirm_block
