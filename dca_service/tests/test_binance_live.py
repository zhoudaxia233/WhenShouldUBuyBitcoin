import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from sqlmodel import Session, SQLModel, create_engine, select
from datetime import datetime

from dca_service.models import DCAStrategy, BinanceCredentials, DCATransaction
from dca_service.scheduler import DCAScheduler
from dca_service.services.dca_engine import DCADecision

# Use in-memory DB for testing
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture
def mock_binance_client():
    # Patch the class where it is defined, so the local import in scheduler gets the mock
    with patch("dca_service.services.binance_client.BinanceClient") as MockClient:
        client_instance = MockClient.return_value
        # Mock async methods - scheduler uses execute_market_order_with_confirmation
        client_instance.execute_market_order_with_confirmation = AsyncMock(return_value={
            "order_id": 12345,
            "total_btc": 0.001,
            "avg_price": 50000.0,
            "quote_spent": 50.0,
            "total_fee": 0.0,
            "fee_asset": "USDC"
        })
        client_instance.close = AsyncMock()
        yield client_instance

@pytest.fixture
def mock_dca_decision():
    with patch("dca_service.scheduler.calculate_dca_decision") as mock:
        decision = DCADecision(
            can_execute=True,
            reason="Test",
            ahr999_value=0.5,
            price_usd=50000.0,
            ahr_band="cheap",
            multiplier=1.0,
            base_amount_usd=50.0,
            suggested_amount_usd=50.0,
            timestamp=datetime.now(),
            metrics_source={"backend": "mock", "label": "Test"}
        )
        mock.return_value = decision
        yield mock

@pytest.fixture
def mock_decrypt():
    with patch("dca_service.services.security.decrypt_text", return_value="secret_key") as mock:
        yield mock

def test_execute_dca_live_mode(session, mock_binance_client, mock_dca_decision, mock_decrypt):
    """Verify that LIVE mode triggers Binance client and records real transaction details"""
    
    # 1. Setup Data
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000,
        target_btc_amount=1.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        execution_frequency="daily",
        execution_time_utc="12:00",
        execution_mode="LIVE"  # <--- LIVE MODE
    )
    session.add(strategy)
    
    creds = BinanceCredentials(
        api_key_encrypted="encrypted_test_key",
        api_secret_encrypted="encrypted_secret",
        credential_type="TRADING"  # Required for LIVE mode
    )
    session.add(creds)
    session.commit()
    
    # 2. Execute
    scheduler = DCAScheduler()
    # We call _execute_dca directly to bypass time checks
    scheduler._execute_dca(strategy, session)
    
    # 3. Verify Binance Client Interaction
    mock_binance_client.execute_market_order_with_confirmation.assert_called_once()
    call_args = mock_binance_client.execute_market_order_with_confirmation.call_args
    assert call_args.kwargs["symbol"] == "BTCUSDC"
    assert call_args.kwargs["quote_quantity"] == 50.0
    mock_binance_client.close.assert_called_once()
    
    # 4. Verify Transaction Record
    tx = session.exec(select(DCATransaction)).first()
    assert tx is not None
    assert tx.source == "DCA"  # Changed from "BINANCE" to "DCA" for bot-triggered trades
    assert tx.executed_amount_usd == 50.0
    assert tx.executed_amount_btc == 0.001
    assert tx.status == "SUCCESS"
    assert "LIVE" in tx.notes or "Automated" in tx.notes

def test_execute_dca_dry_run_mode(session, mock_binance_client, mock_dca_decision):
    """Verify that DRY_RUN mode does NOT trigger Binance client"""
    
    # 1. Setup Data
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000,
        target_btc_amount=1.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        execution_frequency="daily",
        execution_time_utc="12:00",
        execution_mode="DRY_RUN"  # <--- DRY RUN
    )
    session.add(strategy)
    session.commit()
    
    # 2. Execute
    scheduler = DCAScheduler()
    scheduler._execute_dca(strategy, session)
    
    # 3. Verify Binance Client Interaction (Should NOT be called)
    mock_binance_client.create_market_buy_order.assert_not_called()
    
    # 4. Verify Transaction Record
    tx = session.exec(select(DCATransaction)).first()
    assert tx is not None
    assert tx.source == "SIMULATED"
    assert tx.executed_amount_usd == 50.0
    # In dry run, executed amount is calculated from price (50 / 50000 = 0.001)
    assert tx.executed_amount_btc == 0.001 
