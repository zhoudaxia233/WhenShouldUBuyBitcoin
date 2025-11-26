#!/usr/bin/env python3
"""
Binance DCA Order Executor - Standalone Script

This script demonstrates the complete flow for executing a DCA purchase:
1. Place a market buy order on Binance Spot
2. Poll for actual trade fills with visual feedback
3. Display confirmed trade details

Requirements:
- requests library
- Valid Binance API credentials

Usage:
    python binance_order_executor.py --symbol BTCUSDC --amount 10.0
"""

import argparse
import hashlib
import hmac
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests


# ============================================================================
# Configuration
# ============================================================================

# Binance API endpoints
BASE_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"

# Default credentials (should be set via environment variables in production)
API_KEY = ""
SECRET_KEY = ""

# Polling configuration
MAX_POLL_ATTEMPTS = 10  # Maximum number of attempts to check for fills
POLL_INTERVAL_SECONDS = 1  # Wait time between polling attempts


# ============================================================================
# Core Functions
# ============================================================================

def _generate_signature(params: Dict, secret_key: str) -> str:
    """
    Generate HMAC SHA256 signature for Binance API request.
    
    Args:
        params: Dictionary of request parameters
        secret_key: API secret key
        
    Returns:
        Hexadecimal signature string
    """
    query_string = urlencode(params)
    signature = hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def _make_request(
    method: str,
    endpoint: str,
    params: Optional[Dict] = None,
    signed: bool = False,
    base_url: str = BASE_URL
) -> Dict:
    """
    Make authenticated request to Binance API.
    
    Args:
        method: HTTP method (GET, POST)
        endpoint: API endpoint path
        params: Request parameters
        signed: Whether request requires signature
        base_url: Base URL for API calls
        
    Returns:
        JSON response from API
        
    Raises:
        requests.exceptions.HTTPError: On API error
    """
    if params is None:
        params = {}
    
    headers = {
        "X-MBX-APIKEY": API_KEY
    }
    
    # Add timestamp and signature for signed requests
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = _generate_signature(params, SECRET_KEY)
    
    url = f"{base_url}{endpoint}"
    
    if method == "GET":
        response = requests.get(url, headers=headers, params=params)
    elif method == "POST":
        response = requests.post(url, headers=headers, params=params)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")
    
    response.raise_for_status()
    return response.json()


def _place_market_order(symbol: str, quote_quantity: float, base_url: str = BASE_URL) -> int:
    """
    Place a market buy order on Binance Spot.
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDC")
        quote_quantity: Amount in quote currency (e.g., 10.0 USDC)
        base_url: Base URL for API calls
        
    Returns:
        Order ID from Binance
        
    Raises:
        requests.exceptions.HTTPError: On API error
    """
    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": quote_quantity
    }
    
    print(f"📤 Submitting market order: {quote_quantity} USDC for {symbol}...")
    
    response = _make_request("POST", "/api/v3/order", params=params, signed=True, base_url=base_url)
    
    order_id = response["orderId"]
    print(f"✅ Order submitted! ID: {order_id}")
    
    return order_id


def _get_order_trades(
    order_id: int,
    symbol: str,
    max_attempts: int = MAX_POLL_ATTEMPTS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    base_url: str = BASE_URL
) -> List[Dict]:
    """
    Poll for actual trade fills for a given order ID.
    
    This function will retry multiple times with visual feedback until
    trades are confirmed or max attempts is reached.
    
    Args:
        order_id: Binance order ID
        symbol: Trading pair (e.g., "BTCUSDC")
        max_attempts: Maximum polling attempts
        poll_interval: Seconds to wait between attempts
        base_url: Base URL for API calls
        
    Returns:
        List of trade dictionaries from Binance
        
    Raises:
        TimeoutError: If trades not found within max attempts
    """
    print(f"\n⏳ Waiting for trade confirmation...")
    
    for attempt in range(1, max_attempts + 1):
        print(f"   Attempt {attempt}/{max_attempts}...", end="", flush=True)
        
        # Query trades filtered by order ID
        params = {
            "symbol": symbol,
            "orderId": order_id
        }
        
        try:
            trades = _make_request("GET", "/api/v3/myTrades", params=params, signed=True, base_url=base_url)
            
            if trades:
                print(" ✅")
                print(f"\n✅ Trades confirmed! Found {len(trades)} fill(s)")
                return trades
            else:
                print(" (no fills yet)")
                
        except requests.exceptions.HTTPError as e:
            print(f" ⚠️ API error: {e}")
        
        # Wait before next attempt (except on last attempt)
        if attempt < max_attempts:
            time.sleep(poll_interval)
    
    # If we get here, we've exhausted all attempts
    raise TimeoutError(f"Failed to retrieve trades for order {order_id} after {max_attempts} attempts")


