import asyncio
import base64
import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from dca_service.core.logging import logger


class KrakenClient:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0)

    async def close(self):
        await self.client.aclose()

    def _headers(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, str]:
        postdata = urlencode(params)
        encoded = (str(params["nonce"]) + postdata).encode("utf-8")
        message = endpoint.encode("utf-8") + hashlib.sha256(encoded).digest()
        secret = base64.b64decode(self.api_secret)
        signature = hmac.new(secret, message, hashlib.sha512)
        return {
            "API-Key": self.api_key,
            "API-Sign": base64.b64encode(signature.digest()).decode("ascii"),
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        params = dict(params or {})
        headers = {}
        if signed:
            params["nonce"] = int(time.time() * 1000)
            headers = self._headers(endpoint, params)

        request_kwargs = {"headers": headers}
        if method.upper() == "GET":
            request_kwargs["params"] = params
        else:
            request_kwargs["data"] = params

        response = await self.client.request(method, endpoint, **request_kwargs)
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("error") or []
        if errors:
            raise ValueError(f"Kraken API Error: {'; '.join(map(str, errors))}")
        return payload.get("result") or {}

    async def test_connection(self) -> bool:
        await self._request("POST", "/0/private/Balance", signed=True)
        logger.info("Kraken connection test succeeded")
        return True

    async def test_trading_permission(self, symbol: str) -> bool:
        await self._request(
            "POST",
            "/0/private/AddOrder",
            params={
                "pair": symbol,
                "type": "buy",
                "ordertype": "market",
                "volume": "1.00",
                "oflags": "viqc",
                "validate": "true",
            },
            signed=True,
        )
        logger.info("Kraken trading permission test succeeded")
        return True

    @staticmethod
    def _asset_code(asset: str) -> str:
        asset = asset.upper()
        if asset == "BTC":
            return "XXBT"
        if asset == "USD":
            return "ZUSD"
        return asset

    @staticmethod
    def _pair_aliases(symbol: str) -> set[str]:
        normalized = (symbol or "").upper()
        aliases = {normalized}
        if normalized in {"XBTUSD", "BTCUSD"}:
            aliases.update({"XXBTZUSD", "XBT/USD", "BTC/USD", "BTCUSD", "XBTUSD"})
        return aliases

    async def get_spot_balances(self, assets: list[str]) -> Dict[str, float]:
        data = await self._request("POST", "/0/private/Balance", signed=True)
        balances = {}
        for asset in assets:
            balances[asset] = float(data.get(self._asset_code(asset), data.get(asset, 0.0)) or 0.0)
        return balances

    async def get_current_price(self, symbol: str) -> float:
        data = await self._request("GET", "/0/public/Ticker", params={"pair": symbol})
        ticker = next(iter(data.values()))
        return float(ticker["c"][0])

    async def create_market_buy_order(self, symbol: str, quantity_usd: float) -> Dict[str, Any]:
        if quantity_usd <= 0:
            raise ValueError("Order amount must be positive")
        return await self._request(
            "POST",
            "/0/private/AddOrder",
            params={
                "pair": symbol,
                "type": "buy",
                "ordertype": "market",
                "volume": f"{quantity_usd:.2f}",
                "oflags": "viqc",
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
        txids = order_response.get("txid") or []
        order_id = txids[0] if txids else None
        if not order_id:
            raise ValueError("Failed to retrieve Kraken order ID from order response")

        max_attempts = max(1, int(max_wait_seconds / poll_interval))
        trades = []
        for attempt in range(1, max_attempts + 1):
            history = await self._request(
                "POST",
                "/0/private/TradesHistory",
                params={"type": "all", "trades": True},
                signed=True,
            )
            trade_map = history.get("trades") or {}
            trades = [
                {"id": trade_id, **trade}
                for trade_id, trade in trade_map.items()
                if trade.get("ordertxid") == order_id
            ]
            if trades:
                break
            if attempt < max_attempts:
                await asyncio.sleep(poll_interval)
        else:
            raise TimeoutError(f"Failed to retrieve Kraken trades for order {order_id}")

        total_btc = sum(float(trade.get("vol", 0.0)) for trade in trades)
        total_quote = sum(float(trade.get("cost", 0.0)) for trade in trades)
        total_fee = sum(float(trade.get("fee", 0.0)) for trade in trades)
        avg_price = total_quote / total_btc if total_btc > 0 else 0.0
        return {
            "order_id": order_id,
            "trades": trades,
            "total_btc": total_btc,
            "avg_price": avg_price,
            "total_fee": total_fee,
            "fee_asset": "USD",
            "quote_spent": total_quote,
        }

    async def calculate_avg_buy_price(self, symbol: str) -> float:
        history = await self._request(
            "POST",
            "/0/private/TradesHistory",
            params={"type": "all"},
            signed=True,
        )
        trades = history.get("trades") or {}
        total_btc = 0.0
        total_quote = 0.0
        pair_aliases = self._pair_aliases(symbol)
        for trade in trades.values():
            if trade.get("type") != "buy" or str(trade.get("pair") or "").upper() not in pair_aliases:
                continue
            total_btc += float(trade.get("vol", 0.0))
            total_quote += float(trade.get("cost", 0.0))
        return total_quote / total_btc if total_btc > 0 else 0.0

    async def get_all_btc_trades(self, symbol: str = "XBTUSD", limit: int = 1000):
        history = await self._request(
            "POST",
            "/0/private/TradesHistory",
            params={"type": "all"},
            signed=True,
        )
        trades = history.get("trades") or {}
        pair_aliases = self._pair_aliases(symbol)
        normalized = []
        for trade_id, trade in trades.items():
            if str(trade.get("pair") or "").upper() not in pair_aliases:
                continue
            normalized.append(
                {
                    "id": str(trade_id),
                    "order_id": str(trade.get("ordertxid") or ""),
                    "time": datetime_from_kraken(trade.get("time")),
                    "price": float(trade.get("price", 0.0)),
                    "qty": float(trade.get("vol", 0.0)),
                    "quote_qty": float(trade.get("cost", 0.0)),
                    "commission": float(trade.get("fee", 0.0)),
                    "commission_asset": "USD",
                    "is_buyer": trade.get("type") == "buy",
                }
            )
        return normalized[:limit]


def datetime_from_kraken(value: Any):
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return value
