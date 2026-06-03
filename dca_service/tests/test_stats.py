from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import MagicMock, patch
import csv
import io

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


def test_stats_pnl_uses_effective_execution_fields_and_current_price_point(
    client: TestClient,
    session: Session,
):
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=100000.0,
        ahr999=0.5,
        notes="Live buy with legacy intent fields",
        timestamp=datetime.now(timezone.utc) - timedelta(days=2),
        executed_amount_usd=50.0,
        executed_amount_btc=0.001,
        avg_execution_price_usd=50000.0,
    )
    session.add(tx)
    session.commit()

    tx_day = tx.timestamp.date().isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    with patch(
        "dca_service.api.stats_api._build_market_price_series",
        return_value=([tx_day, today], [50000.0, 80000.0], [50000.0, 50000.0]),
    ):
        response = client.get("/api/stats/pnl")

    assert response.status_code == 200
    data = response.json()

    assert data["invested"][0] == 50.0
    assert data["value"][0] == 50.0
    assert data["avg_price"][0] == 50000.0
    assert data["prices"][0] == 50000.0
    assert data["purchase_usd"][0] == 50.0
    assert data["purchase_btc"][0] == 0.001

    assert data["performance_dates"] == [tx_day, today]
    assert data["performance_invested"][-1] == 50.0
    assert data["performance_value"][-1] == 80.0


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


def test_behavior_analysis_surfaces_amount_weighted_high_cost_exposure():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 10.0,
            "amount_btc": 0.0002,
            "avg_price_usd": 50000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        },
        {
            "event_key": "order:2",
            "event_type": "ORDER",
            "binance_order_id": 2,
            "timestamp": base_time + timedelta(days=1),
            "timestamp_end": base_time + timedelta(days=1),
            "fill_count": 1,
            "amount_usd": 1000.0,
            "amount_btc": 0.01,
            "avg_price_usd": 100000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [2],
            "trade_ids": [2],
        },
    ]
    for idx in range(10):
        ts = base_time + timedelta(days=2 + idx)
        events.append(
            {
                "event_key": f"order:{idx + 3}",
                "event_type": "ORDER",
                "binance_order_id": idx + 3,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 10.0,
                "amount_btc": 0.0002,
                "avg_price_usd": 50000.0,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "tx_ids": [idx + 3],
                "trade_ids": [idx + 3],
            }
        )

    analysis = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    summary = analysis["summary"]
    assert summary["low_zone_buy_ratio"] > summary["high_zone_buy_ratio"]
    assert summary["high_zone_usd_ratio"] > 0.85
    assert summary["low_zone_usd_ratio"] < 0.10
    assert summary["weighted_avg_buy_price_usd"] > 90000.0
    assert "High-cost Weighted" in analysis["style_tags"]
    assert any(item["title"] == "High-cost basis from larger high-zone buys" for item in analysis["issues"])


def test_purchase_csv_export_contains_order_level_purchase_rows(client: TestClient, session: Session):
    dca_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=25.0,
        btc_amount=0.0005,
        price=50000.0,
        ahr999=0.5,
        notes="Automated daily DCA",
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        source="DCA",
        is_manual=False,
        binance_order_id=123456,
        binance_trade_id=111,
        fee_amount=0.02,
        fee_asset="USDC",
        executed_amount_usd=25.0,
        executed_amount_btc=0.0005,
        avg_execution_price_usd=50000.0,
    )
    active_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.002,
        price=50020.0,
        ahr999=0.0,
        notes="Imported from Binance",
        timestamp=datetime(2024, 1, 3, 12, 30, tzinfo=timezone.utc),
        source="MANUAL",
        is_manual=True,
        binance_order_id=999999,
        binance_trade_id=113,
        fee_amount=0.05,
        fee_asset="USDC",
        executed_amount_usd=100.0,
        executed_amount_btc=0.002,
        avg_execution_price_usd=50020.0,
    )
    session.add(dca_tx)
    session.add(active_tx)
    session.commit()

    response = client.get("/api/stats/trading-style.csv?language=en")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="bitcoin-purchases.csv"' in response.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0].keys() == {
        "purchase_datetime",
        "purchase_type",
        "usd_spent",
        "btc_bought",
        "avg_price_usd",
        "fee_usd",
    }
    assert len(rows) == 2
    assert rows[0]["purchase_datetime"] == "2024-01-01T00:00:00+00:00"
    assert rows[0]["purchase_type"] == "DCA"
    assert rows[0]["usd_spent"] == "25.0"
    assert rows[0]["btc_bought"] == "0.0005"
    assert rows[1]["purchase_type"] == "ACTIVE_BUY"
    assert "asset" not in rows[0]
    assert "asset_type" not in rows[0]
    assert "fee_asset" not in rows[0]
    assert "style_tags" not in rows[0]
    assert "behavior_event_count" not in rows[0]
    assert "issues" not in rows[0]
    assert "source" not in rows[0]
    assert "fill_count" not in rows[0]
    assert "binance_order_id" not in rows[0]
    assert "binance_trade_ids" not in rows[0]
    assert "notes" not in rows[0]


