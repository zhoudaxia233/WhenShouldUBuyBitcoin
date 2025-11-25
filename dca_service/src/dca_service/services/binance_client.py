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

    async def get_current_price(self, symbol: str) -> float:
        """
        Fetch current market price for a trading pair.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDC")
            
        Returns:
            Current price as float
        """
        try:
            response = await self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol})
            price = float(response["price"])
            logger.debug(f"Current {symbol} price: {price}")
            return price
        except Exception as e:
            logger.error(f"Failed to fetch current price for {symbol}: {e}")
            raise e

    async def calculate_avg_buy_price(self, symbol: str) -> float:
        """
        Calculate estimated average buy price (cost basis) from trade history.
        
        IMPORTANT LIMITATIONS:
        - Only considers last 1000 trades (Binance API limit)
        - Does NOT account for deposits/withdrawals
        - Does NOT account for transfers between accounts
        - This is an ESTIMATION for portfolio tracking, not tax/accounting
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDC")
            
        Returns:
            Average buy price as float, or 0.0 if no buy trades found
        """
        try:
            # Fetch recent trades (max 1000 per API limitations)
            params = {
                "symbol": symbol,
                "limit": 1000  # Maximum allowed by Binance
            }
            response = await self._request("GET", "/api/v3/myTrades", params=params, signed=True)
            
            total_cost = 0.0
            total_quantity = 0.0
            buy_count = 0
            
            for trade in response:
                # Only consider buy trades
                if trade.get("isBuyer", False):
                    qty = float(trade.get("qty", 0))
                    price = float(trade.get("price", 0))
                    commission = float(trade.get("commission", 0))
                    
                    # Add to totals
                    total_quantity += qty
                    total_cost += (qty * price)
                    buy_count += 1
            
            if total_quantity > 0:
                avg_price = total_cost / total_quantity
                logger.info(
                    f"Calculated avg buy price for {symbol}: ${avg_price:.2f} "
                    f"(based on {buy_count} buy trades, {total_quantity:.8f} BTC)"
                )
                return avg_price
            else:
                logger.warning(f"No buy trades found for {symbol}")
                return 0.0
                
        except Exception as e:
            logger.error(f"Failed to calculate average buy price for {symbol}: {e}")
            raise e
