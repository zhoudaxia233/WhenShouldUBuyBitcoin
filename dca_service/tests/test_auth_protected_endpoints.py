from fastapi.testclient import TestClient
from sqlmodel import Session
import pytest

from dca_service.main import app
from dca_service.database import get_session


@pytest.fixture(name="unauth_client")
def unauth_client_fixture(session: Session):
    """Client without auth override to verify protected endpoints."""

    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/strategy",
        "/api/dca/preview",
        "/api/binance/credentials/status",
        "/api/email/settings/status",
        "/api/wallet/summary",
    ],
)
def test_endpoint_requires_authentication_redirects_to_login(
    unauth_client: TestClient, endpoint: str
):
    response = unauth_client.get(endpoint, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"
