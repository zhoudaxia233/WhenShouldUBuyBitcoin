from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import patch
from datetime import datetime

from dca_service.models import DCAStrategy

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_preview_dca(mock_metrics, client: TestClient, session: Session):
    # Setup strategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5
    )
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {"ahr999": 0.4, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    response = client.get("/api/dca/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["can_execute"] is True
    assert data["ahr_band"] == "low"
    assert data["suggested_amount_usd"] == 25.0 # 50 * 0.5

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_execute_simulated_dca(mock_metrics, client: TestClient, session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5
    )
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {"ahr999": 0.4, "price_usd": 50000.0, "timestamp": datetime.utcnow()}
    
    response = client.post("/api/dca/execute-simulated")
    assert response.status_code == 200
    data = response.json()
    
    assert data["transaction"] is not None
    assert data["transaction"]["status"] == "SUCCESS"
    assert data["transaction"]["notes"] == "SIMULATED"
    
    # Verify DB
    from dca_service.models import DCATransaction
    from sqlmodel import select
    tx = session.exec(select(DCATransaction)).first()
    assert tx is not None
    assert tx.fiat_amount == 25.0
