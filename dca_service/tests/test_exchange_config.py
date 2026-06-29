from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from dca_service.models import (
    DCAStrategy,
    DCATransaction,
    GlobalSettings,
    KrakenCredentials,
)
from dca_service.api import stats_api
from dca_service.api.wallet_api import fetch_wallet_summary
from dca_service.scheduler import DCAScheduler
from dca_service.services.dca_engine import DCADecision, calculate_dca_decision
from dca_service.services.kraken_client import KrakenClient
from dca_service.services.metrics_provider import RealtimeMetricsBackend
from dca_service.services.security import encrypt_text
from dca_service.services.sync_service import TradeSyncService


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "src" / "dca_service" / "templates"


def test_active_exchange_defaults_to_binance(client: TestClient):
    response = client.get("/api/exchange/active")

    assert response.status_code == 200
    assert response.json() == {"active_exchange": "BINANCE"}


def test_active_exchange_can_switch_to_kraken(client: TestClient, session: Session):
    response = client.post("/api/exchange/active", json={"active_exchange": "KRAKEN"})

    assert response.status_code == 200
    assert response.json() == {"success": True, "active_exchange": "KRAKEN"}
    assert session.get(GlobalSettings, 1).active_exchange == "KRAKEN"


def test_active_exchange_rejects_unknown_exchange(client: TestClient):
    response = client.post("/api/exchange/active", json={"active_exchange": "COINBASE"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported exchange"


def test_save_kraken_credentials(client: TestClient, session: Session):
    response = client.post(
        "/api/kraken/credentials",
        json={
            "api_key": "kraken-key",
            "api_secret": "kraken-secret",
            "credential_type": "READ_ONLY",
        },
    )

    assert response.status_code == 200
    creds = session.exec(select(KrakenCredentials)).first()
    assert creds is not None
    assert creds.api_key_encrypted != "kraken-key"

    status = client.get("/api/kraken/credentials/status?credential_type=READ_ONLY")
    assert status.status_code == 200
    assert status.json()["has_credentials"] is True
    assert status.json()["masked_api_key"] == "krak****-key"


def test_settings_page_exposes_active_exchange_and_kraken_credentials():
    html = (TEMPLATE_DIR / "binance_settings.html").read_text(encoding="utf-8")

    assert "<title>Exchange Settings</title>" in html
    assert 'id="activeExchangeSelect"' in html
    assert "/api/exchange/active" in html
    assert 'id="krakenForm"' in html
    assert "/api/kraken/credentials" in html


def test_strategy_page_checks_active_exchange_trading_status():
    html = (TEMPLATE_DIR / "strategy.html").read_text(encoding="utf-8")

    assert "/api/exchange/active" in html
    assert "/api/${activeExchange.toLowerCase()}/trading-status" in html
    assert "on your Binance account" not in html
    assert "Binance Spot wallet" not in html


def test_dashboard_quote_balance_label_uses_exchange_quote_asset():
    html = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="quoteBalanceLabel"' in html
    assert "updateQuoteBalanceUI(exchangeData)" in html
    assert "if (exchangeData.connected) window.updateQuoteBalanceUI(exchangeData)" not in html
    assert "Available ${quoteAsset}" in html


def test_kraken_client_public_ticker_uses_query_params():
    client = KrakenClient("key", base64.b64encode(b"secret").decode("ascii"))
    response = MagicMock()
    response.json.return_value = {
        "error": [],
        "result": {"XXBTZUSD": {"c": ["50000.0", "0.1"]}},
    }
    client.client.request = AsyncMock(return_value=response)

    price = asyncio.run(client.get_current_price("XBTUSD"))

    assert price == 50000.0
    client.client.request.assert_awaited_once_with(
        "GET",
        "/0/public/Ticker",
        params={"pair": "XBTUSD"},
        headers={},
    )


def test_kraken_client_matches_internal_trade_pair_names():
    client = KrakenClient("key", base64.b64encode(b"secret").decode("ascii"))
    client._request = AsyncMock(
        return_value={
            "trades": {
                "TRADE-1": {
                    "pair": "XXBTZUSD",
                    "type": "buy",
                    "ordertxid": "ORDER-1",
                    "time": 1782720000.0,
                    "price": "50000.0",
                    "vol": "0.01",
                    "cost": "500.0",
                    "fee": "0.5",
                }
            }
        }
    )

    avg_price = asyncio.run(client.calculate_avg_buy_price("XBTUSD"))
    trades = asyncio.run(client.get_all_btc_trades("XBTUSD"))

    assert avg_price == 50000.0
    assert len(trades) == 1
    assert trades[0]["id"] == "TRADE-1"
    assert trades[0]["order_id"] == "ORDER-1"


def test_dca_decision_uses_active_exchange_for_realtime_metrics(session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        DCAStrategy(
            is_active=True,
            total_budget_usd=1000,
            target_btc_amount=1.0,
            ahr999_multiplier_low=5.0,
            ahr999_multiplier_mid=2.0,
            ahr999_multiplier_high=0.0,
            execution_frequency="daily",
            execution_time_utc="12:00",
            execution_mode="DRY_RUN",
        )
    )
    session.commit()

    with patch("dca_service.services.dca_engine.get_latest_metrics") as mock_metrics:
        mock_metrics.return_value = {
            "ahr999": 0.5,
            "price_usd": 50000.0,
            "peak180": 60000.0,
            "timestamp": datetime.now(timezone.utc),
            "source": "realtime",
            "source_label": "Kraken",
        }

        calculate_dca_decision(session)

    mock_metrics.assert_called_once_with(active_exchange="KRAKEN")


def test_realtime_metrics_backend_labels_active_kraken_source():
    with patch("whenshouldubuybitcoin.realtime_check.check_realtime_status") as mock_check:
        mock_check.return_value = {
            "ahr999": 0.5,
            "realtime_price": 50000.0,
            "peak180": 60000.0,
            "timestamp": datetime.now(timezone.utc),
            "price_source": "kraken_public_api",
        }

        metrics = RealtimeMetricsBackend(active_exchange="KRAKEN").get_latest_metrics()

    mock_check.assert_called_once_with(verbose=False, exchange="KRAKEN")
    assert metrics.source.backend == "realtime"
    assert metrics.source.label == "Kraken"


def test_realtime_price_uses_active_kraken_source(client: TestClient, session: Session):
    stats_api.BINANCE_PRICE_CACHE.clear()
    session.get(GlobalSettings, 1).active_exchange = "KRAKEN"
    session.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "XXBTZUSD": {
                "c": ["50123.45", "0.01"],
            }
        }
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client):
        response = client.get("/api/stats/realtime-price?symbol=BTCUSDC")

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_exchange"] == "KRAKEN"
    assert payload["source"] == "kraken_public_api"
    assert payload["exchange_symbol"] == "XBTUSD"
    assert payload["price"] == 50123.45


