from pathlib import Path


def test_dashboard_add_position_modal_and_safe_polling_are_present():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="openAddPositionBtn"' in html
    assert 'data-bs-target="#addPositionModal"' in html
    assert "Extra Buy" in html
    assert "Extra BTC Buy" in html
    assert "This action won't change your DCA settings." in html
    assert "Check Strategy" not in html
    assert "Confirm Extra Buy" not in html
    assert "Buy ${formatExtraBuyUsdcCompact(amount)} USDC" in html
    assert "Confirm buy ${formatExtraBuyUsdcCompact(amount)} USDC" in html
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


def test_extra_buy_realtime_price_is_prominent_on_desktop_and_mobile():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert "metaEl.textContent = Number.isFinite(price) && price > 0 ? `BTC Price: ${formatExtraBuyUsd(price)}` : 'BTC Price: --';" in html
    assert ".extra-buy-price-card {\n            display: flex;" in html
    assert "background: color-mix(in srgb, var(--dashboard-card-bg-solid) 90%, var(--dashboard-accent) 10%);" in html
    assert "border: 1px solid color-mix(in srgb, var(--dashboard-accent) 44%, var(--dashboard-border));" in html
    assert ".extra-buy-price-card .form-text {\n            color: var(--dashboard-text);" in html
    assert "font-size: 0.95rem;" in html
    assert "font-weight: 820;" in html

    mobile_css = html[html.index("@media (max-width: 768px)"):]
    assert ".extra-buy-price-card {\n                display: flex;" in mobile_css
    assert "padding: 0.32rem 0.42rem;" in mobile_css
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


def test_extra_buy_uses_backend_current_valuation_instead_of_dashboard_override():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    request_body = html[
        html.index("function buildAddPositionAdviceRequestBody")
        : html.index("async function fetchAddPositionAdvice")
    ]
    summary_cards = html[
        html.index("function buildAddPositionSummaryCards")
        : html.index("function setAddPositionAdvancedCollapsed")
    ]
    realtime_update = html[
        html.index("function updateDashboardRealtimePrice")
        : html.index("function updateAddPositionRealtimePrice")
    ]

    assert "dashboard_ahr999" not in request_body
    assert "window.__latestDrawdownDecision?.ahr999_value" not in request_body
    assert "toExtraBuyFiniteNumber(guidance.dashboard_ahr999)" not in summary_cards
    assert "toExtraBuyFiniteNumber(valuation.ahr999)" in summary_cards
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
    assert "Strategy check says no extra buy right now." in html
    assert "setAddPositionHardBlocked(true);" in html
    assert "setAddPositionActionMode('advice');" in html