def test_purchase_csv_export_merges_split_fills(client: TestClient, session: Session):
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
        fee_amount=0.01,
        fee_asset="USDC",
        executed_amount_usd=50.0,
        executed_amount_btc=0.001,
        avg_execution_price_usd=50000.0,
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
        fee_amount=0.03,
        fee_asset="USDC",
        executed_amount_usd=150.0,
        executed_amount_btc=0.003,
        avg_execution_price_usd=50010.0,
    )
    session.add(tx1)
    session.add(tx2)
    session.commit()

    response = client.get("/api/stats/trading-style.csv?language=en")

    assert response.status_code == 200

    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1
    assert rows[0]["purchase_datetime"] == "2024-01-01T00:00:00+00:00"
    assert rows[0]["usd_spent"] == "200.0"
    assert rows[0]["btc_bought"] == "0.004"
    assert float(rows[0]["avg_price_usd"]) == 50007.5
    assert rows[0]["fee_usd"] == "0.04"
    assert "fee_asset" not in rows[0]
    assert rows[0]["purchase_type"] == "ACTIVE_BUY"
    assert "fill_count" not in rows[0]
    assert "binance_order_id" not in rows[0]
    assert "binance_trade_ids" not in rows[0]


def test_purchase_csv_export_classifies_simulated_and_unknown_triggers(client: TestClient, session: Session):
    simulated_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=10.0,
        btc_amount=0.0002,
        price=50000.0,
        ahr999=0.5,
        notes="Manual DCA simulation",
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
        source="SIMULATED",
        is_manual=True,
    )
    unknown_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=20.0,
        btc_amount=0.0004,
        price=50000.0,
        ahr999=0.5,
        notes="External import",
        timestamp=datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc),
        source="LEDGER",
        is_manual=False,
    )
    session.add(simulated_tx)
    session.add(unknown_tx)
    session.commit()

    response = client.get("/api/stats/trading-style.csv?language=en")

    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["purchase_type"] for row in rows] == ["SIMULATED", "UNKNOWN"]


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
    assert first_payload["cache_ttl_seconds"] > first_payload["poll_recommendation_seconds"]
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
    assert "Strategy check:" in payload["guidance"]["analysis_text"]
    assert "Call:" not in payload["guidance"]["analysis_text"]
    assert "Do now:" in payload["guidance"]["analysis_text"]
    assert "Short reason:" in payload["guidance"]["analysis_text"]
    assert payload["guidance"]["method_constraints"]["no_hindsight"]


def test_add_position_advice_reports_cost_basis_impact():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 1000.0,
            "amount_btc": 0.01,
            "avg_price_usd": 100000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        },
        {
            "event_key": "order:2",
            "event_type": "ORDER",
            "binance_order_id": 2,
            "timestamp": base_time + timedelta(days=1),
            "timestamp_end": base_time + timedelta(days=1),
            "fill_count": 1,
            "amount_usd": 500.0,
            "amount_btc": 0.0071428571,
            "avg_price_usd": 70000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [2],
            "trade_ids": [2],
        },
    ]
    aggregate_meta = {
        "raw_fill_count": len(events),
        "event_count": len(events),
        "split_event_count": 0,
        "split_fill_extra_count": 0,
    }
    behavior_data = stats_api._build_behavior_analysis(events, aggregate_meta)

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=1000.0,
        current_price_usd=70000.0,
        market_context={
            "available": True,
            "is_stale": False,
            "is_double_undervalued": True,
            "ratio_dca_current": 0.95,
            "ratio_trend_current": 0.55,
            "current_vs_180d_low_pct": 5.0,
            "drop_24h_pct": -1.0,
        },
        macro_context={"available": False},
    )

    cost_basis = guidance["cost_basis_context"]
    assert cost_basis["current_avg_cost_usd"] > 87000.0
    assert cost_basis["proposed_avg_cost_after_buy_usd"] < cost_basis["current_avg_cost_usd"]
    assert cost_basis["proposed_avg_cost_delta_usd"] < 0
    assert "Cost basis:" in guidance["analysis_text"]