def test_realtime_price_marks_coinbase_fallback(client: TestClient, session: Session):
    stats_api.BINANCE_PRICE_CACHE.clear()
    session.get(GlobalSettings, 1).active_exchange = "KRAKEN"
    session.commit()

    kraken_response = MagicMock()
    kraken_response.status_code = 503
    kraken_response.text = "maintenance"
    kraken_response.json.return_value = {"error": ["maintenance"]}

    coinbase_response = MagicMock()
    coinbase_response.status_code = 200
    coinbase_response.json.return_value = {"data": {"rates": {"USD": "50199.99"}}}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.side_effect = [kraken_response, coinbase_response]

    with patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client):
        response = client.get("/api/stats/realtime-price?symbol=BTCUSDC")

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_exchange"] == "KRAKEN"
    assert payload["source"] == "coinbase_public_api"
    assert payload["exchange_symbol"] == "BTC-USD"
    assert payload["coinbase_fallback"] is True


def test_kraken_live_dca_uses_kraken_client(session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000,
        target_btc_amount=1.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        execution_frequency="daily",
        execution_time_utc="12:00",
        execution_mode="LIVE",
    )
    session.add(strategy)
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="TRADING",
        )
    )
    session.commit()

    decision = DCADecision(
        can_execute=True,
        reason="Test",
        ahr999_value=0.5,
        price_usd=50000.0,
        ahr_band="cheap",
        multiplier=1.0,
        base_amount_usd=50.0,
        suggested_amount_usd=50.0,
        timestamp=strategy.updated_at,
        metrics_source={"backend": "mock", "label": "Test"},
    )

    with (
        patch("dca_service.scheduler.calculate_dca_decision", return_value=decision),
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
        patch("dca_service.services.binance_client.BinanceClient") as binance_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.execute_market_order_with_confirmation = AsyncMock(
            return_value={
                "order_id": "KRAKEN-ORDER",
                "trades": [{"id": "KRAKEN-TRADE"}],
                "total_btc": 0.001,
                "avg_price": 50000.0,
                "quote_spent": 50.0,
                "total_fee": 0.0,
                "fee_asset": "USD",
            }
        )
        kraken_client.close = AsyncMock()

        DCAScheduler()._execute_dca(strategy, session)

    kraken_client.execute_market_order_with_confirmation.assert_called_once()
    binance_client_class.assert_not_called()

    tx = session.exec(select(DCATransaction)).first()
    assert tx.source == "DCA"
    assert tx.exchange == "KRAKEN"
    assert tx.exchange_order_id == "KRAKEN-ORDER"
    assert tx.exchange_symbol == "XBTUSD"


def test_kraken_live_dca_failure_records_kraken_source(session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000,
        target_btc_amount=1.0,
        ahr999_multiplier_low=5.0,
        ahr999_multiplier_mid=2.0,
        ahr999_multiplier_high=0.0,
        execution_frequency="daily",
        execution_time_utc="12:00",
        execution_mode="LIVE",
    )
    session.add(strategy)
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="TRADING",
        )
    )
    session.commit()

    decision = DCADecision(
        can_execute=True,
        reason="Test",
        ahr999_value=0.5,
        price_usd=50000.0,
        ahr_band="cheap",
        multiplier=1.0,
        base_amount_usd=50.0,
        suggested_amount_usd=50.0,
        timestamp=strategy.updated_at,
        metrics_source={"backend": "mock", "label": "Test"},
    )

    with (
        patch("dca_service.scheduler.calculate_dca_decision", return_value=decision),
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.execute_market_order_with_confirmation = AsyncMock(
            side_effect=Exception("Kraken trading error")
        )
        kraken_client.close = AsyncMock()

        DCAScheduler()._execute_dca(strategy, session)

    tx = session.exec(select(DCATransaction)).first()
    assert tx.status == "FAILED"
    assert tx.source == "KRAKEN_FAILED"
    assert tx.exchange == "KRAKEN"
    assert tx.exchange_symbol == "XBTUSD"


def test_wallet_summary_uses_active_kraken_client(session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="READ_ONLY",
        )
    )
    session.commit()

    with (
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
        patch("dca_service.services.binance_client.BinanceClient") as binance_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.get_spot_balances = AsyncMock(return_value={"BTC": 0.25})
        kraken_client.get_current_price = AsyncMock(return_value=50000.0)
        kraken_client.calculate_avg_buy_price = AsyncMock(return_value=42000.0)
        kraken_client.close = AsyncMock()

        summary = asyncio.run(fetch_wallet_summary(session))

    binance_client_class.assert_not_called()
    kraken_client.get_spot_balances.assert_called_once_with(["BTC"])
    kraken_client.get_current_price.assert_called_once_with("XBTUSD")
    assert summary.hot_wallet_balance == 0.25
    assert summary.current_price == 50000.0
    assert summary.hot_wallet_avg_price == 42000.0


def test_exchange_holdings_uses_active_kraken(client: TestClient, session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="READ_ONLY",
        )
    )
    session.commit()

    with (
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
        patch("dca_service.services.binance_client.BinanceClient") as binance_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.get_spot_balances = AsyncMock(return_value={"BTC": 0.25, "USD": 1000.0})
        kraken_client.close = AsyncMock()

        response = client.get("/api/exchange/holdings")

    binance_client_class.assert_not_called()
    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is True
    assert payload["exchange"] == "KRAKEN"
    assert payload["quote_asset"] == "USD"
    assert payload["quote_balance"] == 1000.0


def test_exchange_holdings_sanitizes_active_exchange_error(client: TestClient, session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="READ_ONLY",
        )
    )
    session.commit()

    with patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class:
        kraken_client = kraken_client_class.return_value
        kraken_client.get_spot_balances = AsyncMock(
            side_effect=RuntimeError("secret stack trace from provider")
        )
        kraken_client.close = AsyncMock()

        response = client.get("/api/exchange/holdings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected"] is False
    assert payload["reason"] == "api_error"