def _display_trade_details(trades: List[Dict]) -> None:
    """
    Display detailed information about confirmed trades.
    
    Args:
        trades: List of trade dictionaries from Binance
    """
    print("\n" + "=" * 70)
    print("📊 TRADE DETAILS")
    print("=" * 70)
    
    total_qty = 0.0
    total_quote = 0.0
    total_fee = 0.0
    fee_asset = None
    
    for idx, trade in enumerate(trades, 1):
        trade_id = trade["id"]
        price = float(trade["price"])
        qty = float(trade["qty"])
        quote_qty = float(trade["quoteQty"])
        commission = float(trade["commission"])
        commission_asset = trade["commissionAsset"]
        is_buyer = trade["isBuyer"]
        
        # Accumulate totals
        total_qty += qty
        total_quote += quote_qty
        total_fee += commission
        fee_asset = commission_asset
        
        print(f"\n  Trade #{idx}:")
        print(f"    Trade ID:      {trade_id}")
        print(f"    Side:          {'BUY' if is_buyer else 'SELL'}")
        print(f"    Quantity:      {qty:.8f} BTC")
        print(f"    Price:         ${price:,.2f}")
        print(f"    Quote Amount:  ${quote_qty:.2f}")
        print(f"    Fee:           {commission:.8f} {commission_asset}")
    
    # Summary
    print("\n" + "-" * 70)
    print(f"  TOTAL BTC PURCHASED:  {total_qty:.8f} BTC")
    print(f"  TOTAL SPENT:          ${total_quote:.2f}")
    print(f"  AVERAGE PRICE:        ${total_quote / total_qty:,.2f}" if total_qty > 0 else "  AVERAGE PRICE:        N/A")
    print(f"  TOTAL FEE:            {total_fee:.8f} {fee_asset}")
    print("=" * 70 + "\n")


# ============================================================================
# Main Execution Function
# ============================================================================

def execute_dca_purchase(
    symbol: str,
    quote_quantity: float,
    testnet: bool = False
) -> Dict:
    """
    Execute a DCA purchase with trade confirmation.
    
    This is the main orchestration function that:
    1. Places a market buy order
    2. Polls for actual trade fills
    3. Returns confirmed trade data
    
    Args:
        symbol: Trading pair (e.g., "BTCUSDC")
        quote_quantity: Amount to spend in quote currency
        testnet: Whether to use Binance testnet
        
    Returns:
        Dictionary containing:
            - order_id: Binance order ID
            - trades: List of confirmed trades
            - total_btc: Total BTC purchased
            - avg_price: Average execution price
            - total_fee: Total fee amount
            - fee_asset: Fee currency
    """
    base_url = TESTNET_URL if testnet else BASE_URL
    
    print("\n" + "=" * 70)
    print(f"🚀 STARTING DCA PURCHASE")
    print("=" * 70)
    print(f"  Symbol:        {symbol}")
    print(f"  Quote Amount:  ${quote_quantity:.2f}")
    print(f"  Network:       {'TESTNET' if testnet else 'MAINNET'}")
    print("=" * 70 + "\n")
    
    try:
        # Step 1: Place the market order
        order_id = _place_market_order(symbol, quote_quantity, base_url)
        
        # Step 2: Poll for trade confirmation
        trades = _get_order_trades(order_id, symbol, base_url=base_url)
        
        # Step 3: Display trade details
        _display_trade_details(trades)
        
        # Calculate aggregated data
        total_btc = sum(float(t["qty"]) for t in trades)
        total_quote = sum(float(t["quoteQty"]) for t in trades)
        avg_price = total_quote / total_btc if total_btc > 0 else 0
        total_fee = sum(float(t["commission"]) for t in trades)
        fee_asset = trades[0]["commissionAsset"] if trades else ""
        
        result = {
            "order_id": order_id,
            "trades": trades,
            "total_btc": total_btc,
            "avg_price": avg_price,
            "total_fee": total_fee,
            "fee_asset": fee_asset
        }
        
        print("✅ DCA purchase completed successfully!\n")
        return result
        
    except Exception as e:
        print(f"\n❌ Error during DCA purchase: {e}\n")
        raise


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Execute a DCA purchase on Binance with trade confirmation"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDC",
        help="Trading pair (default: BTCUSDC)"
    )
    parser.add_argument(
        "--amount",
        type=float,
        required=True,
        help="Amount to spend in quote currency (e.g., 10.0 for $10)"
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use Binance testnet instead of mainnet"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="Binance API key (overrides global config)"
    )
    parser.add_argument(
        "--secret-key",
        type=str,
        help="Binance API secret key (overrides global config)"
    )
    
    args = parser.parse_args()
    
    # Update global credentials if provided
    global API_KEY, SECRET_KEY
    if args.api_key:
        API_KEY = args.api_key
    if args.secret_key:
        SECRET_KEY = args.secret_key
    
    # Validate credentials
    if not API_KEY or not SECRET_KEY:
        print("❌ Error: API credentials not configured!")
        print("   Set API_KEY and SECRET_KEY in the script or use --api-key and --secret-key")
        return 1
    
    # Execute the purchase
    try:
        execute_dca_purchase(
            symbol=args.symbol,
            quote_quantity=args.amount,
            testnet=args.testnet
        )
        return 0
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
