"""The server remembers where the cold storage balance came from.

The server keeps the source ("public_key" or "manual") and the time of the
last change, so every device can say where the number came from and stops
syncing once the balance was entered by hand.
"""
from fastapi.testclient import TestClient


def _post(client: TestClient, body: dict):
    return client.post("/api/wallet/cold-balance", json=body)


def test_balance_synced_from_a_public_key_is_marked_as_such(client: TestClient):
    response = _post(client, {"balance": 0.32819137, "source": "public_key"})

    assert response.status_code == 200
    summary = response.json()
    assert summary["cold_wallet_balance"] == 0.32819137
    assert summary["cold_wallet_source"] == "public_key"
    # Sent with its timezone, so browsers do not read it as their local time.
    assert summary["cold_wallet_updated_at"].endswith(("Z", "+00:00"))


def test_balance_entered_by_hand_is_marked_manual(client: TestClient):
    _post(client, {"balance": 0.3, "source": "public_key"})
    response = _post(client, {"balance": 0.31, "source": "manual"})

    assert response.status_code == 200
    assert response.json()["cold_wallet_source"] == "manual"
    assert client.get("/api/wallet/summary").json()["cold_wallet_source"] == "manual"


def test_balance_posted_without_a_source_is_unknown(client: TestClient):
    """A page loaded before this change posts no source; say nothing rather than guess."""
    response = _post(client, {"balance": 0.2})

    assert response.status_code == 200
    assert response.json()["cold_wallet_source"] is None


def test_unknown_source_is_rejected(client: TestClient):
    assert _post(client, {"balance": 0.2, "source": "xpub"}).status_code == 422


def test_global_settings_migration_adds_the_source_column(tmp_path, monkeypatch):
    """Databases from before this change get the column, empty, so their balance reads as unknown."""
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
        row = conn.execute(text("SELECT cold_wallet_balance, cold_wallet_source FROM global_settings")).one()
    assert row == (0.32819137, None)
