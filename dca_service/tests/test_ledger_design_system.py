"""The signed-in app uses one quiet "ledger" design system.

The old look painted almost everything Bitcoin orange on a cream background,
and relied on an Inter font that was never loaded, so each device fell back to
a different system font. The redesign keeps orange for Bitcoin itself, uses
ink for actions, and ships its own fonts so every device renders the same.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "dca_service"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
HEADER = (TEMPLATES / "_shared_header.html").read_text(encoding="utf-8")


def _block(selector: str) -> str:
    """First rule whose selector list starts with `selector`."""
    start = re.search(r"(?m)^" + re.escape(selector) + r"[ ,]", CSS).start()
    return CSS[start : CSS.index("}", start)]


def test_fonts_are_self_hosted_and_licensed():
    faces = re.findall(r"@font-face\s*\{[^}]*\}", CSS)
    families = {re.search(r'font-family:\s*"([^"]+)"', face).group(1) for face in faces}
    assert {"IBM Plex Sans", "IBM Plex Mono"} <= families
    for url in re.findall(r'url\("?(fonts/[^")]+)"?\)', CSS):
        assert (STATIC / url).is_file(), url
    assert (STATIC / "fonts" / "OFL.txt").is_file()


def test_body_text_uses_plex_and_numbers_use_plex_mono():
    root = _block(":root")
    assert '--font-sans: "IBM Plex Sans"' in root
    assert '--font-mono: "IBM Plex Mono"' in root
    assert "--bs-body-font-family: var(--font-sans);" in root
    assert "Inter," not in CSS


def test_palette_is_neutral_with_ink_actions_and_orange_only_for_bitcoin():
    light = _block(":root")
    dark = _block('html[data-bs-theme="dark"]')
    assert "--dashboard-bg: #fafaf9;" in light
    assert "--dashboard-accent: #15171b;" in light
    assert "--dashboard-btc: #f7931a;" in light
    for tokens in (light, dark):
        for name in ("--dashboard-on-accent", "--dashboard-faint", "--dashboard-danger-soft", "--dashboard-success-soft"):
            assert f"{name}:" in tokens, name
    assert "#fffaf4" not in CSS
    assert "#ff8a00" not in CSS


def test_templates_do_not_redefine_tokens_or_hardcode_the_old_yellow_and_orange():
    for template in TEMPLATES.glob("*.html"):
        html = template.read_text(encoding="utf-8")
        assert "--dashboard-bg:" not in html, template.name
        for colour in ("#f4bd21", "#ff8a00", "#fffaf4", "rgba(255, 138, 0"):
            assert colour not in html, f"{template.name} still uses {colour}"


def test_desktop_navigation_is_a_grouped_sidebar():
    assert 'class="dashboard-header app-sidebar"' in HEADER
    groups = re.findall(r'<p class="sidebar-group">([^<]+)</p>', HEADER)
    assert groups == ["Portfolio", "Automation", "Elsewhere"]
    links = re.findall(r'<a href="([^"]+)" class="sidebar-link', HEADER)
    assert links == ["/", "/stats", "/strategy", "/settings/binance", "/admin/data-sources", "/analysis/"]
    for page in ("dashboard", "stats", "strategy", "settings", "admin"):
        assert f"{{% if active_page == '{page}' %}} active{{% endif %}}" in HEADER, page
    assert "{% if user and user.is_admin %}" in HEADER


def test_sidebar_is_fixed_on_desktop_and_hidden_on_phones():
    sidebar = _block(".app-sidebar")
    assert "position: fixed;" in sidebar
    assert "width: var(--sidebar-width);" in sidebar
    phone = CSS[CSS.index("@media (max-width: 991.98px)") :]
    hidden = phone[phone.index(".app-sidebar {") :]
    assert "display: none;" in hidden[: hidden.index("}")]
    assert ".mobile-bottom-nav" in CSS


def test_home_loads_the_ladder_and_renders_it_on_every_preview():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "<script src=\"{{ asset_url('strategy_ladder.js') }}\"></script>" in html
    assert html.index("strategy_ladder.js") < html.index("function renderStrategyLadder(decision, strategy)")
    update = html[html.index("function updatePreviewUI(decision)") :]
    update = update[: update.index("async function loadPreview()")]
    assert "window.renderStrategyLadder(decision);" in update
    assert "window.renderBudgetSpent(decision);" in update
    assert 'id="strategyLadder"' in html
    assert 'id="goalRingFill"' in html