def test_extra_buy_modal_uses_reference_style_compact_assessment_and_order():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]

    assert 'extra-buy-modal-content' in modal_markup
    assert 'class="modal-dialog modal-lg modal-dialog-scrollable extra-buy-modal-dialog"' in modal_markup
    assert 'id="addPositionRecommendedAmount"' not in modal_markup
    assert 'id="addPositionRecommendedCaption"' not in modal_markup
    assert 'id="addPositionSummaryGrid"' in modal_markup
    assert 'id="addPositionMarketSnapshotGrid"' not in modal_markup
    assert 'id="addPositionImpactPanel"' in modal_markup
    assert 'id="addPositionAdvancedPanel"' in modal_markup
    assert 'id="addPositionAdvancedToggle"' in modal_markup
    assert 'id="addPositionAdviceText"' in modal_markup
    assert '<pre id="addPositionAdviceText"' not in modal_markup
    assert "MARKET ASSESSMENT" not in modal_markup
    assert "Suggested Range" in modal_markup
    assert "SUGGESTED RANGE" not in modal_markup
    assert 'id="addPositionRangeMinLabel"' not in modal_markup
    assert 'id="addPositionRangeMaxLabel"' not in modal_markup
    assert 'id="addPositionRangeMarker"' not in modal_markup
    assert 'id="addPositionBestAmount"' not in modal_markup
    assert "Best Amount" not in modal_markup
    assert "This is a market-based suggestion and is independent of the amount you choose to buy." not in modal_markup
    assert "YOUR ORDER" in modal_markup
    assert "Impact on your position" in modal_markup
    assert "Advanced analysis" in modal_markup
    assert "Why this makes sense" not in modal_markup
    assert "Market snapshot" not in modal_markup

    assert "function renderAddPositionGuidanceSummary(payload)" in html
    assert "function resetAddPositionGuidanceSummary()" in html
    assert "renderAddPositionGuidanceSummary(payload);" in html
    assert "resetAddPositionGuidanceSummary();" in html
    assert ".extra-buy-modal-content" in html
    assert ".extra-buy-recommendation-value" in html
    assert ".extra-buy-range-track" not in html
    assert ".extra-buy-range-rail" not in html
    assert "function updateExtraBuyRangeRail(range, recommendedAmount)" not in html
    assert "updateExtraBuyRangeRail(recommendedRange, recommendedAmount);" not in html
    assert "max-width: 1180px;" in html
    assert '"why why"' not in html
    assert 'grid-template-areas:\n                "hero controls"\n                "signals signals"\n                "impact impact"\n                "cta cta"\n                "advanced advanced";' in html
    assert ".extra-buy-hero {\n            grid-area: hero;" in html
    assert ".extra-buy-signals {\n            grid-area: signals;" in html
    assert ".extra-buy-controls {\n            grid-area: controls;" in html
    assert ".extra-buy-section {\n            grid-area: impact;" in html
    assert ".extra-buy-cta-btn {\n            grid-area: cta;" in html
    assert ".extra-buy-advanced-panel {\n            grid-area: advanced;" in html
    assert "grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);" in html
    assert "gap: 0.75rem;\n            padding: 1rem 1.1rem 1.1rem;" in html
    assert '"why"' not in html
    assert "grid-template-columns: 1fr;\n                grid-template-areas:\n                    \"hero\"\n                    \"controls\"\n                    \"signals\"\n                    \"impact\"\n                    \"cta\"\n                    \"advanced\";" in html
    assert ".extra-buy-market-copy" not in html
    assert ".extra-buy-suggestion-note" not in html
    assert ".extra-buy-impact-grid {\n                grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) minmax(88px, 0.8fr);" in html
    assert ".extra-buy-impact-box {\n                grid-column: auto;\n                border: 0;\n                background: transparent;\n                padding: 0;\n            }" in html
    assert ".extra-buy-impact-arrow {\n                transform: none;" in html
    assert ".extra-buy-advanced-title span span {\n                display: none;" in html
    assert ".extra-buy-advanced-title span {\n                display: none;" not in html
    assert "max-width: 700px;" not in html
    assert "max-width: 800px;" not in html
    assert "max-width: 1120px;" not in html
    assert "font-size: clamp(2.2rem, 3.4vw, 2.8rem);" in html
    assert "width: 72px;\n            height: 72px;" in html
    assert "font-size: clamp(2.45rem, 5.2vw, 4.35rem);" not in html
    assert "font-size: 2.45rem;" not in html
    assert "min-height: 218px;" in html
    assert "min-height: 270px;" not in html
    assert "gap: 0.75rem;\n            padding: 1rem 1.1rem 1.1rem;" in html
    assert "min-height: 112px;" in html
    assert "min-height: 138px;" not in html
    assert "@media (min-width: 768px) and (max-height: 760px)" in html
    assert "min-height: 178px;" in html
    assert "min-height: 88px;" in html
    assert "padding: 0.58rem 0.72rem;" in html
    assert ".extra-buy-summary-grid,\n            .extra-buy-impact-grid {\n                grid-template-columns: 1fr;" not in html
    assert ".extra-buy-summary-grid {" in html
    assert ".extra-buy-summary-grid {\n                grid-template-columns: repeat(2, minmax(0, 1fr));\n                gap: 0.28rem;" in html
    assert ".extra-buy-summary-grid {\n            display: grid;\n            grid-template-columns: repeat(4, minmax(0, 1fr));\n            gap: 0.75rem;" in html
    assert "grid-template-areas:\n                \"icon title\"\n                \"icon value\"\n                \"icon status\";" in html
    assert ".extra-buy-section {\n            grid-area: impact;\n            display: grid;\n            grid-template-columns: minmax(260px, 1fr) minmax(0, 2.4fr);" in html
    assert ".extra-buy-control-card .form-text:not(#addPositionPriceMeta) {\n                display: none;" in html
    assert ".extra-buy-section-subtitle {\n                display: none;" in html
    assert ".extra-buy-manual-note {\n                display: none;" in html
    assert ".extra-buy-price-card {\n                display: flex;" in html
    assert "justify-content: space-between;" in html
    assert "#addPositionPriceMeta" in html
    assert ".extra-buy-status {\n                display: none;" in html
    assert ".extra-buy-modal-content .modal-header {\n                padding: 0.56rem 0.7rem;" in html
    assert ".extra-buy-layout {\n                grid-template-columns: 1fr;\n                grid-template-areas:" in html
    assert "gap: 0.34rem;\n                padding: 0.38rem;" in html
    assert ".extra-buy-reason-card {\n                min-height: 72px;" in html
    assert "font-size: 1.28rem;\n                margin: 0.18rem 0 0.08rem;" in html
    assert "Bottoming Signals" in html
    assert "const useCents = Math.abs(num) < 100 && Math.abs(num % 1) > 0.005;" in html