def test_kraken_connection_test_sanitizes_provider_errors(client: TestClient, session: Session):
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="READ_ONLY",
        )
    )
    session.commit()

    with patch("dca_service.api.kraken_api.KrakenClient") as kraken_client_class:
        kraken_client = kraken_client_class.return_value
        kraken_client.test_connection = AsyncMock(
            side_effect=RuntimeError("secret stack trace from provider")
        )
        kraken_client.close = AsyncMock()

        response = client.post("/api/kraken/test-connection?credential_type=READ_ONLY")

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error_message": "Kraken connection test failed",
    }


def test_kraken_trading_status_verifies_add_order_permission(client: TestClient, session: Session):
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="TRADING",
        )
    )
    session.commit()

    with patch("dca_service.api.kraken_api.KrakenClient") as kraken_client_class:
        kraken_client = kraken_client_class.return_value
        kraken_client.test_connection = AsyncMock(return_value=True)
        kraken_client.test_trading_permission = AsyncMock(return_value=True)
        kraken_client.close = AsyncMock()

        response = client.get("/api/kraken/trading-status")

    assert response.status_code == 200
    assert response.json()["can_enable_live"] is True
    kraken_client.test_connection.assert_called_once_with()
    kraken_client.test_trading_permission.assert_called_once_with("XBTUSD")


