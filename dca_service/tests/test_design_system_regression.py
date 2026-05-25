import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "src" / "dca_service" / "templates"
STATIC_DIR = PROJECT_ROOT / "src" / "dca_service" / "static"

APP_TEMPLATES = [
    "admin_data_sources.html",
    "binance_settings.html",
    "index.html",
    "login.html",
    "stats.html",
    "strategy.html",
]


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _read_app_css() -> str:
    return (STATIC_DIR / "app.css").read_text(encoding="utf-8")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _css_token_values(css: str) -> dict[str, list[str]]:
    tokens: dict[str, list[str]] = {}
    for name, value in re.findall(r"(--app-[\w-]+)\s*:\s*([^;]+);", _strip_css_comments(css)):
        tokens.setdefault(name, []).append(value.strip())
    return tokens


def test_shared_design_css_is_loaded_after_template_styles():
    for template_name in APP_TEMPLATES:
        html = _read_template(template_name)
        assert 'href="/static/app.css"' in html
        assert html.rfind('href="/static/app.css"') > html.rfind("</style>")


def test_shared_design_tokens_match_design_md():
    css = _read_app_css()
    tokens = _css_token_values(css)
    expected_tokens = {
        "--app-canvas": "#fff",
        "--app-primary": "#000",
        "--app-hairline": "#e5e5e5",
        "--app-radius-card": "12px",
        "--app-radius-pill": "9999px",
        "--app-breakpoint-mobile": "576px",
        "--app-page-gutter-mobile": "24px",
        "--app-heading-mobile": "30px",
        "--app-header-gap-mobile": "12px",
        "--app-badge-gap": "6px",
        "--app-touch-target-mobile": "40px",
    }
    for name, value in expected_tokens.items():
        assert tokens.get(name) == [value]
    assert "SF Pro Rounded" in css


def test_shared_css_has_no_decorative_gradients_or_shadows():
    css = _strip_css_comments(_read_app_css())
    assert "gradient(" not in css
    box_shadow_values = [
        value.strip()
        for value in re.findall(r"box-shadow\s*:\s*([^;]+);", css)
    ]
    assert box_shadow_values
    assert all(value == "none !important" for value in box_shadow_values)


def test_templates_do_not_define_decorative_gradients_or_shadows():
    for template_name in APP_TEMPLATES:
        html = _read_template(template_name)
        assert "linear-gradient" not in html
        assert "box-shadow" not in html
        assert "shadow-sm" not in html


def test_templates_do_not_keep_local_dark_palette_overrides():
    for template_name in APP_TEMPLATES:
        html = _read_template(template_name)
        assert 'html[data-bs-theme="dark"]' not in html
        assert 'html[data-theme="dark"]' not in html


def test_primary_actions_are_black_pills_in_shared_css():
    css = _read_app_css()
    assert re.search(
        r"\.btn,\s*\.btn-login\s*\{[\s\S]*?border-radius: var\(--app-radius-pill\)",
        css,
    )
    assert ".btn-primary" in css
    assert "background: var(--app-primary)" in css
    assert "border-color: var(--app-primary)" in css


def test_mobile_card_headers_stack_badge_groups():
    css = _read_app_css()
    assert "--app-breakpoint-mobile: 576px;" in css
    assert "@media (max-width: 576px)" in css
    assert ".card-header.d-flex" in css
    assert "flex-direction: column" in css
    assert "align-items: flex-start !important" in css
    assert ".card-header .badge" in css
    assert "white-space: normal" in css
    assert "width: min(100% - var(--app-page-gutter-mobile), 1120px);" in css
    assert "font-size: var(--app-heading-mobile);" in css
    assert "gap: var(--app-header-gap-mobile);" in css
    assert "gap: var(--app-badge-gap);" in css
    assert "min-height: var(--app-touch-target-mobile);" in css


def test_bootstrap_semantic_text_utilities_are_neutralized():
    css = _read_app_css()
    assert ".text-primary" in css
    assert ".text-success" in css
    assert ".text-danger" in css
    assert "color: var(--app-ink) !important;" in css


def test_alert_surfaces_are_neutral_not_blue_or_yellow():
    css = _read_app_css()
    assert ".alert-info" in css
    assert ".alert-warning" in css
    assert ".alert-danger" in css
    assert "background: var(--app-surface-soft) !important;" in css
    assert "border-color: var(--app-hairline) !important;" in css


def test_dashboard_preview_does_not_call_late_renderer_before_defined():
    html = _read_template("index.html")
    early_preview_script = html[
        html.index("const ahrValue = toFiniteNumber(preview.ahr999_value);") :
        html.index("<!-- Set Cold Wallet Balance Modal -->")
    ]
    assert "renderBottomingSignalPreview(preview.bottoming_signal || null);" not in early_preview_script
    assert "typeof window.renderBottomingSignalPreview === 'function'" in early_preview_script
    assert "window.__latestBottomingSignal = preview.bottoming_signal || null;" in early_preview_script
