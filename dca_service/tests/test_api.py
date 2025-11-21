from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.models import DCATransaction

def test_read_transactions_empty(client: TestClient):
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert response.json() == []

def test_simulate_transaction(client: TestClient):
    response = client.post(
        "/api/transactions/simulate",
        json={
            "fiat_amount": 100.0,
            "ahr999": 0.45,
            "price": 50000.0,
            "notes": "Test simulation"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["fiat_amount"] == 100.0
    assert data["btc_amount"] == 0.002  # 100 / 50000
    assert data["id"] is not None

def test_read_transactions_populated(client: TestClient, session: Session):
    # Create a transaction first
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.002,
        price=50000.0,
        ahr999=0.45,
        notes="Test"
    )
    session.add(tx)
    session.commit()
    
    response = client.get("/api/transactions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["fiat_amount"] == 100.0
