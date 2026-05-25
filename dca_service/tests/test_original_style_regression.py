import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "src" / "dca_service" / "templates"
STATIC_DIR = PROJECT_ROOT / "src" / "dca_service" / "static"

TEMPLATE_NAMES = [
    "admin_data_sources.html",
    "binance_settings.html",
    "index.html",
    "login.html",
    "stats.html",
    "strategy.html",
]


def test_shared_satsflow_design_system_is_loaded_by_all_templates():
    for template_name in TEMPLATE_NAMES:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'href="/static/app.css"' in html, template_name


def test_shared_satsflow_design_system_file_exists():
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert "--dashboard-accent: #ff8a00;" in css
    assert "--dashboard-accent-strong: #f97316;" in css
    assert ".app-shell" in css
    assert ".brand-lockup" in css
    assert ".dashboard-panel" in css
    assert ".login-shell" in css


def test_login_uses_satsflow_brand_style_not_legacy_purple_gradient():
    html = (TEMPLATE_DIR / "login.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" not in html
    assert 'class="login-shell"' in html
    assert 'class="brand-mark"' in html
    assert 'class="login-card dashboard-panel"' in html


def test_dashboard_preview_does_not_call_late_renderer_before_defined():
    html = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    early_preview_script = html[
        html.index("const ahrValue = toFiniteNumber(preview.ahr999_value);") :
        html.index("<!-- Set Cold Wallet Balance Modal -->")
    ]
    assert not re.search(
        r"(?<!\.)\brenderBottomingSignalPreview\(preview\.bottoming_signal \|\| null\);",
        early_preview_script,
    )
    assert "typeof window.renderBottomingSignalPreview === 'function'" in early_preview_script
    assert "window.__latestBottomingSignal = preview.bottoming_signal || null;" in early_preview_script


def test_dashboard_cache_hydration_does_not_use_local_timezone_before_definition():
    html = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    early_preview_script = html[
        html.index("// Hydrate wallet and DCA preview from cache") :
        html.index("<!-- Set Cold Wallet Balance Modal -->")
    ]

    assert "mode === 'LOCAL' ? LOCAL_TIMEZONE : 'UTC'" not in early_preview_script
    assert "mode === 'LOCAL' ? window.LOCAL_TIMEZONE : 'UTC'" in early_preview_script
