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
    assert "actionText = `Will buy $${suggestedAmount.toFixed(2)}`;" in html
    assert "actionText = 'Will wait';" in html
    assert "? `Will buy $${decision.suggested_amount_usd.toFixed(2)}`" in html
    assert ": 'Will wait';" in html


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
