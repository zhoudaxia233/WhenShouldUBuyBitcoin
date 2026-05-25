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
    assert 'href="/" class="btn dashboard-nav-btn{% if active_page == \'dashboard\' %} active{% endif %}"' in header
    assert 'id="settingsDropdown"' in header
    assert 'class="dropdown-item" href="/strategy"' in header
    assert 'class="dropdown-item" href="/settings/binance"' in header
    assert 'href="/settings/binance#email-settings"' not in header
    assert 'href="/stats" class="btn dashboard-nav-btn{% if active_page == \'stats\' %} active{% endif %}"' in header
    assert 'href="/admin/data-sources" class="btn dashboard-nav-btn nav-accent admin-diagnostics-link{% if active_page == \'admin\' %} active{% endif %}"' in header
    assert 'href="/analysis/" class="btn dashboard-nav-btn"' in header
    for label in ["Dashboard", "Settings", "Diagnostics", "Analytics", "WSUB"]:
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
        assert 'class="version-badge"' in html, template_name


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


def test_mobile_navigation_wraps_instead_of_horizontal_clipping():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")
    dashboard = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")

    mobile_css = css[css.index("@media (max-width: 768px)") :]
    assert "overflow-x: visible;" in mobile_css
    assert "flex-wrap: wrap !important;" in mobile_css
    assert "flex-wrap: nowrap !important;" not in dashboard[dashboard.find("@media (max-width: 768px)") :]


def test_diagnostics_nav_accent_is_distinct_from_active_state():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    assert ".dashboard-nav-btn.active,\n.dashboard-nav-btn.nav-accent" not in css
    assert ".dashboard-nav-btn.nav-accent:not(.active)" in css
    assert ".dashboard-nav-btn.nav-accent.active" in css


def test_mobile_version_badge_does_not_overlay_content():
    css = STATIC_CSS_PATH.read_text(encoding="utf-8")

    mobile_css = css[css.index("@media (max-width: 768px)") :]
    assert ".version-badge" in mobile_css
    assert "position: static;" in mobile_css


def test_stats_uses_satsflow_badge_and_reserve_palette():
    html = (TEMPLATE_DIR / "stats.html").read_text(encoding="utf-8")

    assert 'class="badge stats-balance-badge fs-6"' in html
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
