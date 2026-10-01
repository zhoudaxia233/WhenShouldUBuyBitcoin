"""Tests for placing a LIVE market order and confirming its fills."""
import asyncio

import pytest

from dca_service.services.binance_client import BinanceClient, OrderStatusUnknownError


FILL = {"qty": "0.002", "quoteQty": "100.0", "commission": "0.000002", "commissionAsset": "BTC"}


class FakeBinance:
    """Replaces BinanceClient._request with scripted responses per endpoint."""

    def __init__(self, order_post=None, order_lookup=None, trades=None):
        self.order_post = order_post
        self.order_lookup = order_lookup
        self.trades = trades if trades is not None else [FILL]
        self.calls = []

    async def __call__(self, method, endpoint, params=None, signed=False):
        self.calls.append((method, endpoint, dict(params or {})))
        if (method, endpoint) == ("POST", "/api/v3/order"):
            return self._answer(self.order_post)
        if (method, endpoint) == ("GET", "/api/v3/order"):
            return self._answer(self.order_lookup)
        if (method, endpoint) == ("GET", "/api/v3/myTrades"):
            return self.trades
        raise AssertionError(f"Unexpected request {method} {endpoint}")

    @staticmethod
    def _answer(value):
        if isinstance(value, Exception):
            raise value
        return value

    def posted_client_order_id(self):
        posts = [p for m, e, p in self.calls if (m, e) == ("POST", "/api/v3/order")]
        assert len(posts) == 1
        return posts[0]["newClientOrderId"]


@pytest.fixture
def client():
    c = BinanceClient("key", "secret")
    yield c
    asyncio.run(c.close())


def execute(client, fake):
    client._request = fake
    return asyncio.run(client.execute_market_order_with_confirmation(
        symbol="BTCUSDC", quote_quantity=100.0, max_wait_seconds=1, poll_interval=1.0
    ))


def test_order_is_placed_with_client_order_id(client):
    fake = FakeBinance(order_post={"orderId": 7})

    result = execute(client, fake)

    assert result["order_id"] == 7
    assert fake.posted_client_order_id().startswith("dca-")


def test_placement_error_but_order_exists_is_confirmed(client):
    fake = FakeBinance(
        order_post=ValueError("Network Error: read timeout"),
        order_lookup={"orderId": 8, "status": "FILLED"},
    )

    result = execute(client, fake)

    assert result["order_id"] == 8
    assert result["total_btc"] == pytest.approx(0.002)
    lookups = [p for m, e, p in fake.calls if (m, e) == ("GET", "/api/v3/order")]
    assert lookups[0]["origClientOrderId"] == fake.posted_client_order_id()


def test_placement_error_and_order_absent_raises_original_error(client):
    fake = FakeBinance(
        order_post=ValueError("Binance API Error -2010: Account has insufficient balance"),
        order_lookup=ValueError("Binance API Error -2013: Order does not exist."),
    )

    with pytest.raises(ValueError, match="insufficient balance"):
        execute(client, fake)


def test_placement_error_and_lookup_error_is_unknown(client):
    fake = FakeBinance(
        order_post=ValueError("Network Error: read timeout"),
        order_lookup=ValueError("Network Error: connection reset"),
    )

    with pytest.raises(OrderStatusUnknownError):
        execute(client, fake)


def test_placed_order_without_visible_fills_is_unknown(client):
    fake = FakeBinance(order_post={"orderId": 9}, trades=[])

    with pytest.raises(OrderStatusUnknownError) as exc_info:
        execute(client, fake)

    assert exc_info.value.order_id == 9
