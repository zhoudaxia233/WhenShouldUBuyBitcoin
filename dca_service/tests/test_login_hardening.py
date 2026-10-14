"""
Login hardening regressions.

- Logging out must revoke every copy of the session cookie, not only the
  browser's own copy (session cookies are signed, stateless values).
- The login response must not reveal whether an email exists through timing.
- Responses carry anti-framing / HSTS headers; API docs need a login.
"""
import base64
import json

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlmodel import Session

from dca_service.config import settings
from dca_service.database import get_session
from dca_service.main import app


@pytest.fixture(name="real_auth_client")
def real_auth_client_fixture(session: Session):
    """Client that goes through the real get_current_user."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app, follow_redirects=False)
    yield client
    app.dependency_overrides.clear()


def _csrf(client: TestClient) -> str:
    response = client.get("/api/auth/login")
    return response.text.split('name="csrf_token" value="')[1].split('"')[0]


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        data={
            "email": "test@example.com",
            "password": "testpassword123",
            "csrf_token": _csrf(client),
        },
    )
    assert response.status_code == 303


def test_logout_revokes_copied_session_cookie(real_auth_client: TestClient):
    _login(real_auth_client)
    copied_cookie = real_auth_client.cookies.get(settings.SESSION_COOKIE_NAME)

    other_device = TestClient(
        app, follow_redirects=False, cookies={settings.SESSION_COOKIE_NAME: copied_cookie}
    )
    assert other_device.get("/api/wallet/summary").status_code == 200

    real_auth_client.post("/api/auth/logout")

    response = other_device.get("/api/wallet/summary")
    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


def test_login_on_another_device_keeps_existing_sessions(real_auth_client: TestClient):
    """Only logout revokes sessions; logging in elsewhere must not sign anyone out."""
    _login(real_auth_client)

    second_device = TestClient(app, follow_redirects=False)
    _login(second_device)

    assert real_auth_client.get("/api/wallet/summary").status_code == 200
    assert second_device.get("/api/wallet/summary").status_code == 200


@pytest.mark.parametrize(
    "path",
    ["/api/auth/login", "/healthz", "/api/version", "/static/favicon.svg", "/analysis/"],
)
def test_public_pages_need_no_login(real_auth_client: TestClient, path: str):
    response = real_auth_client.get(path)
    if response.status_code == 404 and path == "/analysis/":
        pytest.skip("docs/ is not present")
    assert response.status_code == 200


def test_session_without_version_is_rejected(real_auth_client: TestClient):
    """Cookies signed before session versions existed must not stay valid."""
    payload = base64.b64encode(json.dumps({"user_id": 1}).encode("utf-8"))
    legacy_cookie = TimestampSigner(settings.SESSION_SECRET).sign(payload).decode("utf-8")

    client = TestClient(
        app, follow_redirects=False, cookies={settings.SESSION_COOKIE_NAME: legacy_cookie}
    )
    response = client.get("/api/wallet/summary")
    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


def test_unknown_email_still_runs_password_check(real_auth_client: TestClient, monkeypatch):
    """Skipping bcrypt for unknown emails makes them answer ~100x faster."""
    import dca_service.api.auth_api as auth_api

    calls = []
    real_verify = auth_api.verify_password

    def counting_verify(plain, hashed):
        calls.append(hashed)
        return real_verify(plain, hashed)

    monkeypatch.setattr(auth_api, "verify_password", counting_verify)

    response = real_auth_client.post(
        "/api/auth/login",
        data={
            "email": "nobody@example.com",
            "password": "whatever-password",
            "csrf_token": _csrf(real_auth_client),
        },
    )
    assert response.status_code == 401
    assert len(calls) == 1
    assert calls[0].startswith("$2b$")


def test_app_pages_refuse_cross_site_framing(real_auth_client: TestClient):
    response = real_auth_client.get("/api/auth/login")
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_public_analysis_site_stays_embeddable(real_auth_client: TestClient):
    response = real_auth_client.get("/analysis/")
    if response.status_code == 404:
        pytest.skip("docs/ is not present")
    assert "x-frame-options" not in response.headers


def test_hsts_only_when_served_over_https(real_auth_client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "SESSION_COOKIE_HTTPS_ONLY", False)
    assert "strict-transport-security" not in real_auth_client.get("/healthz").headers

    monkeypatch.setattr(settings, "SESSION_COOKIE_HTTPS_ONLY", True)
    assert (
        real_auth_client.get("/healthz").headers["strict-transport-security"]
        == "max-age=31536000"
    )


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/api/openapi.json"])
def test_api_docs_require_login(real_auth_client: TestClient, path: str):
    response = real_auth_client.get(path)
    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/api/openapi.json"])
def test_api_docs_work_after_login(client: TestClient, path: str):
    response = client.get(path)
    assert response.status_code == 200


def test_openapi_schema_lists_api_routes(client: TestClient):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/wallet/summary" in paths
    assert "/docs" not in paths


def test_users_table_migration_adds_session_version(tmp_path, monkeypatch):
    """Production databases created before session versions get the column."""
    from sqlmodel import create_engine, text

    import dca_service.database as database

    old_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT, "
            "is_active BOOLEAN, is_admin BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP)"
        ))
        conn.execute(text("INSERT INTO users (id, email, password_hash) VALUES (1, 'a@b.c', 'x')"))
    monkeypatch.setattr(database, "engine", old_engine)

    database._migrate_users_table()
    database._migrate_users_table()  # idempotent

    with old_engine.connect() as conn:
        assert conn.execute(text("SELECT session_version FROM users")).scalar_one() == 0
