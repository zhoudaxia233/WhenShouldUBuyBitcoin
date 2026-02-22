from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import MagicMock, patch

from dca_service.api import stats_api
from dca_service.models import DCATransaction, SummaryApiSettings, DCAStrategy, BinanceCredentials
from dca_service.services.security import encrypt_text
from datetime import datetime, timezone, timedelta

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


def test_trading_style_analysis_aggregates_split_fills(client: TestClient, session: Session):
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=50.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Split fill 1",
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=123456,
        binance_trade_id=111,
    )
    tx2 = DCATransaction(
        status="SUCCESS",
        fiat_amount=150.0,
        btc_amount=0.003,
        price=50010.0,
        ahr999=0.5,
        notes="Split fill 2",
        timestamp=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=123456,
        binance_trade_id=112,
    )
    tx3 = DCATransaction(
        status="SUCCESS",
        fiat_amount=200.0,
        btc_amount=0.004,
        price=50020.0,
        ahr999=0.5,
        notes="Another order",
        timestamp=datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=999999,
        binance_trade_id=113,
    )
    session.add(tx1)
    session.add(tx2)
    session.add(tx3)
    session.commit()

    response = client.get("/api/stats/trading-style?include_ai=false")
    assert response.status_code == 200
    payload = response.json()
    summary = payload["analysis_data"]["summary"]

    assert summary["raw_fill_count"] == 3
    assert summary["behavior_event_count"] == 2
    assert summary["split_event_count"] == 1
    assert summary["split_fill_extra_count"] == 1
    assert summary["avg_fills_per_event"] == 1.5
    assert payload["ai_analysis"] is None
    assert payload["ai_status"]["attempted"] is False

    diagnostics = payload["analysis_data"]["event_diagnostics"]
    assert len(diagnostics) == 2
    assert diagnostics[0]["binance_order_id"] == 123456
    assert diagnostics[0]["fill_count"] == 2
    assert diagnostics[0]["amount_usd"] == 200.0
    assert diagnostics[0]["amount_btc"] == 0.004
    assert diagnostics[1]["binance_order_id"] == 999999
    assert diagnostics[1]["fill_count"] == 1


def test_trading_style_analysis_ai_disabled_without_settings(client: TestClient, session: Session):
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.002,
        price=50000.0,
        ahr999=0.5,
        notes="No AI settings",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(tx)
    session.commit()

    response = client.get("/api/stats/trading-style?include_ai=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_analysis"] is None
    assert payload["ai_status"]["success"] is False
    assert "not configured" in payload["ai_status"]["reason"].lower()


def test_trading_style_analysis_ai_success(client: TestClient, session: Session):
    stats_api.TRADING_STYLE_AI_CACHE.clear()
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.002,
        price=50000.0,
        ahr999=0.5,
        notes="AI settings test",
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(tx)
    session.add(
        SummaryApiSettings(
            is_enabled=True,
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key_encrypted=encrypt_text("sk-test-key"),
        )
    )
    session.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "风格判断：偏固定节奏。主要问题：样本偏少。建议：保持一致执行。"
                }
            }
        ]
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    with patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client):
        response = client.get("/api/stats/trading-style?include_ai=true&language=zh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ai_status"]["attempted"] is True
    assert payload["ai_status"]["success"] is True
    assert payload["ai_status"]["language"] == "zh"
    assert payload["ai_status"]["cache_hit"] is False
    assert "风格判断" in payload["ai_analysis"]


def test_trading_style_analysis_reuses_cached_ai_when_source_unchanged(client: TestClient, session: Session):
    stats_api.TRADING_STYLE_AI_CACHE.clear()
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=300.0,
        btc_amount=0.006,
        price=50000.0,
        ahr999=0.5,
        notes="Cache test",
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    session.add(tx)
    session.add(
        SummaryApiSettings(
            is_enabled=True,
            provider="openai",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key_encrypted=encrypt_text("sk-test-key"),
        )
    )
    session.commit()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Style Assessment: steady."}}]
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    with patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client):
        first = client.get("/api/stats/trading-style?include_ai=true&language=en")
        second = client.get("/api/stats/trading-style?include_ai=true&language=en")

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()

    assert first_payload["ai_status"]["attempted"] is True
    assert first_payload["ai_status"]["cache_hit"] is False
    assert second_payload["ai_status"]["attempted"] is False
    assert second_payload["ai_status"]["cache_hit"] is True
    assert "Source unchanged" in second_payload["ai_status"]["reason"]
    assert second_payload["ai_analysis"] == first_payload["ai_analysis"]
    assert mock_client.post.call_count == 1


