from fastapi.testclient import TestClient
from sqlmodel import Session
from unittest.mock import MagicMock, patch

from dca_service.api import stats_api
from dca_service.models import DCATransaction, SummaryApiSettings
from dca_service.services.security import encrypt_text
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
