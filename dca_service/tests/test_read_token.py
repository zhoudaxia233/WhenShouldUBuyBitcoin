"""
Read-only API token for GET /api/wallet/summary.

- Another program (the owner's freedom-ledger relay) reads the summary with
  `Authorization: Bearer <token>` instead of a browser login.
- The token opens that one endpoint only; every other route and every write
  still needs the session login.
- Wrong, missing or revoked tokens get a plain 401, not the login redirect,
  so the caller sees why it failed.
- Only a hash is stored.
"""
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.api import wallet_api
from dca_service.api.schemas import WalletSummary
from dca_service.database import get_session
from dca_service.main import app
from dca_service.models import ReadToken


SUMMARY = WalletSummary(
    cold_wallet_balance=0.5,
    hot_wallet_balance=0.25,
    hot_wallet_avg_price=0.0,
    total_btc=0.75,
    current_price=0.0,
    cold_wallet_value_usd=0.0,
    hot_wallet_value_usd=0.0,
    total_value_usd=0.0,
)


@pytest.fixture(autouse=True)
def fixed_summary(monkeypatch):
    async def fake_summary(session):
        return SUMMARY

    monkeypatch.setattr(wallet_api, "fetch_wallet_summary", fake_summary)


@pytest.fixture(name="real_auth_client")
def real_auth_client_fixture(session: Session):
    """Client that goes through the real auth dependencies."""
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app, follow_redirects=False)
    yield client
    app.dependency_overrides.clear()


def _login(client: TestClient) -> None:
    page = client.get("/api/auth/login")
    csrf = page.text.split('name="csrf_token" value="')[1].split('"')[0]
    response = client.post(
        "/api/auth/login",
        data={"email": "test@example.com", "password": "testpassword123", "csrf_token": csrf},
    )
    assert response.status_code == 303


def _create_token(client: TestClient) -> str:
    _login(client)
    response = client.post("/api/read-token")
    assert response.status_code == 200
    token = response.json()["token"]
    client.cookies.clear()
    return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_token_reads_the_wallet_summary(real_auth_client: TestClient):
    token = _create_token(real_auth_client)

    response = real_auth_client.get("/api/wallet/summary", headers=_bearer(token))

    assert response.status_code == 200
    assert response.json() == SUMMARY.model_dump()


def test_only_a_hash_is_stored(real_auth_client: TestClient, session: Session):
    token = _create_token(real_auth_client)

    stored = session.exec(select(ReadToken)).all()
    assert len(stored) == 1
    assert stored[0].token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored[0].token_hash


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/strategy"),
        ("GET", "/api/binance/credentials/status"),
        ("GET", "/api/email/settings/status"),
        ("GET", "/api/read-token"),
        ("GET", "/"),
        ("POST", "/api/wallet/cold-balance"),
        ("POST", "/api/read-token"),
        ("DELETE", "/api/read-token"),
    ],
)
def test_token_opens_nothing_else(real_auth_client: TestClient, method: str, path: str):
    token = _create_token(real_auth_client)

    response = real_auth_client.request(
        method, path, headers=_bearer(token), json={"balance": 9.0}
    )

    assert response.status_code == 401


def test_token_cannot_change_the_cold_balance(real_auth_client: TestClient, session: Session):
    from dca_service.models import GlobalSettings

    token = _create_token(real_auth_client)
    real_auth_client.post(
        "/api/wallet/cold-balance", headers=_bearer(token), json={"balance": 9.0}
    )

    session.expire_all()
    assert session.get(GlobalSettings, 1).cold_wallet_balance == 0.0


@pytest.mark.parametrize("header", ["Bearer wrong", "Bearer ", "Basic abc", "Bearer"])
def test_wrong_token_gets_401(real_auth_client: TestClient, header: str):
    _create_token(real_auth_client)

    response = real_auth_client.get("/api/wallet/summary", headers={"Authorization": header})

    assert response.status_code == 401
    assert "location" not in response.headers


def test_no_token_and_no_login_still_redirects_to_login(real_auth_client: TestClient):
    response = real_auth_client.get("/api/wallet/summary")

    assert response.status_code == 303
    assert response.headers["location"] == "/api/auth/login"


def test_revoked_token_gets_401(real_auth_client: TestClient):
    token = _create_token(real_auth_client)
    _login(real_auth_client)
    assert real_auth_client.delete("/api/read-token").status_code == 200
    real_auth_client.cookies.clear()

    response = real_auth_client.get("/api/wallet/summary", headers=_bearer(token))

    assert response.status_code == 401


def test_new_token_replaces_the_old_one(real_auth_client: TestClient, session: Session):
    old = _create_token(real_auth_client)
    new = _create_token(real_auth_client)

    assert real_auth_client.get("/api/wallet/summary", headers=_bearer(old)).status_code == 401
    assert real_auth_client.get("/api/wallet/summary", headers=_bearer(new)).status_code == 200
    assert len(session.exec(select(ReadToken)).all()) == 1


def test_token_of_a_disabled_user_gets_401(real_auth_client: TestClient, session: Session, test_user):
    token = _create_token(real_auth_client)
    test_user.is_active = False
    session.add(test_user)
    session.commit()

    response = real_auth_client.get("/api/wallet/summary", headers=_bearer(token))

    assert response.status_code == 401


def test_status_shows_whether_a_token_exists_but_never_the_token(real_auth_client: TestClient):
    _login(real_auth_client)
    assert real_auth_client.get("/api/read-token").json()["has_token"] is False

    token = real_auth_client.post("/api/read-token").json()["token"]
    status = real_auth_client.get("/api/read-token").json()

    assert status["has_token"] is True
    assert status["created_at"]
    assert token not in str(status)


def test_created_at_says_it_is_utc(real_auth_client: TestClient):
    # SQLite drops the timezone; without an offset the browser reads UTC as local time
    from datetime import datetime

    _login(real_auth_client)
    real_auth_client.post("/api/read-token")

    created = real_auth_client.get("/api/read-token").json()["created_at"]

    assert datetime.fromisoformat(created).utcoffset().total_seconds() == 0


def test_session_login_still_reads_the_summary(real_auth_client: TestClient):
    _create_token(real_auth_client)
    _login(real_auth_client)

    response = real_auth_client.get("/api/wallet/summary")

    assert response.status_code == 200
    assert response.json()["total_btc"] == 0.75


def test_settings_page_offers_the_token():
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[1]
        / "src" / "dca_service" / "templates" / "binance_settings.html"
    ).read_text(encoding="utf-8")

    assert 'id="readTokenCard"' in html
    assert "fetch('/api/read-token'" in html
    # The token is shown once and never logged
    block = html[html.index("// ============= READ-ONLY TOKEN"):]
    assert "console.log" not in block[: block.index("// ============= END READ-ONLY TOKEN")]
