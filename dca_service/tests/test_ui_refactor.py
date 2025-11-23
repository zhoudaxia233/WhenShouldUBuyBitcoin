"""
Tests for UI refactor regression prevention.
Ensures the Binance settings refactor bugs don't come back.
"""
import pytest
from fastapi.testclient import TestClient


def test_binance_settings_route_exists(client: TestClient):
    """Ensure /settings/binance route exists after refactor"""
    response = client.get("/settings/binance")
    assert response.status_code == 200
    assert b"Binance Settings" in response.content


def test_binance_credentials_status_api_fields(client: TestClient):
    """
    REGRESSION TEST: Ensure API returns correct field names.
    Bug: binance_settings.html was checking for keys_stored/api_key_preview
    but API returns has_credentials/masked_api_key
    """
    response = client.get("/api/binance/credentials/status")
    assert response.status_code == 200
    data = response.json()
    
    # API must return these fields, not the old field names
    assert "has_credentials" in data
    if data["has_credentials"]:
        assert "masked_api_key" in data
    
    # Old field names should NOT be present
    assert "keys_stored" not in data
    assert "api_key_preview" not in data


def test_dashboard_has_binance_settings_button(client: TestClient):
    """Ensure dashboard has navigation to Binance settings"""
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode('utf-8')
    
    # Button should exist in header
    assert "/settings/binance" in content
    assert "Binance Settings" in content


def test_dashboard_no_binance_connection_card(client: TestClient):
    """
    REGRESSION TEST: Ensure Binance Connection card was removed from dashboard.
    Bug: Old UI had the entire Binance form on main dashboard
    """
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode('utf-8')
    
    # These elements should NOT be on the dashboard anymore
    assert "binanceForm" not in content
    assert "testConnectionBtn" not in content
    # Old inline credential inputs should be gone
    assert 'id="apiKey"' not in content
    assert 'id="apiSecret"' not in content


def test_dashboard_transaction_table_has_bottom_margin(client: TestClient):
    """
    REGRESSION TEST: Transaction table should have bottom margin.
    Bug: Table was touching the footer with no spacing
    """
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode('utf-8')
    
    # Transaction History card should have mb-5 class
    # Look for the card that contains "Transaction History"
    assert 'class="card shadow-sm mb-5"' in content or 'shadow-sm mb-5' in content


def test_dashboard_loads_holdings_on_page_load(client: TestClient):
    """
    REGRESSION TEST: Dashboard should call loadHoldings() on page load.
    Bug: Holdings section was empty because loadHoldings() wasn't being called,
    and loadBinanceStatus() (which was deleted) was still being called.
    """
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode('utf-8')
    
    # loadHoldings() function must exist
    assert "async function loadHoldings()" in content or "function loadHoldings()" in content
    
    # It must be called on page load
    assert "loadHoldings();" in content
    
    # Old function loadBinanceStatus() should NOT be called anymore
    assert "loadBinanceStatus();" not in content


def test_binance_settings_page_loads_credentials_on_start(client: TestClient):
    """
    REGRESSION TEST: Binance settings page should load credentials status.
    Bug: Page wasn't calling loadCredentialsStatus() on page load
    """
    response = client.get("/settings/binance")
    assert response.status_code == 200
    content = response.content.decode('utf-8')
    
    # loadCredentialsStatus() function must exist
    assert "loadCredentialsStatus" in content
    
    # It must be called on page load
    assert "loadCredentialsStatus();" in content
