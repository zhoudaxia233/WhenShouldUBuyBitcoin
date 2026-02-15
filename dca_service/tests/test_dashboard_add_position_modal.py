from pathlib import Path


def test_dashboard_add_position_modal_and_safe_polling_are_present():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "index.html"
    html = template_path.read_text(encoding="utf-8")

    assert 'id="openAddPositionBtn"' in html
    assert 'data-bs-target="#addPositionModal"' in html
    assert "Add Position" in html
    assert 'id="addPositionModal"' in html
    assert 'id="addPositionUsdcInput"' in html
    assert 'id="addPositionPriceInput"' in html
    assert 'id="addPositionPriceInput" type="number" min="1" step="0.01" class="form-control" required readonly' in html
    assert "const ADD_POSITION_PRICE_POLL_INTERVAL_MS = 3000;" in html
    assert "fetch('/api/stats/realtime-price?symbol=BTCUSDC')" in html
    assert "fetch('/api/stats/add-position/advice'" in html
    assert "Buy (Confirm)" in html
    assert "fetch('/api/stats/add-position/confirm'" in html
