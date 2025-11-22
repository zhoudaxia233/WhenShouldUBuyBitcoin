import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlmodel import select
from datetime import datetime, timezone, timedelta

from dca_service.models import ManualTransaction, DCATransaction, BinanceCredentials, DCAStrategy
from dca_service.services.security import encrypt_text

def test_create_manual_transaction(client, session):
    response = client.post("/api/manual_transaction", json={
        "type": "BUY",
        "btc_amount": 0.5,
        "fiat_amount": 50000.0,
        "price_usd": 100000.0,
        "fee_usdc": 10.0,
        "notes": "Ledger buy"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "BUY"
    assert data["btc_amount"] == 0.5
    assert data["notes"] == "Ledger buy"
    
    # Verify DB
    tx = session.exec(select(ManualTransaction)).first()
    assert tx is not None
    assert tx.btc_amount == 0.5
    assert tx.type == "BUY"

def test_create_manual_transaction_validation(client):
    # Missing fiat for BUY
    response = client.post("/api/manual_transaction", json={
        "type": "BUY",
        "btc_amount": 0.5
    })
    assert response.status_code == 400
    assert "Fiat amount required" in response.json()["detail"]
    
    # Zero BTC
    response = client.post("/api/manual_transaction", json={
        "type": "TRANSFER_IN",
        "btc_amount": 0
    })
    assert response.status_code == 400
    assert "BTC amount cannot be zero" in response.json()["detail"]

def test_create_manual_transaction_required_fields(client):
    # Missing Price (now required)
    response = client.post("/api/manual_transaction", json={
        "type": "TRANSFER_IN",
        "btc_amount": 0.1,
        "fiat_amount": 1000.0
    })
    assert response.status_code == 400
    assert "Price (USD) is required" in response.json()["detail"]
    
    # Missing Fiat (now required for all types)
    response = client.post("/api/manual_transaction", json={
        "type": "TRANSFER_IN",
        "btc_amount": 0.1,
        "price_usd": 50000.0
    })
    assert response.status_code == 400
    assert "Fiat Amount (USD) is required" in response.json()["detail"]

def test_read_transactions_with_null_fields(client, session):
    # Manually insert a record with nulls (simulating old data that caused crash)
    # This bypasses API validation
    bad_tx = ManualTransaction(
        type="BUY",
        btc_amount=0.1,
        fiat_amount=None, # Should be required but DB might allow null if not strict
        price_usd=None,
        timestamp=datetime.now(timezone.utc)
    )
    session.add(bad_tx)
    session.commit()
    
    # Verify GET /transactions doesn't crash backend
    response = client.get("/api/transactions")
    assert response.status_code == 200
    data = response.json()
    
    # Find our bad transaction
    tx = next(t for t in data if t["id"] == f"MAN-{bad_tx.id}" and t["source"] == "MANUAL")
    assert tx["fiat_amount"] is None
    assert tx["price"] is None
    # If this passes, the backend is resilient. 
    # The frontend fix (already applied) handles these nulls.

@patch("dca_service.services.binance_client.httpx.AsyncClient")
def test_holdings_aggregation(mock_client_cls, client, session):
    # Setup Binance Creds
    enc_key = encrypt_text("key")
    enc_secret = encrypt_text("secret")
    session.add(BinanceCredentials(api_key_encrypted=enc_key, api_secret_encrypted=enc_secret))
    
    # Setup Strategy (target 2.0 BTC)
    session.add(DCAStrategy(
        target_btc_amount=2.0, 
        total_budget_usd=1000.0, 
        is_active=True,
        ahr999_multiplier_low=1.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.0
    ))
    
    # Add Manual Transaction (0.5 BTC)
    session.add(ManualTransaction(
        type="BUY",
        btc_amount=0.5,
        fiat_amount=1000.0,
        timestamp=datetime.now(timezone.utc)
    ))
    session.commit()
    
    # Mock Binance Client (returns 1.0 BTC)
    mock_instance = AsyncMock()
    mock_client_cls.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "balances": [
            {"asset": "BTC", "free": "1.0", "locked": "0.0"},
            {"asset": "USDT", "free": "1000.0", "locked": "0.0"}
        ]
    }
    mock_response.raise_for_status.return_value = None
    mock_instance.request.return_value = mock_response
    
    # Call API
    response = client.get("/api/binance/holdings")
    assert response.status_code == 200
    data = response.json()
    
    # Total should be 1.0 (Binance) + 0.5 (Manual) = 1.5
    assert data["btc_balance"] == 1.5
    assert data["target_btc_amount"] == 2.0
    assert data["progress_ratio"] == 0.75 # 1.5 / 2.0

def test_unified_history(client, session):
    # Add DCA Transaction (older)
    dca_time = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.5,
        timestamp=dca_time,
        source="SIMULATED"
    ))
    
    # Add Manual Transaction (newer)
    manual_time = datetime.now(timezone.utc)
    session.add(ManualTransaction(
        type="TRANSFER_IN",
        btc_amount=0.1,
        timestamp=manual_time,
        notes="Deposit"
    ))
    session.commit()
    
    response = client.get("/api/transactions")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) == 2
    # Should be sorted by timestamp desc (Manual first)
    assert data[0]["source"] == "MANUAL"
    assert data[0]["type"] == "TRANSFER_IN"
    assert data[0]["btc_amount"] == 0.1
    
    assert data[1]["source"] == "SIMULATED"
    assert data[1]["type"] == "DCA"
    assert data[1]["btc_amount"] == 0.001

def test_unified_history_id_collision(client, session):
    # Create DCA tx with ID 1 (if possible, or just let DB assign it)
    # Since we can't easily force ID in SQLModel without setting it explicitly
    # We'll just create one of each and check the prefixes
    
    dca_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.5,
        source="SIMULATED"
    )
    session.add(dca_tx)
    
    manual_tx = ManualTransaction(
        type="BUY",
        btc_amount=0.1,
        fiat_amount=1000.0,
        price_usd=10000.0
    )
    session.add(manual_tx)
    session.commit()
    
    # Refresh to get IDs
    session.refresh(dca_tx)
    session.refresh(manual_tx)
    
    response = client.get("/api/transactions")
    assert response.status_code == 200
    data = response.json()
    
    # Verify IDs are prefixed strings
    dca_entry = next(t for t in data if t["type"] == "DCA")
    manual_entry = next(t for t in data if t["source"] == "MANUAL")
    
    assert dca_entry["id"] == f"DCA-{dca_tx.id}"
    assert manual_entry["id"] == f"MAN-{manual_tx.id}"
    
    # Even if numeric IDs were same (e.g. both 1), string IDs should differ
    assert dca_entry["id"] != manual_entry["id"]
