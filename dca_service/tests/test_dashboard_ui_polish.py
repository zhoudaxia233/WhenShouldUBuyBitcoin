from pathlib import Path


TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "dca_service"
    / "templates"
    / "index.html"
)


def _dashboard_html() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_dashboard_uses_orange_bitcoin_visual_system():
    html = _dashboard_html()

    assert "--dashboard-accent: #ff8a00;" in html
    assert "--dashboard-accent-strong: #f97316;" in html
    assert 'class="brand-mark"' in html
    assert 'class="brand-title">{{ project_name }}</span>' in html
    assert 'class="btn dashboard-nav-btn active"' in html


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
    assert "<h1>{{ project_name }}</h1>" in login
    assert '"project_name": settings.PROJECT_NAME' in auth_api


def test_dashboard_wallet_uses_metric_cards_and_progress_ring():
    html = _dashboard_html()

    assert 'class="wallet-card-grid"' in html
    assert 'class="metric-card metric-card-primary"' in html
    assert 'class="metric-card progress-metric-card"' in html
    assert 'id="progressRing"' in html
    assert "--progress-value" in html
    assert "progressRingEl.style.setProperty('--progress-value'" in html


def test_dashboard_dark_mode_has_matching_tokens():
    html = _dashboard_html()

    assert 'html[data-bs-theme="dark"] {' in html
    assert "--dashboard-bg: #12100d;" in html
    assert "--dashboard-card-bg: #181512;" in html
    assert "--dashboard-border: #352a1f;" in html
    assert "--dashboard-accent-soft: rgba(255, 138, 0, 0.16);" in html


def test_dashboard_mobile_layout_is_explicitly_scoped():
    html = _dashboard_html()

    assert "@media (max-width: 768px)" in html
    assert ".wallet-card-grid" in html
    assert ".strategy-metric-grid" in html
    assert ".dashboard-nav" in html