def test_extra_buy_summary_uses_only_available_guidance_data_not_static_fear_greed_copy():
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
    assert "function buildAddPositionMarketCards(guidance, payload)" not in html
    assert "renderExtraBuyCards(\n                'addPositionMarketSnapshotGrid'" not in html
    assert "extra-buy-market-snapshot" not in html
    assert "type === 'market'" not in html
    assert "function formatExtraBuyCardCopy(value, maxLength = 118)" in html
    assert "copy: formatExtraBuyCardCopy(" in html
    assert "copy: guidance.call_reason," not in html
    assert "fearValue !== null" in html
    assert "summaryCards.push" in html


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
    assert "Confirm buy ${formatExtraBuyUsdcCompact(amount)} USDC" in html


def test_extra_buy_modal_surfaces_suggested_range_and_user_input_state():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    modal_markup = html[
        html.index('<div class="modal fade" id="addPositionModal"')
        : html.index('<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">')
    ]

    assert "Strong Buy Opportunity" in modal_markup
    assert "Suggested Range" in modal_markup
    assert "SUGGESTED RANGE" not in modal_markup
    assert 'id="addPositionRecommendedRange"' in modal_markup
    assert 'id="addPositionRecommendedCaption"' not in modal_markup
    assert 'id="addPositionAmountStatus"' not in modal_markup
    assert 'id="addPositionAmountAlignment"' not in modal_markup
    assert 'extra-buy-input-state' not in modal_markup
    assert '<span class="extra-buy-estimate-label">Estimated BTC</span>' in modal_markup
    assert '<span class="extra-buy-estimate-label">Estimated BTC <i' not in modal_markup
    assert 'data-add-amount="10"' in modal_markup
    assert 'data-add-amount="25"' in modal_markup
    assert 'data-add-amount="50"' in modal_markup
    assert 'data-add-amount="100"' in modal_markup

    assert "const recommendedRange = getAddPositionRecommendedRange(guidance);" in html
    assert "function getAddPositionRecommendedRange(guidance)" in html
    assert "setExtraBuyText('addPositionRecommendedRange', formatExtraBuyUsdRange(recommendedRange));" in html
    assert "setExtraBuyText('addPositionRecommendedCaption', formatExtraBuyRecommendationCaption(recommendedAmount));" not in html
    assert "function updateAddPositionInputState()" in html
    assert "function formatExtraBuyAmountAlignment(amount, range)" not in html
    assert "formatExtraBuyAmountAlignment(amount, addPositionLastRecommendedRange)" not in html
    assert "Below suggested range" not in html
    assert "addPositionLastRecommendedRange = recommendedRange;" in html
    assert "addPositionLastRecommendedAmount = recommendedAmount;" not in html
    assert "function scrollAddPositionModalToTop()" in html
    assert "scrollAddPositionModalToTop();" in html
    assert "addPositionActionMode === 'confirm'" in html
    assert "'Checks strategy first. No purchase yet.'" in html
    assert "setExtraBuyText('addPositionConfirmSubtext', 'Confirm to execute this buy now.');" in html
    assert "addPositionQuickAmountBtns.forEach" in html
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
    assert "setExtraBuyText('addPositionOpportunityTitle', 'Strategy Check Ready');" in html
    assert "setExtraBuyText('addPositionImpactCurrentCost', '$--');" in html
    assert "setExtraBuyText('addPositionImpactAfterCost', '$--');" in html
    assert "setExtraBuyText('addPositionImpactDelta', '$--');" in html

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
    assert "Enter amount to continue" in html


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