def test_add_position_advice_ignores_stale_market_and_macro_signals():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.001,
            "avg_price_usd": 100000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        }
    ]
    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": 1,
            "event_count": 1,
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=1000.0,
        current_price_usd=70000.0,
        market_context={
            "available": True,
            "is_stale": True,
            "metrics_as_of_date": "2026-03-15",
            "metrics_age_days": 72,
            "deep_value_regime": True,
            "is_double_undervalued": True,
            "ahr999": 0.42,
            "ahr999_sub_1": True,
            "ahr999_sub_07": True,
            "rsi14": 22.0,
            "is_rsi_bottoming_signal": True,
            "current_vs_180d_low_pct": 0.5,
            "drop_24h_pct": -9.0,
        },
        macro_context={
            "available": True,
            "is_stale": True,
            "report_age_days": 72,
            "macro_risk_score": 30.0,
            "stress_flags": 0,
            "net_liquidity_90d_delta": 120.0,
        },
    )

    assert guidance["data_freshness"]["market_context_usable"] is False
    assert guidance["data_freshness"]["macro_context_usable"] is False
    assert "stale" in guidance["analysis_text"].lower()
    assert "Technical bottoming:" not in guidance["analysis_text"]


def test_add_position_advice_exposes_practical_signal_context_for_easy_metrics():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.0011111111,
            "avg_price_usd": 90000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        },
        {
            "event_key": "order:2",
            "event_type": "ORDER",
            "binance_order_id": 2,
            "timestamp": base_time + timedelta(days=5),
            "timestamp_end": base_time + timedelta(days=5),
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.00125,
            "avg_price_usd": 80000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [2],
            "trade_ids": [2],
        },
    ]
    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=100.0,
        current_price_usd=76000.0,
        market_context={
            "available": True,
            "is_stale": False,
            "is_double_undervalued": False,
            "ratio_dca_current": 0.97,
            "ratio_trend_current": 0.57,
            "ahr999": 0.56,
            "ahr999_sub_1": True,
            "current_vs_180d_low_pct": 23.0,
            "current_vs_ath_pct": -38.0,
            "range_30d_pct": 8.8,
            "realized_vol_30d_pct": 1.3,
            "drop_24h_pct": -0.4,
        },
        macro_context={
            "available": True,
            "is_stale": False,
            "report_age_days": 1,
            "macro_risk_score": 31.0,
            "stress_flags": 0,
            "net_liquidity_90d_delta": 207.0,
            "ma_regime": "bearish",
            "ma_spread": -3468.0,
            "oi_percentile": 86.7,
            "oi_quadrant": "Squeeze Setup (crowded)",
        },
    )

    signals = guidance["practical_signal_context"]
    assert signals["valuation"]["bias"] == "supportive"
    assert signals["cost_basis"]["bias"] == "supportive"
    assert signals["macro"]["bias"] == "supportive"
    assert signals["trend"]["bias"] == "defensive"
    assert signals["leverage"]["bias"] == "defensive"
    assert "Practical signals:" in guidance["analysis_text"]


