from pathlib import Path


def test_strategy_template_has_summary_api_settings_section():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "strategy.html"
    html = template_path.read_text(encoding="utf-8")

    assert "OpenAI Summary API Settings" in html
    assert 'id="summaryApiForm"' in html
    assert 'id="summary_api_enabled"' in html
    assert 'id="summary_api_base_url"' in html
    assert 'id="summary_api_model"' in html
    assert 'id="summary_api_key"' in html
    assert 'id="testSummaryApiBtn"' in html
    assert "loadSummaryApiSettings()" in html
    assert "fetch('/api/summary-api/settings'" in html
    assert "fetch('/api/summary-api/settings/test'" in html
