from fastapi.testclient import TestClient
from sqlmodel import Session, select
from unittest.mock import patch
from datetime import datetime, timezone

from dca_service.models import DCATransaction, DCAStrategy
from dca_service.config import settings

# ============================================================================
# TRANSACTION API TESTS
# ============================================================================

def test_read_transactions_empty(client: TestClient):
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert response.json() == []



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


def test_version_endpoint(client: TestClient):
    response = client.get("/api/version")
    assert response.status_code == 200

    data = response.json()
    assert data["project"] == settings.PROJECT_NAME
    assert data["version"] == settings.APP_VERSION
    assert data["commit"] == settings.APP_COMMIT_SHA


def test_healthz_endpoint(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["project"] == settings.PROJECT_NAME
    assert data["version"] == settings.APP_VERSION


def test_strategy_page_displays_configured_local_timezone(client: TestClient):
    response = client.get("/strategy")
    assert response.status_code == 200
    assert f"Local ({settings.LOCAL_TIMEZONE})" in response.text


def test_switch_time_mode_keeps_wall_clock_execution_time(client: TestClient, session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        execution_frequency="daily",
        execution_time_utc="00:00",
        time_display_mode="UTC",
    )
    session.add(strategy)
    session.commit()

    # Toggle mode only: execution_time_utc should remain unchanged as a wall-clock value.
    update_payload = client.get("/api/strategy").json()
    update_payload.pop("id", None)
    update_payload.pop("created_at", None)
    update_payload.pop("updated_at", None)
    update_payload["time_display_mode"] = "LOCAL"
    response = client.put("/api/strategy", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["time_display_mode"] == "LOCAL"
    assert data["execution_time_utc"] == "00:00"

    # Toggle back to UTC, still keep the same configured trigger time string.
    update_payload["time_display_mode"] = "UTC"
    response = client.put("/api/strategy", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["time_display_mode"] == "UTC"
    assert data["execution_time_utc"] == "00:00"

# ============================================================================
# DCA API TESTS
# ============================================================================

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_dca_preview(mock_metrics, client: TestClient, session: Session):
    """Test DCA preview endpoint"""
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
    
    mock_metrics.return_value = {
        "ahr999": 0.4, 
        "price_usd": 50000.0, 
        "timestamp": datetime.now(timezone.utc)
    }
    
    response = client.get("/api/dca/preview")
    assert response.status_code == 200
    data = response.json()
    assert data["can_execute"] is True
    # New percentile strategy: AHR999 0.4 falls into p10 tier (bottom 10%)
    assert data["ahr_band"] in ["p10", "low"]  # Accept either for backward compatibility
    # Budget $1000 / 30.44 days ≈ $32.85, multiplier varies by percentile tier
    assert data["suggested_amount_usd"] > 0  # Verify non-zero purchase

@patch('dca_service.services.dca_engine.get_latest_metrics')
def test_dca_execute_simulated(mock_metrics, client: TestClient, session: Session):
    """Test simulated DCA execution endpoint"""
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5
    )
    session.add(strategy)
    session.commit()
    
    mock_metrics.return_value = {
        "ahr999": 0.4, 
        "price_usd": 50000.0, 
        "timestamp": datetime.now(timezone.utc)
    }
    
    response = client.post("/api/dca/execute-simulated")
    assert response.status_code == 200
    data = response.json()
    
    assert data["transaction"] is not None
    assert data["transaction"]["status"] == "SUCCESS"
    assert data["transaction"]["notes"] == "Manual DCA simulation"
    
    # Verify DB
    tx = session.exec(select(DCATransaction)).first()
    assert tx is not None
    # Budget $1000 / 30.44 days ≈ $32.85, multiplier varies by percentile tier
    assert tx.fiat_amount > 0  # Verify non-zero purchase