def test_add_position_advice_crowded_leverage_trims_size_and_raises_risk():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.0011111111,
            "avg_price_usd": 90000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        },
        {
            "event_key": "order:2",
            "event_type": "ORDER",
            "binance_order_id": 2,
            "timestamp": base_time + timedelta(days=5),
            "timestamp_end": base_time + timedelta(days=5),
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.00125,
            "avg_price_usd": 80000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [2],
            "trade_ids": [2],
        },
    ]
    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )
    market_context = {
        "available": True,
        "is_stale": False,
        "is_double_undervalued": False,
        "ratio_dca_current": 0.97,
        "ratio_trend_current": 0.57,
        "ahr999": 0.56,
        "ahr999_sub_1": True,
        "current_vs_180d_low_pct": 23.0,
        "drop_24h_pct": -0.4,
    }
    base_macro = {
        "available": True,
        "is_stale": False,
        "report_age_days": 1,
        "macro_risk_score": 31.0,
        "stress_flags": 0,
        "net_liquidity_90d_delta": 207.0,
        "ma_regime": "bearish",
        "ma_spread": -3468.0,
    }

    uncrowded = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=100.0,
        current_price_usd=76000.0,
        market_context=market_context,
        macro_context={**base_macro, "oi_percentile": 40.0, "oi_quadrant": "balanced"},
    )
    crowded = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=100.0,
        current_price_usd=76000.0,
        market_context=market_context,
        macro_context={**base_macro, "oi_percentile": 90.0, "oi_quadrant": "Squeeze Setup (crowded)"},
    )

    assert crowded["suggested_amount_usdc"] < uncrowded["suggested_amount_usdc"]
    assert crowded["risk_score"] > uncrowded["risk_score"]
    assert crowded["practical_signal_context"]["leverage"]["bias"] == "defensive"


def test_add_position_advice_deep_value_uses_wide_band_not_unlimited_planned_size():
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [
        {
            "event_key": "order:1",
            "event_type": "ORDER",
            "binance_order_id": 1,
            "timestamp": base_time,
            "timestamp_end": base_time,
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.0011111111,
            "avg_price_usd": 90000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [1],
            "trade_ids": [1],
        },
        {
            "event_key": "order:2",
            "event_type": "ORDER",
            "binance_order_id": 2,
            "timestamp": base_time + timedelta(days=5),
            "timestamp_end": base_time + timedelta(days=5),
            "fill_count": 1,
            "amount_usd": 100.0,
            "amount_btc": 0.00125,
            "avg_price_usd": 80000.0,
            "fee_usd": 0.0,
            "source_types": ["MANUAL"],
            "tx_ids": [2],
            "trade_ids": [2],
        },
    ]
    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )
    market_context = {
        "available": True,
        "is_stale": False,
        "is_double_undervalued": True,
        "ratio_dca_current": 0.97,
        "ratio_trend_current": 0.57,
        "ahr999": 0.56,
        "ahr999_sub_1": True,
        "current_vs_180d_low_pct": 23.0,
        "drop_24h_pct": -0.4,
    }
    macro_context = {
        "available": True,
        "is_stale": False,
        "report_age_days": 1,
        "macro_risk_score": 31.0,
        "stress_flags": 0,
        "net_liquidity_90d_delta": 207.0,
        "ma_regime": "bearish",
        "ma_spread": -3468.0,
    }

    small = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=50.0,
        current_price_usd=76000.0,
        market_context=market_context,
        macro_context=macro_context,
    )
    planned = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=250.0,
        current_price_usd=76000.0,
        market_context=market_context,
        macro_context=macro_context,
    )
    huge = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=3000.0,
        current_price_usd=76000.0,
        market_context=market_context,
        macro_context=macro_context,
    )

    assert small["action_code"] == "BUY_MORE"
    assert planned["action_code"] == "BUY_AS_PLANNED"
    assert huge["action_code"] == "BUY_LESS"
    assert huge["suggested_amount_usdc"] < huge["proposed_amount_usdc"]
    assert huge["input_alignment"] == "ABOVE_SUGGESTED"
    assert "\nApplied lesson:\n3. " in planned["analysis_text"]


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
    assert "Extra Buy confirmed after strategy check" in payload["transaction"]["notes"]
    assert "Add Position" not in payload["transaction"]["notes"]
    assert mock_email_task.call_count == 1


