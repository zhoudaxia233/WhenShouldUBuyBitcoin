"""The server keeps the wallet's public keys, so every device can refresh the balance.

Keys are encrypted at rest like the Binance credentials, go only to a logged-in
admin, and never appear in the wallet summary, which a read-only token can read.
Balances are still read in the browser; the server only stores the keys.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session

from dca_service.auth.dependencies import get_current_user
from dca_service.main import app
from dca_service.models import GlobalSettings, User

# BIP84 test vector: "abandon abandon ... about", account m/84'/0'/0'.
ZPUB = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
# The same account key as Ledger Live shows it.
XPUB = "xpub6CatWdiZiodmUeTDp8LT5or8nmbKNcuyvz7WyksVFkKB4RHwCD3XyuvPEbvqAQY3rAPshWcMLoP2fMFMKHPJ4ZeZXYVUhLv1VMrjPC7PW6V"
ZPRV = "zprvAdG4iTXWBoARxkkzNpNh8r6Qag3irQB8PzEMkAFeTRXxHpbF9z4QgEvBRphj53hJFiBVJ1gYbNLfpUvgs1imuBRbkDZx1qjw6x6nQFUc6rX"


def _put(client: TestClient, keys):
    return client.put("/api/wallet/cold-keys", json={"keys": keys})


def _as_user(is_admin: bool):
    app.dependency_overrides[get_current_user] = lambda: User(
        id=7, email="someone@example.com", password_hash="x", is_admin=is_admin, is_active=True,
    )


def test_a_saved_key_opens_on_any_logged_in_device(client: TestClient):
    assert client.get("/api/wallet/cold-keys").json() == {"keys": []}

    assert _put(client, [ZPUB, XPUB]).status_code == 200

    assert client.get("/api/wallet/cold-keys").json() == {"keys": [ZPUB, XPUB]}


def test_keys_are_encrypted_in_the_database(client: TestClient, session: Session):
    _put(client, [ZPUB])

    stored = session.get(GlobalSettings, 1).cold_wallet_keys_encrypted
    assert stored
    assert ZPUB not in stored


def test_saving_new_keys_replaces_the_old_ones(client: TestClient):
    _put(client, [ZPUB])
    _put(client, [XPUB])

    assert client.get("/api/wallet/cold-keys").json() == {"keys": [XPUB]}


def test_removing_the_keys_leaves_nothing_behind(client: TestClient, session: Session):
    _put(client, [ZPUB])

    assert _put(client, []).status_code == 200

    assert client.get("/api/wallet/cold-keys").json() == {"keys": []}
    assert session.get(GlobalSettings, 1).cold_wallet_keys_encrypted is None


def test_saving_keys_does_not_touch_the_balance_or_its_time(client: TestClient):
    client.post("/api/wallet/cold-balance", json={"balance": 0.3, "source": "public_key"})
    before = client.get("/api/wallet/summary").json()

    _put(client, [ZPUB])

    after = client.get("/api/wallet/summary").json()
    assert after["cold_wallet_balance"] == before["cold_wallet_balance"]
    assert after["cold_wallet_source"] == before["cold_wallet_source"]
    assert after["cold_wallet_updated_at"] == before["cold_wallet_updated_at"]


def test_a_private_key_is_refused_and_never_echoed(client: TestClient):
    response = _put(client, [ZPUB, ZPRV])

    assert response.status_code == 422
    assert ZPRV not in response.text
    assert client.get("/api/wallet/cold-keys").json() == {"keys": []}


def test_text_that_is_no_public_key_is_refused(client: TestClient):
    assert _put(client, ["hello"]).status_code == 422
    assert _put(client, [ZPUB + "0"]).status_code == 422


def test_keys_that_can_no_longer_be_decrypted_read_as_none(client: TestClient, session: Session):
    """After a changed encryption key the page offers setup again, not an error."""
    _put(client, [ZPUB])
    settings = session.get(GlobalSettings, 1)
    settings.cold_wallet_keys_encrypted = "not-a-fernet-token"
    session.add(settings)
    session.commit()

    response = client.get("/api/wallet/cold-keys")

    assert response.status_code == 200
    assert response.json() == {"keys": []}


def test_keys_are_not_cached(client: TestClient):
    _put(client, [ZPUB])
    assert client.get("/api/wallet/cold-keys").headers["cache-control"] == "no-store"


def test_only_an_admin_reaches_the_keys(client: TestClient):
    _put(client, [ZPUB])
    _as_user(is_admin=False)

    assert client.get("/api/wallet/cold-keys").status_code == 403
    assert _put(client, []).status_code == 403


def test_keys_stay_out_of_the_summary_a_read_token_can_read(client: TestClient):
    _put(client, [ZPUB])

    assert ZPUB not in client.get("/api/wallet/summary").text


def test_read_token_cannot_read_the_keys():
    """The token works on the summary alone; the keys need a session login."""
    from dca_service.api import wallet_api
    from dca_service.auth.dependencies import get_current_admin_user

    routes = [r for r in wallet_api.router.routes if r.path == "/wallet/cold-keys"]
    assert {method for r in routes for method in r.methods} == {"GET", "PUT"}
    for route in routes:
        assert get_current_admin_user in [d.call for d in route.dependant.dependencies]


def test_global_settings_migration_adds_the_keys_column(tmp_path, monkeypatch):
    from sqlmodel import create_engine, text

    import dca_service.database as database

    old_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE global_settings (id INTEGER PRIMARY KEY, cold_wallet_balance FLOAT, updated_at TIMESTAMP)"
        ))
        conn.execute(text("INSERT INTO global_settings (id, cold_wallet_balance) VALUES (1, 0.32819137)"))
    monkeypatch.setattr(database, "engine", old_engine)

    database._migrate_global_settings_table()
    database._migrate_global_settings_table()  # idempotent

    with old_engine.connect() as conn:
        row = conn.execute(text("SELECT cold_wallet_balance, cold_wallet_keys_encrypted FROM global_settings")).one()
    assert row == (0.32819137, None)
