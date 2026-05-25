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


def test_shared_design_override_is_not_loaded():
    for template_name in TEMPLATE_NAMES:
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        assert 'href="/static/app.css"' not in html


def test_shared_design_override_file_is_removed():
    assert not (STATIC_DIR / "app.css").exists()


def test_login_uses_original_gradient_card_style():
    html = (TEMPLATE_DIR / "login.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" in html
    assert "box-shadow:" in html


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