def test_add_position_confirm_ignores_fixed_dca_stop_price(client: TestClient, session: Session):
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        ahr999_multiplier_low=0.5,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=1.5,
        strategy_type="fixed_dca",
        fixed_dca_stop_price_usd=1.0,
        execution_mode="DRY_RUN",
    )
    session.add(strategy)
    session.commit()

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
    assert payload["transaction"]["source"] == "MANUAL"
    assert payload["transaction"]["is_manual"] is True
    assert payload["transaction"]["fiat_amount"] == 120.0
    assert payload["transaction"]["price"] == 60000.0
    assert "Extra Buy confirmed after strategy check" in payload["transaction"]["notes"]
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
    assert payload["transaction"]["source"] == "BINANCE"
    assert payload["transaction"]["is_manual"] is True
    assert payload["transaction"]["status"] == "SUCCESS"
    assert payload["transaction"]["binance_order_id"] == 99887766
    assert payload["transaction"]["executed_amount_btc"] == 0.00195
    assert payload["transaction"]["fee_amount"] == 0.04
    assert "Extra Buy confirmed after strategy check" in payload["transaction"]["notes"]
    assert "Add Position" not in payload["transaction"]["notes"]


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
    assert "strategy check: buy " in payload["guidance"]["analysis_text"].lower()


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


def test_add_position_advice_dense_active_buy_pressure_waits_without_drawdown_gate():
    now_utc = datetime.now(timezone.utc)
    events = []

    for idx in range(2):
        ts = now_utc - timedelta(days=13 - idx)
        events.append(
            {
                "event_key": f"order:dca-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 10_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 50.0,
                "amount_btc": 50.0 / 78_000.0,
                "avg_price_usd": 78_000.0,
                "fee_usd": 0.0,
                "source_types": ["DCA"],
                "tx_ids": [idx],
                "trade_ids": [idx],
            }
        )

    for idx in range(10):
        ts = now_utc - timedelta(days=9 - idx)
        events.append(
            {
                "event_key": f"order:active-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 20_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 200.0,
                "amount_btc": 200.0 / 90_000.0,
                "avg_price_usd": 90_000.0,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "tx_ids": [100 + idx],
                "trade_ids": [100 + idx],
            }
        )

    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=500.0,
        current_price_usd=86_000.0,
        market_context={
            "available": True,
            "is_stale": False,
            "is_double_undervalued": False,
            "ratio_dca_current": 1.05,
            "ratio_trend_current": 0.95,
            "ahr999": 1.05,
            "current_vs_180d_low_pct": 20.0,
            "current_vs_ath_pct": -18.0,
            "drop_24h_pct": -0.5,
            "range_30d_pct": 16.0,
            "realized_vol_30d_pct": 4.0,
            "sideways_30d": False,
        },
        macro_context={
            "available": True,
            "is_stale": False,
            "report_age_days": 1,
            "macro_risk_score": 45.0,
            "stress_flags": 1,
            "net_liquidity_90d_delta": 0.0,
            "oi_30d_change_pct": 0.0,
            "ma_regime": "neutral",
        },
    )

    assert guidance["decision"] == "WAIT"
    assert guidance["action_code"] == "NO_BUY"
    assert guidance["behavior_context"]["active_buy_discipline_mode"] is True
    assert guidance["behavior_context"]["active_buy_usd_ratio"] > 0.90
    assert guidance["behavior_context"]["active_buy_cost_premium_pct"] > 5.0
    assert "active buy" in guidance["call_reason"].lower()
    assert "15%" in guidance["analysis_text"]


