from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient
from sqlmodel import Session

from dca_service.auth.dependencies import get_current_user
from dca_service.config import settings
from dca_service.api import admin_api
from dca_service.main import app
from dca_service.models import User
from dca_service.services.distribution_scraper import clear_cache


@pytest.fixture(autouse=True)
def reset_distribution_scraper_state():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def unauth_client(session: Session):
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _non_admin_user() -> User:
    return User(
        id=2,
        email="user@example.com",
        password_hash="test_hash",
        is_active=True,
        is_admin=False,
    )


@pytest.fixture
def non_admin_client(session: Session):
    def get_current_user_override():
        return _non_admin_user()

    app.dependency_overrides[get_current_user] = get_current_user_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_admin_data_sources_api_requires_login(unauth_client: TestClient):
    response = unauth_client.get(
        "/api/admin/data-sources/bitinfocharts",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


def test_admin_data_sources_page_requires_login(unauth_client: TestClient):
    response = unauth_client.get("/admin/data-sources", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


def test_admin_data_sources_api_rejects_non_admin(non_admin_client: TestClient):
    response = non_admin_client.get("/api/admin/data-sources/bitinfocharts")

    assert response.status_code == 403


def test_admin_data_sources_page_rejects_non_admin(non_admin_client: TestClient):
    response = non_admin_client.get("/admin/data-sources")

    assert response.status_code == 403


def test_admin_can_view_bitinfocharts_diagnostics(client: TestClient):
    response = client.get("/api/admin/data-sources/bitinfocharts")

    assert response.status_code == 200
    data = response.json()
    assert "diagnostics" in data
    assert data["diagnostics"]["target_url"] == "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html"

    page = client.get("/admin/data-sources")
    assert page.status_code == 200
    assert "BitInfoCharts" in page.text
    assert "Refresh now" in page.text


def test_admin_dashboard_shows_data_sources_entry(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert 'href="/admin/data-sources"' in response.text
    assert 'admin-diagnostics-link' in response.text


def test_non_admin_dashboard_hides_data_sources_entry(non_admin_client: TestClient):
    response = non_admin_client.get("/")

    assert response.status_code == 200
    assert 'href="/admin/data-sources"' not in response.text


def test_admin_entry_is_standalone_not_inside_settings_dropdown(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    settings_menu = response.text[
        response.text.index('aria-labelledby="settingsDropdown"') :
        response.text.index("</ul>", response.text.index('aria-labelledby="settingsDropdown"'))
    ]
    assert "/admin/data-sources" not in settings_menu
    assert response.text.index('admin-diagnostics-link') > response.text.index("</ul>", response.text.index('aria-labelledby="settingsDropdown"'))


def test_admin_entry_is_available_on_authenticated_nav_pages(client: TestClient):
    for path in ["/", "/stats", "/strategy", "/settings/binance", "/admin/data-sources"]:
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/admin/data-sources"' in response.text
        assert 'admin-diagnostics-link' in response.text


def test_non_admin_nav_pages_hide_admin_entry(non_admin_client: TestClient):
    for path in ["/", "/stats", "/strategy", "/settings/binance"]:
        response = non_admin_client.get(path)
        assert response.status_code == 200
        assert 'href="/admin/data-sources"' not in response.text
        assert 'admin-diagnostics-link' not in response.text


def test_non_admin_stats_page_does_not_ship_admin_ops_endpoints(non_admin_client: TestClient):
    response = non_admin_client.get("/stats")

    assert response.status_code == 200
    assert "/api/static/regenerate" not in response.text
    assert "/api/static/regenerate/status" not in response.text
    assert "log_tail" not in response.text


def test_dashboard_does_not_render_raw_api_detail_messages(non_admin_client: TestClient):
    response = non_admin_client.get("/")

    assert response.status_code == 200
    assert "payload?.detail" not in response.text
    assert "textContent = String(error?.message" not in response.text


def test_admin_data_sources_page_has_theme_toggle(client: TestClient):
    response = client.get("/admin/data-sources")

    assert response.status_code == 200
    assert "localStorage.getItem('dca_theme')" in response.text
    assert "data-bs-theme" in response.text
    assert 'id="themeToggleBtn"' in response.text


def test_admin_data_sources_page_uses_bootstrap_theme_variables(client: TestClient):
    response = client.get("/admin/data-sources")

    assert response.status_code == 200
    assert "background-color: var(--bs-body-bg)" in response.text
    assert 'html[data-bs-theme="dark"] body' not in response.text


def test_admin_data_sources_page_loads_bootstrap_bundle_for_shared_dropdown(client: TestClient):
    response = client.get("/admin/data-sources")

    assert response.status_code == 200
    assert "bootstrap.bundle.min.js" in response.text
    assert response.text.index("bootstrap.bundle.min.js") < response.text.index(
        "document.addEventListener('DOMContentLoaded'"
    )


def test_admin_diagnostics_api_includes_sanitized_runtime_logs(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    log_file = tmp_path / "dca_service.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-05-25 10:00:00 | INFO | started",
                "2026-05-25 10:00:01 | ERROR | requests.exceptions.Timeout: Read timed out",
                "2026-05-25 10:00:02 | ERROR | api_secret=super-secret password=1234 Bearer abc.def.ghi",
                "2026-05-25 10:00:03 | ERROR | Authorization: Bearer header.token.value",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_file))
    monkeypatch.setattr(
        admin_api,
        "get_static_generation_log_path",
        lambda: tmp_path / "static_generation.log",
        raising=False,
    )

    response = client.get("/api/admin/data-sources/bitinfocharts")

    assert response.status_code == 200
    data = response.json()
    assert "runtime" in data
    assert data["runtime"]["app_version"]
    assert data["runtime"]["service_log"]["exists"] is True
    assert data["runtime"]["service_log"]["line_count"] == 4
    assert any("Read timed out" in line for line in data["runtime"]["service_log"]["tail"])
    assert "super-secret" not in response.text
    assert "password=1234" not in response.text
    assert "Bearer abc.def.ghi" not in response.text
    assert "header.token.value" not in response.text
    assert "[REDACTED]" in response.text


def test_admin_refresh_timeout_updates_diagnostics_without_raw_error(client: TestClient):
    clear_cache()
    raw_timeout = requests.exceptions.Timeout(
        "HTTPSConnectionPool(host='bitinfocharts.com', port=443): Read timed out. raw socket details"
    )

    with patch("requests.get", side_effect=raw_timeout):
        response = client.post("/api/admin/data-sources/bitinfocharts/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    diagnostics = data["diagnostics"]
    assert diagnostics["last_status"] == "unavailable"
    assert diagnostics["last_error_type"] == "Timeout"
    assert diagnostics["last_error_message_sanitized"] == "Request timed out while contacting BitInfoCharts."
    assert "HTTPSConnectionPool" not in response.text
    assert "raw socket details" not in response.text


def test_admin_refresh_success_reports_tier_count(client: TestClient):
    clear_cache()
    response = MagicMock()
    response.text = """
    <table>
      <thead>
        <tr>
          <th>Balance, BTC</th>
          <th>Addresses</th>
          <th>% Addresses (Total)</th>
          <th>BTC</th>
          <th>USD</th>
          <th>% BTC (Total)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>[1 - 10)</td>
          <td>200000</td>
          <td>1.40% (1.66%)</td>
          <td>500000</td>
          <td>$38200000000</td>
          <td>2.50%</td>
        </tr>
      </tbody>
    </table>
    """
    response.status_code = 200
    response.raise_for_status.return_value = None

    with patch("requests.get", return_value=response):
        api_response = client.post("/api/admin/data-sources/bitinfocharts/refresh")

    assert api_response.status_code == 200
    data = api_response.json()
    assert data["success"] is True
    assert data["tier_count"] == 1
    assert data["diagnostics"]["last_status"] == "live"