def test_wallet_summary_fallback_uses_active_kraken_price_source(session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.commit()

    with (
        patch(
            "whenshouldubuybitcoin.data_fetcher.get_realtime_btc_price_with_source",
            return_value=(datetime.now(timezone.utc), 50123.0, "kraken_public_api"),
        ) as source_price,
        patch(
            "whenshouldubuybitcoin.data_fetcher.get_realtime_btc_price",
            return_value=(datetime.now(timezone.utc), 49000.0),
        ) as legacy_price,
    ):
        summary = asyncio.run(fetch_wallet_summary(session))

    source_price.assert_called_once_with("KRAKEN")
    legacy_price.assert_not_called()
    assert summary.current_price == 50123.0


def test_add_position_live_order_uses_active_kraken(session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="TRADING",
        )
    )
    session.commit()

    with (
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
        patch("dca_service.services.binance_client.BinanceClient") as binance_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.execute_market_order_with_confirmation = AsyncMock(
            return_value={
                "order_id": "KRAKEN-ADD",
                "trades": [{"id": "KRAKEN-FILL"}],
                "total_btc": 0.002,
                "avg_price": 50000.0,
                "quote_spent": 100.0,
                "total_fee": 0.1,
                "fee_asset": "USD",
            }
        )
        kraken_client.close = AsyncMock()

        result = stats_api._execute_live_add_position_order(
            session,
            symbol="BTCUSDC",
            amount_usdc=100.0,
        )

    binance_client_class.assert_not_called()
    kraken_client.execute_market_order_with_confirmation.assert_called_once()
    assert result["order_id"] == "KRAKEN-ADD"
    assert result["exchange"] == "KRAKEN"
    assert result["exchange_symbol"] == "XBTUSD"


def test_sync_trades_imports_active_kraken_buy(session: Session):
    settings = session.get(GlobalSettings, 1)
    settings.active_exchange = "KRAKEN"
    session.add(settings)
    session.add(
        KrakenCredentials(
            api_key_encrypted=encrypt_text("kraken-key"),
            api_secret_encrypted=encrypt_text("kraken-secret"),
            credential_type="READ_ONLY",
        )
    )
    session.commit()

    trade_time = datetime(2026, 6, 29, tzinfo=timezone.utc)
    with (
        patch("dca_service.services.kraken_client.KrakenClient") as kraken_client_class,
        patch("dca_service.services.binance_client.BinanceClient") as binance_client_class,
    ):
        kraken_client = kraken_client_class.return_value
        kraken_client.get_all_btc_trades = AsyncMock(
            return_value=[
                {
                    "id": "KRAKEN-TRADE",
                    "order_id": "KRAKEN-ORDER",
                    "time": trade_time,
                    "price": 50000.0,
                    "qty": 0.001,
                    "quote_qty": 50.0,
                    "commission": 0.05,
                    "commission_asset": "USD",
                    "is_buyer": True,
                }
            ]
        )
        kraken_client.close = AsyncMock()

        added = asyncio.run(TradeSyncService(session).sync_trades())

    binance_client_class.assert_not_called()
    assert added == 1
    tx = session.exec(select(DCATransaction)).first()
    assert tx.source == "MANUAL"
    assert tx.exchange == "KRAKEN"
    assert tx.exchange_order_id == "KRAKEN-ORDER"
    assert tx.exchange_trade_id == "KRAKEN-TRADE"
