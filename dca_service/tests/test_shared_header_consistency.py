"""The shared header must look the same on every signed-in page.

Each page used to restyle parts of the header and the page width in its own
<style> block. On Strategy the 1000px page width squeezed the account chip
until the email read "y...". The header's look now lives only in app.css.
"""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"
HEADER_SELECTOR = re.compile(
    r"\.container\b|\.app-shell|\.dashboard-header|\.shared-header|\.brand-|\.dashboard-nav|"
    r"\.nav-actions|\.header-utility|\.user-chip|\.user-avatar|\.user-email|\.logout-|"
    r"\.theme-toggle|\.dashboard-refresh-btn|\.mobile-bottom"
)
PAGES_WITH_SHARED_HEADER = [
    path for path in sorted(TEMPLATES.glob("*.html"))
    if '{% include "_shared_header.html" %}' in path.read_text(encoding="utf-8")
]


def _inline_rules(html):
    for block in re.findall(r"<style[^>]*>(.*?)</style>", html, re.S):
        for selector, _body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
            yield " ".join(selector.split())


def test_every_signed_in_page_uses_the_shared_header():
    names = {path.name for path in PAGES_WITH_SHARED_HEADER}
    assert {"index.html", "stats.html", "strategy.html", "binance_settings.html", "admin_data_sources.html"} <= names


def test_pages_do_not_restyle_the_header_or_page_width():
    for path in PAGES_WITH_SHARED_HEADER:
        html = path.read_text(encoding="utf-8")
        overrides = [sel for sel in _inline_rules(html) if HEADER_SELECTOR.search(sel)]
        assert not overrides, f"{path.name} restyles the shared header: {overrides}"


def test_navigation_only_lists_pages():
    header = (TEMPLATES / "_shared_header.html").read_text(encoding="utf-8")
    assert 'href="/#buys"' not in header
    assert ">Buys<" not in header
