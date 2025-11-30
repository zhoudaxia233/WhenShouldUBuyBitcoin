from fastapi.testclient import TestClient
from sqlmodel import Session
from dca_service.main import app
from dca_service.models import DCATransaction, GlobalSettings
from dca_service.database import get_session
import pytest
from datetime import datetime, timezone

def test_stats_distribution(client: TestClient):
    response = client.get("/api/stats/distribution")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert "tier" in data[0]
    assert "percentile" in data[0]

def test_stats_percentile(client: TestClient, session: Session):
    # Setup: Set cold wallet balance (since hot wallet requires Binance API)
    from dca_service.models import GlobalSettings
    settings = session.get(GlobalSettings, 1)
    settings.cold_wallet_balance = 0.15
    session.add(settings)
    session.commit()
    
    response = client.get("/api/stats/percentile")
    assert response.status_code == 200
    data = response.json()
    assert data["total_btc"] == 0.15
    assert data["percentile_top"] <= 27.38
    assert "Top" in data["message"]

def test_stats_pnl(client: TestClient, session: Session):
    # Setup: Add transactions
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=1000.0,
        btc_amount=0.02,
        price=50000.0,
        ahr999=0.5,
        notes="Buy 1",
        timestamp=datetime(2023, 1, 1, tzinfo=timezone.utc)
    )
    session.add(tx1)
    
    tx2 = DCATransaction(
        status="SUCCESS",
        fiat_amount=1000.0,
        btc_amount=0.01, # Price doubled to 100k
        price=100000.0,
        ahr999=1.0,
        notes="Buy 2",
        timestamp=datetime(2023, 2, 1, tzinfo=timezone.utc)
    )
    session.add(tx2)
    session.commit()
    
    response = client.get("/api/stats/pnl")
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["dates"]) == 2
    assert len(data["invested"]) == 2
    assert len(data["value"]) == 2
    
    # Check cumulative values
    # First point: Invested 1000, Value 1000 (0.02 * 50000)
    assert data["invested"][0] == 1000.0
    assert data["value"][0] == 1000.0
    
    # Second point: Invested 2000, Value (0.02 + 0.01) * 100000 = 0.03 * 100000 = 3000
    # Wait, my logic in stats_api.py uses the transaction price as the "current price" for the WHOLE portfolio at that moment?
    # Let's check the logic:
    # current_value = cumulative_btc * current_price
    # Yes. So at T2, we have 0.03 BTC, price is 100k, so value is 3000.
    assert data["invested"][1] == 2000.0
    assert data["value"][1] == 3000.0