def test_realtime_price_endpoint_reuses_cache(client: TestClient):
    stats_api.BINANCE_PRICE_CACHE.clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"symbol": "BTCUSDC", "price": "50123.45"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client):
        first = client.get("/api/stats/realtime-price?symbol=BTCUSDC")
        second = client.get("/api/stats/realtime-price?symbol=BTCUSDC")

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()

    assert first_payload["cache_hit"] is False
    assert second_payload["cache_hit"] is True
    assert second_payload["price"] == first_payload["price"]
    assert second_payload["poll_recommendation_seconds"] == 3
    assert mock_client.get.call_count == 1


def test_add_position_advice_uses_split_fill_merged_behavior_events(client: TestClient, session: Session):
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=60.0,
        btc_amount=0.0012,
        price=50000.0,
        ahr999=0.5,
        notes="Split fill 1",
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=8080,
        binance_trade_id=1,
    )
    tx2 = DCATransaction(
        status="SUCCESS",
        fiat_amount=140.0,
        btc_amount=0.0028,
        price=50020.0,
        ahr999=0.5,
        notes="Split fill 2",
        timestamp=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=8080,
        binance_trade_id=2,
    )
    tx3 = DCATransaction(
        status="SUCCESS",
        fiat_amount=180.0,
        btc_amount=0.0035,
        price=51000.0,
        ahr999=0.6,
        notes="Standalone buy",
        timestamp=datetime(2024, 1, 4, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=9090,
        binance_trade_id=3,
    )
    session.add(tx1)
    session.add(tx2)
    session.add(tx3)
    session.commit()

    response = client.post(
        "/api/stats/add-position/advice",
        json={
            "amount_usdc": 220.0,
            "current_price_usd": 49500.0,
            "symbol": "BTCUSDC",
        },
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["input"]["amount_usdc"] == 220.0
    assert payload["input"]["current_price_usd"] == 49500.0
    assert payload["analysis_data"]["summary"]["raw_fill_count"] == 3
    assert payload["analysis_data"]["summary"]["behavior_event_count"] == 2
    assert payload["analysis_data"]["summary"]["split_event_count"] == 1
    assert payload["guidance"]["risk_level"] in {"low", "medium", "high"}
    assert payload["guidance"]["decision"] in {"BUY", "WAIT"}
    assert payload["guidance"]["action_code"] in {"NO_BUY", "BUY_LESS", "BUY_MORE", "BUY_AS_PLANNED"}
    assert payload["guidance"]["final_call"]
    assert payload["guidance"]["call_reason"]
    assert payload["guidance"]["analysis_text"]
    assert "Call:" in payload["guidance"]["analysis_text"]
    assert "Do now:" in payload["guidance"]["analysis_text"]
    assert "Short reason:" in payload["guidance"]["analysis_text"]
    assert payload["guidance"]["method_constraints"]["no_hindsight"]


def test_add_position_confirm_records_simulated_buy_transaction(client: TestClient, session: Session):
    with patch("dca_service.api.stats_api._send_add_position_email_task") as mock_email_task:
        response = client.post(
            "/api/stats/add-position/confirm",
            json={
                "amount_usdc": 120.0,
                "price_usd": 60000.0,
                "symbol": "BTCUSDC",
            },
        )
    assert response.status_code == 200
    payload = response.json()

    assert payload["success"] is True
    assert payload["transaction"]["status"] == "SUCCESS"
    assert payload["transaction"]["source"] == "MANUAL"
    assert payload["transaction"]["is_manual"] is True
    assert payload["transaction"]["fiat_amount"] == 120.0
    assert payload["transaction"]["price"] == 60000.0
    assert payload["transaction"]["btc_amount"] == 0.002
    assert mock_email_task.call_count == 1


def test_add_position_confirm_executes_live_mode_when_strategy_is_live(client: TestClient, session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5,
        execution_mode="LIVE",
    )
    creds = BinanceCredentials(
        credential_type="TRADING",
        api_key_encrypted=encrypt_text("live-key"),
        api_secret_encrypted=encrypt_text("live-secret"),
    )
    session.add(strategy)
    session.add(creds)
    session.commit()

    with patch("dca_service.api.stats_api._execute_live_add_position_order") as mock_exec:
        mock_exec.return_value = {
            "order_id": 99887766,
            "total_btc": 0.00195,
            "avg_price": 61538.46,
            "quote_spent": 120.0,
            "total_fee": 0.04,
            "fee_asset": "USDC",
        }
        response = client.post(
            "/api/stats/add-position/confirm",
            json={
                "amount_usdc": 120.0,
                "price_usd": 60000.0,
                "symbol": "BTCUSDC",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "LIVE"
    assert payload["transaction"]["source"] == "MANUAL"
    assert payload["transaction"]["is_manual"] is True
    assert payload["transaction"]["status"] == "SUCCESS"
    assert payload["transaction"]["binance_order_id"] == 99887766
    assert payload["transaction"]["executed_amount_btc"] == 0.00195
    assert payload["transaction"]["fee_amount"] == 0.04


def test_add_position_advice_deep_value_regime_does_not_auto_discourage_large_size(client: TestClient, session: Session):
    tx1 = DCATransaction(
        status="SUCCESS",
        fiat_amount=40.0,
        btc_amount=0.0008,
        price=50000.0,
        ahr999=0.5,
        notes="Baseline 1",
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
    )
    tx2 = DCATransaction(
        status="SUCCESS",
        fiat_amount=36.0,
        btc_amount=0.00072,
        price=50000.0,
        ahr999=0.5,
        notes="Baseline 2",
        timestamp=datetime(2024, 1, 3, 0, 0, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
    )
    session.add(tx1)
    session.add(tx2)
    session.commit()

    with patch("dca_service.api.stats_api._load_recent_market_context") as mock_market:
        mock_market.return_value = {
            "available": True,
            "window_days": 180,
            "low_180d": 60000.0,
            "high_180d": 100000.0,
            "current_vs_180d_low_pct": 0.5,
            "drop_24h_pct": -9.0,
            "near_180d_low": True,
            "new_180d_low": False,
            "deep_value_regime": True,
        }
        with patch("dca_service.api.stats_api._load_macro_context") as mock_macro:
            mock_macro.return_value = {
                "available": True,
                "report_date": "2026-02-08",
                "report_age_days": 1,
                "macro_risk_score": 30.0,
                "macro_risk_regime": "neutral",
                "stress_flags": 0,
                "net_liquidity_90d_delta": 80.0,
                "oi_30d_change_pct": -10.0,
                "ma_regime": "bearish",
                "ma_spread": -1000.0,
                "usdjpy_risk_level": "MODERATE RISK",
                "overall_summary": "test",
            }
            response = client.post(
                "/api/stats/add-position/advice",
                json={
                    "amount_usdc": 1000.0,
                    "current_price_usd": 60300.0,
                    "symbol": "BTCUSDC",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["guidance"]["market_context"]["deep_value_regime"] is True
    assert payload["guidance"]["macro_context"]["available"] is True
    assert payload["analysis_data"]["macro_context"]["available"] is True
    assert payload["guidance"]["decision"] == "BUY"
    assert payload["guidance"]["risk_level"] in {"low", "medium"}
    assert payload["guidance"]["final_call"].startswith("BUY ")
    assert "deep pullback zone" in payload["guidance"]["analysis_text"].lower()
    assert "call: buy " in payload["guidance"]["analysis_text"].lower()


def test_add_position_advice_sideways_dense_dca_waits_without_takeoff_macro(client: TestClient, session: Session):
    # Create dense DCA history: daily cadence, enough events to trigger dense mode.
    now_utc = datetime.now(timezone.utc)
    start_ts = now_utc - timedelta(days=11)
    for idx in range(12):
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=40.0 + (idx % 3),
            btc_amount=0.0007,
            price=68000.0,
            ahr999=0.6,
            notes=f"Dense DCA {idx}",
            timestamp=start_ts + timedelta(days=idx),
            source="MANUAL",
            is_manual=True,
        )
        session.add(tx)
    session.commit()

    with patch("dca_service.api.stats_api._load_recent_market_context") as mock_market:
        mock_market.return_value = {
            "available": True,
            "window_days": 180,
            "low_180d": 65000.0,
            "high_180d": 72000.0,
            "ath_price": 109000.0,
            "current_vs_180d_low_pct": 6.5,
            "current_vs_180d_high_pct": -3.0,
            "current_vs_ath_pct": -35.0,
            "drop_24h_pct": -0.4,
            "near_180d_low": False,
            "new_180d_low": False,
            "near_180d_high": False,
            "new_180d_high": False,
            "near_ath": False,
            "new_ath": False,
            "deep_value_regime": False,
            "breakout_high_regime": False,
            "range_30d_pct": 5.0,
            "realized_vol_30d_pct": 1.1,
            "sideways_30d": True,
        }
        with patch("dca_service.api.stats_api._load_macro_context") as mock_macro:
            mock_macro.return_value = {
                "available": True,
                "report_date": "2026-02-08",
                "report_age_days": 1,
                "macro_risk_score": 45.0,
                "macro_risk_regime": "neutral",
                "stress_flags": 0,
                "net_liquidity_90d_delta": 20.0,
                "oi_30d_change_pct": 0.0,
                "ma_regime": "bearish",
                "ma_spread": -1500.0,
                "usdjpy_risk_level": "MODERATE RISK",
                "overall_summary": "test",
            }
            response = client.post(
                "/api/stats/add-position/advice",
                json={
                    "amount_usdc": 700.0,
                    "current_price_usd": 69200.0,
                    "symbol": "BTCUSDC",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["guidance"]["decision"] == "WAIT"
    assert payload["guidance"]["final_call"] == "NO BUY"
    assert payload["guidance"]["action_code"] == "NO_BUY"
    assert "dense" in payload["guidance"]["call_reason"].lower()


def test_add_position_advice_sideways_dense_dca_allows_add_with_takeoff_macro(client: TestClient, session: Session):
    now_utc = datetime.now(timezone.utc)
    start_ts = now_utc - timedelta(days=11)
    for idx in range(12):
        tx = DCATransaction(
            status="SUCCESS",
            fiat_amount=45.0,
            btc_amount=0.00072,
            price=68000.0,
            ahr999=0.6,
            notes=f"Dense DCA takeoff {idx}",
            timestamp=start_ts + timedelta(days=idx),
            source="MANUAL",
            is_manual=True,
        )
        session.add(tx)
    session.commit()

    with patch("dca_service.api.stats_api._load_recent_market_context") as mock_market:
        mock_market.return_value = {
            "available": True,
            "window_days": 180,
            "low_180d": 65000.0,
            "high_180d": 72000.0,
            "ath_price": 109000.0,
            "current_vs_180d_low_pct": 7.0,
            "current_vs_180d_high_pct": -2.0,
            "current_vs_ath_pct": -34.0,
            "drop_24h_pct": 1.8,
            "near_180d_low": False,
            "new_180d_low": False,
            "near_180d_high": False,
            "new_180d_high": False,
            "near_ath": False,
            "new_ath": False,
            "deep_value_regime": False,
            "breakout_high_regime": True,
            "range_30d_pct": 6.0,
            "realized_vol_30d_pct": 1.4,
            "sideways_30d": True,
        }
        with patch("dca_service.api.stats_api._load_macro_context") as mock_macro:
            mock_macro.return_value = {
                "available": True,
                "report_date": "2026-02-08",
                "report_age_days": 1,
                "macro_risk_score": 38.0,
                "macro_risk_regime": "neutral",
                "stress_flags": 0,
                "net_liquidity_90d_delta": 120.0,
                "oi_30d_change_pct": 9.0,
                "ma_regime": "bullish",
                "ma_spread": 1800.0,
                "usdjpy_risk_level": "MODERATE RISK",
                "overall_summary": "test",
            }
            response = client.post(
                "/api/stats/add-position/advice",
                json={
                    "amount_usdc": 120.0,
                    "current_price_usd": 69400.0,
                    "symbol": "BTCUSDC",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["guidance"]["decision"] == "BUY"
    assert payload["guidance"]["final_call"].startswith("BUY")
    assert "macro takeoff signals are aligned" in payload["guidance"]["analysis_text"].lower()
