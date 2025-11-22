import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlmodel import select
from dca_service.models import BinanceCredentials, DCAStrategy
from dca_service.services.security import encrypt_text, decrypt_text
from dca_service.config import settings

# Mock encryption key for tests
TEST_ENC_KEY = "gAAAAABj8..."  # Needs to be a valid fernet key?
# Fernet key must be 32 url-safe base64-encoded bytes.
# I'll generate one or use a fixed valid one.
VALID_FERNET_KEY = "C0XwX5X5X5X5X5X5X5X5X5X5X5X5X5X5X5X5X5X5X5U="
# Actually, let's just mock the settings object or set it directly if possible.
# Pydantic settings are mutable.


@pytest.fixture(autouse=True)
def set_test_settings():
    # Generate a valid key
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    with patch("dca_service.config.settings.BINANCE_CRED_ENC_KEY", key):
        yield


def test_encryption_decryption():
    original = "my_secret_key"
    encrypted = encrypt_text(original)
    assert encrypted != original
    decrypted = decrypt_text(encrypted)
    assert decrypted == original


def test_save_credentials(client, session):
    response = client.post(
        "/api/binance/credentials",
        json={"api_key": "test_key", "api_secret": "test_secret"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

    creds = session.exec(select(BinanceCredentials)).first()
    assert creds is not None
    assert creds.api_key_encrypted != "test_key"
    assert decrypt_text(creds.api_key_encrypted) == "test_key"


def test_get_credentials_status(client, session):
    # No creds
    response = client.get("/api/binance/credentials/status")
    assert response.status_code == 200
    assert response.json()["has_credentials"] is False

    # Add creds
    enc_key = encrypt_text("1234567890")
    enc_secret = encrypt_text("secret")
    session.add(
        BinanceCredentials(api_key_encrypted=enc_key, api_secret_encrypted=enc_secret)
    )
    session.commit()

    response = client.get("/api/binance/credentials/status")
    assert response.json()["has_credentials"] is True
    assert response.json()["masked_api_key"] == "1234****7890"


@patch("dca_service.services.binance_client.httpx.AsyncClient")
def test_test_connection_success(mock_client_cls, client, session):
    # Setup creds
    enc_key = encrypt_text("key")
    enc_secret = encrypt_text("secret")
    session.add(
        BinanceCredentials(api_key_encrypted=enc_key, api_secret_encrypted=enc_secret)
    )
    session.commit()

    # Mock client instance
    mock_instance = AsyncMock()
    mock_client_cls.return_value = mock_instance

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}
    mock_response.raise_for_status.return_value = None

    mock_instance.request.return_value = mock_response

    response = client.post("/api/binance/test-connection")
    assert response.status_code == 200
    assert response.json()["success"] is True


@patch("dca_service.services.binance_client.httpx.AsyncClient")
def test_get_holdings_success(mock_client_cls, client, session):
    # Setup creds and strategy
    enc_key = encrypt_text("key")
    enc_secret = encrypt_text("secret")
    session.add(
        BinanceCredentials(api_key_encrypted=enc_key, api_secret_encrypted=enc_secret)
    )
    session.add(
        DCAStrategy(
            target_btc_amount=1.0,
            total_budget_usd=1000.0,
            is_active=True,
            ahr999_multiplier_low=2.0,
            ahr999_multiplier_mid=1.0,
            ahr999_multiplier_high=0.5,
        )
    )
    session.commit()

    # Mock client
    mock_instance = AsyncMock()
    mock_client_cls.return_value = mock_instance

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "balances": [
            {"asset": "BTC", "free": "0.5", "locked": "0.0"},
            {"asset": "USDC", "free": "1000.0", "locked": "0.0"},
        ]
    }
    mock_response.raise_for_status.return_value = None

    mock_instance.request.return_value = mock_response

    response = client.get("/api/binance/holdings")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["btc_balance"] == 0.5
    assert data["quote_balance"] == 1000.0
    assert data["progress_ratio"] == 0.5


def test_get_holdings_no_creds(client):
    response = client.get("/api/binance/holdings")
    assert response.status_code == 200
    assert response.json()["connected"] is False
    assert response.json()["reason"] == "no_credentials"
