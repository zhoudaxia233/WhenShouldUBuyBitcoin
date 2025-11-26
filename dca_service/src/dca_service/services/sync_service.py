from datetime import datetime, timezone
from typing import List, Optional
from sqlmodel import Session, select, col
from sqlalchemy.exc import IntegrityError

from dca_service.models import DCATransaction, BinanceCredentials
from dca_service.services.binance_client import BinanceClient
from dca_service.services.security import decrypt_text
from dca_service.core.logging import logger

class TradeSyncService:
    """
    Service to handle incremental synchronization of trades from Binance.
    """
    
    def __init__(self, session: Session):
        self.session = session
        
    def get_last_synced_timestamp(self) -> int:
        """
        Get the timestamp (in ms) of the most recent trade stored in the DB.
        Returns 0 if no trades exist.
        """
        # Find the trade with the latest timestamp that has a valid binance_trade_id
        statement = (
            select(DCATransaction)
            .where(DCATransaction.binance_trade_id.is_not(None))
            .order_by(col(DCATransaction.timestamp).desc())
            .limit(1)
        )
        last_tx = self.session.exec(statement).first()
        
        if last_tx:
            # Convert datetime to ms timestamp
            return int(last_tx.timestamp.timestamp() * 1000)
        
        return 0

    def _get_client(self) -> Optional[BinanceClient]:
        """Get authenticated Binance client (READ_ONLY preferred)"""
        # Try READ_ONLY first
        creds = self.session.exec(
            select(BinanceCredentials).where(BinanceCredentials.credential_type == "READ_ONLY")
        ).first()
        
        # Fallback to TRADING
        if not creds:
            creds = self.session.exec(
                select(BinanceCredentials).where(BinanceCredentials.credential_type == "TRADING")
            ).first()
        
        if not creds or not creds.api_key_encrypted:
            return None
        
        try:
            api_key = decrypt_text(creds.api_key_encrypted)
            api_secret = decrypt_text(creds.api_secret_encrypted)
            return BinanceClient(api_key, api_secret)
        except Exception as e:
            logger.error(f"Failed to decrypt credentials: {e}")
            return None

    async def sync_trades(self, symbol: str = "BTCUSDC") -> int:
        """
        Fetch new trades from Binance and store them in the database.
        
        Args:
            symbol: Trading pair to sync
            
        Returns:
            Number of new trades added
        """
        client = self._get_client()
        if not client:
            logger.warning("No Binance credentials found. Skipping sync.")
            return 0
            
        try:
            # 1. Get last sync timestamp
            last_ts = self.get_last_synced_timestamp()
            
            # Add 1ms to avoid fetching the same trade again
            start_time = last_ts + 1 if last_ts > 0 else None
            
            logger.info(f"Syncing trades for {symbol} starting from {start_time or 'beginning'}...")
            
            # 2. Fetch new trades from Binance
            # Note: We use a custom request here because get_all_btc_trades doesn't support startTime yet
            params = {"symbol": symbol, "limit": 1000}
            if start_time:
                params["startTime"] = start_time
                
            trades = await client._request("GET", "/api/v3/myTrades", params=params, signed=True)
            
            if not trades:
                logger.info("No new trades found.")
                return 0
                
            logger.info(f"Fetched {len(trades)} new trades from Binance")
            
            # 3. Store new trades
            added_count = 0
            
            # Get existing order IDs to avoid duplicating DCA transactions that might not have trade_id set yet
            existing_dca_orders = set(
                self.session.exec(
                    select(DCATransaction.binance_order_id)
                    .where(DCATransaction.binance_order_id.is_not(None))
                ).all()
            )
            
            for trade in trades:
                trade_id = trade["id"]
                order_id = trade["orderId"]
                
                # Skip if we already have this trade ID (double check)
                exists = self.session.exec(
                    select(DCATransaction)
                    .where(DCATransaction.binance_trade_id == trade_id)
                ).first()
                
                if exists:
                    continue
                
                # Check if this corresponds to a known DCA order
                # If so, we might want to update the existing record with the trade ID
                # But DCA orders might have multiple fills (trades), so we can't just 1:1 map easily
                # Strategy: 
                # - If it's a DCA order, we assume the DCA bot already created a record
                # - BUT, the DCA bot record doesn't have trade_id. 
                # - AND one order can have multiple trades.
                # - SIMPLIFICATION: For now, we only import MANUAL trades (not in existing_dca_orders)
                #   OR we import everything but mark is_manual=False if it matches a DCA order.
                
                # Better approach:
                # If order_id matches a known DCA transaction:
                #   - If that transaction has NO trade_id, update it with this trade_id (first fill)
                #   - If it already has a trade_id (or this is a second fill), create a new record?
                #   - Actually, for simplicity and to avoid "double counting" in the UI:
                #     We should probably ONLY import trades that are NOT from our DCA bot.
                #     DCA bot trades are already recorded when they happen.
                
                if order_id in existing_dca_orders:
                    # This is a trade from our own bot.
                    # We could update the existing record to add the trade_id if missing
                    dca_tx = self.session.exec(
                        select(DCATransaction)
                        .where(DCATransaction.binance_order_id == order_id)
                        .where(DCATransaction.binance_trade_id.is_(None))
                    ).first()
                    
                    if dca_tx:
                        # Link this trade to the existing DCA record
                        dca_tx.binance_trade_id = trade_id
                        self.session.add(dca_tx)
                        # If there are multiple fills, subsequent ones will be skipped or treated as new?
                        # For now, let's just link the first one.
                        continue
                    else:
                        # Already linked, or multiple fills. 
                        # To avoid duplicates in the UI, we skip additional fills for now
                        # (unless we want to show every partial fill as a separate row)
                        continue
                
                # Only import BUY trades for now (DCA context)
                if not trade["isBuyer"]:
                    continue
                    
                # Create new transaction record for this manual trade
                ts = datetime.fromtimestamp(trade["time"] / 1000, tz=timezone.utc)
                qty = float(trade["qty"])
                price = float(trade["price"])
                quote_qty = float(trade["quoteQty"])
                commission = float(trade["commission"])
                commission_asset = trade["commissionAsset"]
                
                # Normalize fee to USD if possible (approximate)
                # This is tricky without historical prices. We'll store raw values.
                
                new_tx = DCATransaction(
                    timestamp=ts,
                    status="SUCCESS",
                    fiat_amount=quote_qty,
                    btc_amount=qty,
                    price=price,
                    ahr999=0.0, # Unknown for manual trades
                    notes="Imported from Binance",
                    source="MANUAL",
                    is_manual=True,
                    binance_order_id=order_id,
                    binance_trade_id=trade_id,
                    fee_amount=commission,
                    fee_asset=commission_asset,
                    
                    # Fill required fields
                    intended_amount_usd=quote_qty,
                    executed_amount_usd=quote_qty,
                    executed_amount_btc=qty,
                    avg_execution_price_usd=price
                )
                
                self.session.add(new_tx)
                added_count += 1
            
            self.session.commit()
            logger.info(f"Successfully synced {added_count} new trades")
            return added_count
            
        except Exception as e:
            logger.error(f"Error syncing trades: {e}")
            return 0
        finally:
            await client.close()