def test_add_position_advice_three_active_buys_in_24h_waits_even_without_sideways_or_dca():
    now_utc = datetime.now(timezone.utc)
    events = []
    prices = [91_000.0, 89_500.0, 93_000.0, 88_000.0, 92_000.0, 87_500.0, 94_000.0, 86_500.0]
    for idx, price in enumerate(prices):
        ts = now_utc - timedelta(days=10 - idx)
        events.append(
            {
                "event_key": f"order:older-active-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 30_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 40.0,
                "amount_btc": 40.0 / price,
                "avg_price_usd": price,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "manual_flags": [True],
                "tx_ids": [300 + idx],
                "trade_ids": [300 + idx],
            }
        )

    for idx, (hours_ago, price) in enumerate([(20, 84_000.0), (11, 82_000.0), (4, 80_500.0)]):
        ts = now_utc - timedelta(hours=hours_ago)
        events.append(
            {
                "event_key": f"order:today-active-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 40_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 30.0,
                "amount_btc": 30.0 / price,
                "avg_price_usd": price,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "manual_flags": [True],
                "tx_ids": [400 + idx],
                "trade_ids": [400 + idx],
            }
        )

    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=50.0,
        current_price_usd=83_000.0,
        market_context={
            "available": True,
            "is_stale": False,
            "is_double_undervalued": False,
            "ratio_dca_current": 1.02,
            "ratio_trend_current": 0.90,
            "ahr999": 1.02,
            "current_vs_180d_low_pct": 18.0,
            "current_vs_ath_pct": -22.0,
            "drop_24h_pct": -1.0,
            "range_30d_pct": 18.0,
            "realized_vol_30d_pct": 5.0,
            "sideways_30d": False,
        },
        macro_context={
            "available": True,
            "is_stale": False,
            "report_age_days": 1,
            "macro_risk_score": 45.0,
            "stress_flags": 1,
            "net_liquidity_90d_delta": 0.0,
            "oi_30d_change_pct": 0.0,
            "ma_regime": "neutral",
        },
    )

    assert guidance["decision"] == "WAIT"
    assert guidance["action_code"] == "NO_BUY"
    assert guidance["behavior_context"]["recent_active_buy_events_24h"] == 3
    assert guidance["behavior_context"]["active_buy_intraday_cooldown_mode"] is True
    assert "3 active buys" in guidance["call_reason"]


def test_add_position_advice_three_active_buys_in_24h_overrides_value_mode_before_drawdown_gate():
    now_utc = datetime.now(timezone.utc)
    events = []
    for idx, (days_ago, price) in enumerate(
        [(10, 91_000.0), (9, 89_500.0), (8, 93_000.0), (7, 88_000.0), (6, 92_000.0), (5, 87_500.0), (4, 94_000.0), (3, 86_500.0)]
    ):
        ts = now_utc - timedelta(days=days_ago)
        events.append(
            {
                "event_key": f"order:older-value-active-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 50_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 40.0,
                "amount_btc": 40.0 / price,
                "avg_price_usd": price,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "manual_flags": [True],
                "tx_ids": [500 + idx],
                "trade_ids": [500 + idx],
            }
        )

    for idx, (hours_ago, price) in enumerate([(20, 84_000.0), (11, 82_000.0), (4, 80_500.0)]):
        ts = now_utc - timedelta(hours=hours_ago)
        events.append(
            {
                "event_key": f"order:today-value-active-{idx}",
                "event_type": "ORDER",
                "binance_order_id": 60_000 + idx,
                "timestamp": ts,
                "timestamp_end": ts,
                "fill_count": 1,
                "amount_usd": 30.0,
                "amount_btc": 30.0 / price,
                "avg_price_usd": price,
                "fee_usd": 0.0,
                "source_types": ["MANUAL"],
                "manual_flags": [True],
                "tx_ids": [600 + idx],
                "trade_ids": [600 + idx],
            }
        )

    behavior_data = stats_api._build_behavior_analysis(
        events,
        {
            "raw_fill_count": len(events),
            "event_count": len(events),
            "split_event_count": 0,
            "split_fill_extra_count": 0,
        },
    )

    guidance = stats_api._build_add_position_guidance(
        behavior_data=behavior_data,
        events=events,
        amount_usdc=50.0,
        current_price_usd=83_000.0,
        market_context={
            "available": True,
            "is_stale": False,
            "is_double_undervalued": True,
            "ratio_dca_current": 0.81,
            "ratio_trend_current": 0.56,
            "ahr999": 0.45,
            "current_vs_180d_low_pct": 17.0,
            "current_vs_ath_pct": -41.0,
            "drop_24h_pct": 0.8,
            "range_30d_pct": 13.6,
            "realized_vol_30d_pct": 4.0,
            "sideways_30d": False,
        },
        macro_context={
            "available": True,
            "is_stale": False,
            "report_age_days": 1,
            "macro_risk_score": 40.0,
            "stress_flags": 0,
            "net_liquidity_90d_delta": 132.0,
            "oi_30d_change_pct": 0.0,
            "ma_regime": "bearish",
        },
    )

    assert guidance["decision"] == "WAIT"
    assert guidance["action_code"] == "NO_BUY"
    assert guidance["behavior_context"]["active_buy_intraday_cooldown_mode"] is True
    assert guidance["behavior_context"]["active_buy_drawdown_gate"] is False
    assert "3 active buys" in guidance["call_reason"]


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
