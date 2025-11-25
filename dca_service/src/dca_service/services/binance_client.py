import time
import hmac
import hashlib
import httpx
from typing import Dict, Any, Optional
from dca_service.core.logging import logger


class BinanceClient:
    BASE_URL = "https://api.binance.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=10.0)

    async def close(self):
        await self.client.aclose()

    def _get_signature(self, params: Dict[str, Any]) -> str:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        if params is None:
            params = {}

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._get_signature(params)

        headers = {"X-MBX-APIKEY": self.api_key}

        try:
            response = await self.client.request(
                method, endpoint, params=params, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            # Try to parse Binance error message
            try:
                error_data = e.response.json()
                msg = error_data.get("msg", str(e))
                code = error_data.get("code", "Unknown")
                raise ValueError(f"Binance API Error {code}: {msg}")
            except Exception:
                raise ValueError(f"HTTP Error: {e}")
        except httpx.RequestError as e:
            raise ValueError(f"Network Error: {e}")

    async def test_connection(self) -> bool:
        """
        Tests connection and permissions by calling a lightweight signed endpoint.
        Using /api/v3/account to verify API key validity and permissions.
        """
        try:
            # /api/v3/account requires signed access, good for verifying keys
            await self._request("GET", "/api/v3/account", signed=True)
            logger.info("Binance connection test succeeded")
            return True
        except Exception as e:
            logger.warning(f"Binance connection test failed: {e}")
            raise e

    async def get_spot_balances(self, assets: list[str]) -> Dict[str, float]:
        """
        Fetches spot balances for specified assets.
        Returns a dict: { "BTC": 0.1, "USDC": 100.0 }
        """
        try:
            data = await self._request("GET", "/api/v3/account", signed=True)
            balances = {}

            # Parse balances
            # data['balances'] is a list of {'asset': 'BTC', 'free': '0.00000000', 'locked': '0.00000000'}
            for item in data.get("balances", []):
                asset = item["asset"]
                if asset in assets:
                    free = float(item.get("free", 0))
                    locked = float(item.get("locked", 0))
                    balances[asset] = free + locked

            # Ensure all requested assets are present (default to 0.0)
            for asset in assets:
                if asset not in balances:
                    balances[asset] = 0.0

            holdings_str = ", ".join([f"{k}={v}" for k, v in balances.items()])
            logger.info(f"Fetched Binance holdings: {holdings_str}")
            return balances
        except Exception as e:
            logger.error(f"Failed to fetch Binance holdings: {e}")
            raise e

    async def create_market_buy_order(self, symbol: str, quantity_usd: float) -> Dict[str, Any]:
        """
        Places a market buy order for the specified amount in USD (quote asset).
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDC")
            quantity_usd: Amount of quote asset to spend
            
        Returns:
            Binance API response dict
        """
        try:
            # Basic validation
            if quantity_usd <= 0:
                raise ValueError("Order amount must be positive")
            
            # Binance requires string for decimal precision
            # Round to 2 decimals for USDC/USDT to be safe, though quoteOrderQty handles precision well
            qty_str = f"{quantity_usd:.2f}"
            
            params = {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": qty_str
            }
            
            logger.info(f"Placing LIVE MARKET BUY order: {symbol} for {qty_str} USD")
            
            response = await self._request("POST", "/api/v3/order", params=params, signed=True)
            
            logger.info(
                f"Order placed successfully! "
                f"ID: {response.get('orderId')}, "
                f"Status: {response.get('status')}, "
                f"Executed: {response.get('cummulativeQuoteQty')} {symbol[-4:]}"
            )
            return response
            
        except Exception as e:
            logger.error(f"Failed to place market buy order: {e}")
            raise e
