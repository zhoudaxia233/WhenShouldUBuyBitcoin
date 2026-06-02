from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from dca_service import main
from dca_service.api import stats_api


def test_realtime_price_success_request_is_not_info_logged(client: TestClient):
    stats_api.BINANCE_PRICE_CACHE.clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"symbol": "BTCUSDC", "price": "50123.45"}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with (
        patch("dca_service.api.stats_api.httpx.Client", return_value=mock_client),
        patch.object(main.logger, "info") as mock_info,
    ):
        response = client.get("/api/stats/realtime-price?symbol=BTCUSDC")

    assert response.status_code == 200
    request_log_messages = [
        str(call.args[0])
        for call in mock_info.call_args_list
        if call.args
    ]
    assert not any("GET /api/stats/realtime-price" in message for message in request_log_messages)


def test_request_log_filter_keeps_errors_and_slow_price_requests():
    assert main._should_log_request("/api/stats/realtime-price", 200, 999.99) is False
    assert main._should_log_request("/api/stats/realtime-price", 200, 1000.01) is True
    assert main._should_log_request("/api/stats/realtime-price", 502, 5.0) is True
    assert main._should_log_request("/api/strategy", 200, 5.0) is True
