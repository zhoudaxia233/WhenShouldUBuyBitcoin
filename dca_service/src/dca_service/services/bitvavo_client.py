import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from dca_service.core.logging import logger


class BitvavoClient:
    BASE_URL = "https://api.bitvavo.com/v2"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0)

    async def close(self):
        await self.client.aclose()

    def _headers(
        self,
        method: str,
        endpoint: str,
        params: Dict[str, Any],
        body: str,
    ) -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        query = f"?{urlencode(params)}" if params else ""
        payload = f"{timestamp}{method.upper()}{endpoint}{query}{body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Bitvavo-Access-Key": self.api_key,
            "Bitvavo-Access-Signature": signature,
            "Bitvavo-Access-Timestamp": timestamp,
            "Bitvavo-Access-Window": "10000",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        body_text = json.dumps(body or {}, separators=(",", ":")) if body else ""
        headers = self._headers(method, endpoint, params, body_text) if signed else {}
        request_kwargs: Dict[str, Any] = {"headers": headers}
        if params:
            request_kwargs["params"] = params
        if body is not None:
            request_kwargs["content"] = body_text

        response = await self.client.request(method, endpoint, **request_kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            try:
                error = e.response.json()
                message = error.get("error") or error.get("message") or str(e)
            except Exception:
                message = str(e)
            raise ValueError(f"Bitvavo API Error: {message}") from e
        return response.json()

    async def test_connection(self) -> bool:
        await self._request("GET", "/balance", signed=True)
        logger.info("Bitvavo connection test succeeded")
        return True

    async def test_trading_permission(self, symbol: str) -> bool:
        await self.test_connection()
        logger.info("Bitvavo trading permission basic auth test succeeded for %s", symbol)
        return True

    async def get_current_price(self, symbol: str) -> float:
        data = await self._request("GET", "/ticker/price", params={"market": symbol})
        if isinstance(data, list):
            data = data[0] if data else {}
        return float(data["price"])

    async def get_spot_balances(self, assets: list[str]) -> Dict[str, float]:
        data = await self._request("GET", "/balance", signed=True)
        balances = {asset: 0.0 for asset in assets}
        for item in data:
            asset = str(item.get("symbol") or "").upper()
            if asset in balances:
                balances[asset] = float(item.get("available", 0.0) or 0.0) + float(
                    item.get("inOrder", 0.0) or 0.0
                )
        return balances

    async def create_market_buy_order(self, symbol: str, quantity_quote: float) -> Dict[str, Any]:
        if quantity_quote <= 0:
            raise ValueError("Order amount must be positive")
        return await self._request(
            "POST",
            "/order",
            body={
                "market": symbol,
                "side": "buy",
                "orderType": "market",
                "amountQuote": f"{quantity_quote:.2f}",
            },
            signed=True,
        )

    async def execute_market_order_with_confirmation(
        self,
        symbol: str,
        quote_quantity: float,
        max_wait_seconds: int = 10,
        poll_interval: float = 1.0,
    ) -> Dict[str, Any]:
        order_response = await self.create_market_buy_order(symbol, quote_quantity)
        order_id = order_response.get("orderId")
        if not order_id:
            raise ValueError("Failed to retrieve Bitvavo order ID from order response")

        max_attempts = max(1, int(max_wait_seconds / poll_interval))
        trades = []
        for attempt in range(1, max_attempts + 1):
            trades = [
                trade
                for trade in await self.get_all_btc_trades(symbol)
                if str(trade.get("order_id")) == str(order_id)
            ]
            if trades:
                break
            if attempt < max_attempts:
                await asyncio.sleep(poll_interval)
        else:
            raise TimeoutError(f"Failed to retrieve Bitvavo trades for order {order_id}")

        total_btc = sum(float(trade.get("qty", 0.0)) for trade in trades)
        total_quote = sum(float(trade.get("quote_qty", 0.0)) for trade in trades)
        total_fee = sum(float(trade.get("commission", 0.0)) for trade in trades)
        avg_price = total_quote / total_btc if total_btc > 0 else 0.0
        return {
            "order_id": order_id,
            "trades": trades,
            "total_btc": total_btc,
            "avg_price": avg_price,
            "total_fee": total_fee,
            "fee_asset": trades[-1].get("commission_asset", "EUR") if trades else "EUR",
            "quote_spent": total_quote,
        }

    async def calculate_avg_buy_price(self, symbol: str) -> float:
        trades = await self.get_all_btc_trades(symbol)
        buys = [trade for trade in trades if trade.get("is_buyer")]
        total_btc = sum(float(trade.get("qty", 0.0)) for trade in buys)
        total_quote = sum(float(trade.get("quote_qty", 0.0)) for trade in buys)
        return total_quote / total_btc if total_btc > 0 else 0.0

    async def get_all_btc_trades(self, symbol: str = "BTC-EUR", limit: int = 1000):
        data = await self._request(
            "GET",
            "/trades",
            params={"market": symbol, "limit": limit},
            signed=True,
        )
        normalized = []
        for trade in data:
            qty = float(trade.get("amount", 0.0) or 0.0)
            price = float(trade.get("price", 0.0) or 0.0)
            quote_qty = float(trade.get("amountQuote", 0.0) or 0.0) or qty * price
            normalized.append(
                {
                    "id": str(trade.get("id") or ""),
                    "order_id": str(trade.get("orderId") or ""),
                    "time": _datetime_from_bitvavo(trade.get("timestamp")),
                    "price": price,
                    "qty": qty,
                    "quote_qty": quote_qty,
                    "commission": float(trade.get("fee", 0.0) or 0.0),
                    "commission_asset": str(trade.get("feeCurrency") or "EUR"),
                    "is_buyer": str(trade.get("side") or "").lower() == "buy",
                }
            )
        return normalized[:limit]


def _datetime_from_bitvavo(value: Any):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    return value
