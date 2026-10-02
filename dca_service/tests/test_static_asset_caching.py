"""Browsers must never pair a new page with an old cached stylesheet or script.

v0.1.64 moved the home page's styles into /static/app.css. The URL did not
change, and the file was served without Cache-Control, so browsers kept their
old copy and rendered the new page unstyled.
"""
import re
from pathlib import Path

from dca_service.main import app
from dca_service.static_files import asset_url

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"


def test_asset_url_changes_with_the_file_contents(tmp_path, monkeypatch):
    import dca_service.static_files as static_files

    (tmp_path / "app.css").write_text("a{}", encoding="utf-8")
    monkeypatch.setattr(static_files, "STATIC_DIR", tmp_path)
    static_files.asset_url.cache_clear()
    first = asset_url("app.css")
    assert re.fullmatch(r"/static/app\.css\?v=[0-9a-f]{10}", first)

    (tmp_path / "app.css").write_text("b{}", encoding="utf-8")
    static_files.asset_url.cache_clear()
    assert asset_url("app.css") != first
    static_files.asset_url.cache_clear()


def test_templates_load_css_and_js_through_versioned_urls():
    for template in TEMPLATES.glob("*.html"):
        html = template.read_text(encoding="utf-8")
        plain = re.findall(r'(?:href|src)="/static/[^"]+\.(?:css|js)"', html)
        assert not plain, f"{template.name} loads an unversioned asset: {plain}"


def test_rendered_pages_carry_the_versioned_urls(client):
    login = client.get("/api/auth/login")
    assert login.status_code == 200
    assert asset_url("app.css") in login.text


def test_static_and_analysis_files_are_revalidated(client):
    for path in ("/static/app.css", "/static/reserve_chart.js", "/analysis/", "/analysis/today.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("cache-control") == "no-cache", path
