import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from dca_service.main import app
from dca_service.database import get_session
from dca_service.models import GlobalSettings, User
from dca_service.auth.dependencies import get_current_user

@pytest.fixture(name="client")
def client_fixture():
    # Create fresh DB for each test
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    
    def get_session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_session_override
    
    # Seed DB with settings and test user
    with Session(engine) as session:
        settings = GlobalSettings(id=1, cold_wallet_balance=1.5)
        session.add(settings)
        
        # Create test user for authentication bypass
        from dca_service.auth.password import hash_password
        test_user = User(
            id=1,
            email="test@example.com",
            password_hash=hash_password("testpassword123"),
            is_active=True,
            is_admin=True
        )
        session.add(test_user)
        session.commit()
        
    # Override authentication to bypass login
    test_user_obj = User(
        id=1,
        email="test@example.com", 
        password_hash="test_hash",
        is_active=True,
        is_admin=True
    )
    
    def get_current_user_override():
        return test_user_obj
    
    app.dependency_overrides[get_current_user] = get_current_user_override
        
    yield TestClient(app)
    
    # Cleanup
    SQLModel.metadata.drop_all(engine)
    app.dependency_overrides.clear()

def test_percentile_api_resilience(client):
    """
    Test that the percentile API returns 200 OK and total_btc even if
    the distribution scraper fails (simulating the Vultr blocking issue).
    """
    # Mock the scraper to raise ValueError
    with patch("dca_service.services.distribution_scraper.fetch_distribution") as mock_fetch:
        mock_fetch.side_effect = ValueError("Scraper blocked!")
        
        # Mock wallet summary to return a known BTC amount
        with patch("dca_service.api.wallet_api.get_wallet_summary") as mock_wallet:
            mock_wallet.return_value = MagicMock(total_btc=1.5)
            
            response = client.get("/api/stats/percentile")
            
            # Should be 200 OK, not 503
            assert response.status_code == 200
            
            data = response.json()
            
            # Should contain total_btc
            assert data["total_btc"] == 1.5
            
            # Should indicate data unavailability
            assert data["percentile_top"] is None
            assert data["percentile_display"] == "Data Unavailable"
            assert "unavailable" in data["message"].lower()

def test_percentile_api_success(client):
    """Test happy path when scraper works."""
    with patch("dca_service.services.distribution_scraper.fetch_distribution") as mock_fetch:
        # Mock successful distribution data
        mock_fetch.return_value = [
            {"tier": "100+", "percentile": "Top 0.01%"},
            {"tier": "1-10", "percentile": "Top 2%"},
        ]
        
        with patch("dca_service.api.wallet_api.get_wallet_summary") as mock_wallet:
            mock_wallet.return_value = MagicMock(total_btc=1.5)
            
            response = client.get("/api/stats/percentile")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_btc"] == 1.5
            assert data["percentile_display"] == "Top 2%"
