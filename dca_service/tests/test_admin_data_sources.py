from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient
from sqlmodel import Session

from dca_service.auth.dependencies import get_current_user
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
