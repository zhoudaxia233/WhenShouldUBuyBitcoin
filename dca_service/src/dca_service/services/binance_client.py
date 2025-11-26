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

    async def execute_market_order_with_confirmation(
        self,
        symbol: str,
        quote_quantity: float,
        max_wait_seconds: int = 10,
        poll_interval: float = 1.0
    ) -> Dict[str, Any]:
        """
        Execute market order and wait for trade confirmation.
        
        This method:
        1. Places a market buy order
        2. Polls for actual trade fills (retries with configurable timeout)
        3. Returns aggregated confirmed trade data
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDC")
            quote_quantity: Amount in quote currency to spend
            max_wait_seconds: Maximum time to wait for trade confirmation
            poll_interval: Seconds between polling attempts
            
        Returns:
            Dictionary containing:
                - order_id: Binance order ID
                - trades: List of confirmed trades
                - total_btc: Total BTC purchased
                - avg_price: Average execution price
                - total_fee: Total fee amount
                - fee_asset: Fee currency
                
        Raises:
            TimeoutError: If trades not confirmed within max_wait_seconds
            ValueError: On API errors or invalid parameters
        """
        import asyncio
        
        # Step 1: Place the market order
        logger.info(f"🚀 Executing market order: {symbol} for ${quote_quantity:.2f}")
        order_response = await self.create_market_buy_order(symbol, quote_quantity)
        order_id = order_response.get("orderId")
        
        if not order_id:
            raise ValueError("Failed to retrieve order ID from order response")
        
        # Step 2: Poll for trade confirmation
        max_attempts = int(max_wait_seconds / poll_interval)
        logger.info(f"⏳ Waiting for trade confirmation (max {max_wait_seconds}s)...")
        
        for attempt in range(1, max_attempts + 1):
            logger.debug(f"   Polling attempt {attempt}/{max_attempts}...")
            
            try:
                # Query trades for this specific order ID
                params = {
                    "symbol": symbol,
                    "orderId": order_id
                }
                trades = await self._request("GET", "/api/v3/myTrades", params=params, signed=True)
                
                if trades:
                    logger.info(f"✅ Trades confirmed! Found {len(trades)} fill(s)")
                    break
                else:
                    logger.debug(f"   No fills yet (attempt {attempt}/{max_attempts})")
                    
            except Exception as e:
                logger.warning(f"   Error querying trades: {e}")
            
            # Wait before next attempt (except on last attempt)
            if attempt < max_attempts:
                await asyncio.sleep(poll_interval)
        else:
            # Exhausted all attempts without finding trades
            raise TimeoutError(
                f"Failed to retrieve trades for order {order_id} after {max_wait_seconds}s. "
                f"Order may still be processing on Binance."
            )
        
        # Step 3: Aggregate trade data
        total_btc = 0.0
        total_quote = 0.0
        total_fee = 0.0
        fee_asset = ""
        
        for trade in trades:
            qty = float(trade.get("qty", 0))
            price = float(trade.get("price", 0))
            quote_qty = float(trade.get("quoteQty", 0))
            commission = float(trade.get("commission", 0))
            commission_asset = trade.get("commissionAsset", "")
            
            total_btc += qty
            total_quote += quote_qty
            total_fee += commission
            fee_asset = commission_asset  # Use the last one (usually all the same)
        
        avg_price = total_quote / total_btc if total_btc > 0 else 0.0
        
        logger.info(
            f"📊 Order execution summary: "
            f"{total_btc:.8f} BTC @ ${avg_price:,.2f} avg "
            f"(Fee: {total_fee:.8f} {fee_asset})"
        )
        
        return {
            "order_id": order_id,
            "trades": trades,
            "total_btc": total_btc,
            "avg_price": avg_price,
            "total_fee": total_fee,
            "fee_asset": fee_asset,
            "quote_spent": total_quote
        }

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

    async def get_all_btc_trades(self, symbol: str = "BTCUSDC", limit: int = 1000):
        """
        Fetch all BTC trades from Binance (last 1000 max).
        
        Args:
            symbol: Trading pair (default: "BTCUSDC")
            limit: Number of trades to fetch (max 1000 per Binance limit)
            
        Returns:
            List of trade dictionaries from Binance
        """
        try:
            params = {"symbol": symbol, "limit": limit}
            trades = await self._request("GET", "/api/v3/myTrades", params=params, signed=True)
            logger.info(f"Fetched {len(trades)} trades for {symbol}")
            return trades
        except Exception as e:
            logger.error(f"Failed to fetch trades for {symbol}: {e}")
            raise e
