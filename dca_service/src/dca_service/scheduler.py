"""
DCA Scheduler - Automatic execution of DCA transactions

Uses APScheduler to check every minute if a DCA transaction should be executed
based on the strategy configuration (execution_time_utc, execution_frequency).
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from dca_service.database import engine
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision
from dca_service.config import settings
from dca_service.core.logging import logger


class DCAScheduler:
    """
    Background scheduler for automatic DCA execution.
    
    Checks every minute if conditions are met to execute a DCA transaction:
    - Strategy is active
    - Current time matches execution_time_utc (with a short grace window)
    - Frequency matches (daily or correct day of week for weekly)
    - No transaction already executed today (for daily) or this week (for weekly)
    """

    EXECUTION_GRACE_MINUTES = 5
    
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.is_running = False
    
    def start(self):
        """Start the background scheduler"""
        if self.is_running:
            logger.warning("DCA Scheduler already running")
            return
        
        # Schedule job to run every minute
        self.scheduler.add_job(
            func=self._check_and_execute_dca,
            trigger=CronTrigger(minute='*'),  # Every minute
            id='dca_check',
            name='DCA Execution Check',
            replace_existing=True
        )
        
        # Schedule trade sync job to run every 10 minutes
        self.scheduler.add_job(
            func=self._sync_trades_job,
            trigger=CronTrigger(minute='*/10'),  # Every 10 minutes
            id='trade_sync',
            name='Exchange Trade Sync',
            replace_existing=True
        )

        if settings.STATIC_GENERATION_SCHEDULE_ENABLED:
            self.scheduler.add_job(
                func=self._run_static_generation_job,
                trigger=CronTrigger(
                    hour=settings.STATIC_GENERATION_SCHEDULE_HOUR_UTC,
                    minute=settings.STATIC_GENERATION_SCHEDULE_MINUTE_UTC,
                ),
                id='static_generation',
                name='Daily Static Analysis Generation',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        
        self.scheduler.start()
        self.is_running = True
        logger.info("DCA Scheduler started - checking every minute, syncing every 10m")
    
    def stop(self):
        """Stop the background scheduler"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("DCA Scheduler stopped")
    
    def _check_and_execute_dca(self):
        """
        Check if DCA should be executed now and execute if conditions are met.
        
        This method is called every minute by the scheduler.
        """
        try:
            with Session(engine) as session:
                strategy = session.exec(select(DCAStrategy)).first()
                
                if not strategy:
                    logger.debug("No strategy configured, skipping DCA check")
                    return
                
                if not strategy.is_active:
                    logger.debug("Strategy is not active, skipping DCA check")
                    return
                
                # Check if current time matches execution time
                if not self._should_execute_now(strategy, session):
                    return
                
                # Execute DCA
                self._execute_dca(strategy, session)
                
        except Exception as e:
            logger.exception(f"Error in DCA scheduler: {e}")

    def _get_now_in_strategy_timezone(self, strategy: DCAStrategy) -> datetime:
        """
        Get current time in strategy-selected timezone context.

        UTC mode: returns UTC now.
        LOCAL mode: returns configured LOCAL_TIMEZONE clock.
        """
        mode = (strategy.time_display_mode or "UTC").upper()
        if mode == "LOCAL":
            try:
                local_tz = ZoneInfo(settings.LOCAL_TIMEZONE)
                return datetime.now(timezone.utc).astimezone(local_tz)
            except ZoneInfoNotFoundError:
                logger.error(
                    f"Invalid LOCAL_TIMEZONE '{settings.LOCAL_TIMEZONE}', fallback to system local timezone"
                )
                return datetime.now(timezone.utc).astimezone()
        return datetime.now(timezone.utc)
    
    # ... (skipping _should_execute_now and helpers as they use logger.debug/error which is fine) ...

    def _should_execute_now(self, strategy: DCAStrategy, session: Session) -> bool:
        """
        Check if DCA should be executed at the current time.
        
        Args:
            strategy: The DCA strategy configuration
            session: Database session
            
        Returns:
            True if DCA should be executed now, False otherwise
        """
        now = self._get_now_in_strategy_timezone(strategy)
        
        if not strategy.is_active:
            return False
        
        # Parse execution time (format: "HH:MM")
        try:
            exec_hour, exec_minute = map(int, strategy.execution_time_utc.split(':'))
        except (ValueError, AttributeError):
            logger.error(f"Invalid execution_time_utc format: {strategy.execution_time_utc}")
            return False
        
        # Check if current time is within the execution window.
        # This avoids missing a run due to short outages/restarts around the target minute.
        if not self._is_within_execution_window(now, exec_hour, exec_minute):
            return False
        
        # Check frequency-specific conditions
        if strategy.execution_frequency == "daily":
            return self._should_execute_daily(session, now)
        elif strategy.execution_frequency == "weekly":
            return self._should_execute_weekly(strategy, session, now)
        else:
            logger.error(f"Unknown execution frequency: {strategy.execution_frequency}")
            return False

    def _is_within_execution_window(self, now: datetime, exec_hour: int, exec_minute: int) -> bool:
        """
        Return True if `now` is within execution minute + grace period.
        """
        scheduled_time = now.replace(hour=exec_hour, minute=exec_minute, second=0, microsecond=0)
        if now < scheduled_time:
            return False

        delay = now - scheduled_time
        return delay <= timedelta(minutes=self.EXECUTION_GRACE_MINUTES)
    
    def _should_execute_daily(self, session: Session, now: datetime) -> bool:
        """
        Check if daily DCA should execute (no transaction today yet).
        
        Args:
            session: Database session
            now: Current UTC datetime
            
        Returns:
            True if no transaction executed today, False otherwise
        """
        # Start/end of "today" in strategy timezone, converted to UTC for DB query.
        # End bound prevents future-dated transactions from incorrectly blocking today.
        today_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start_local = today_start_local + timedelta(days=1)
        today_start = today_start_local.astimezone(timezone.utc)
        tomorrow_start = tomorrow_start_local.astimezone(timezone.utc)
        
        existing_tx = session.exec(
            select(DCATransaction)
            .where(DCATransaction.timestamp >= today_start)
            .where(DCATransaction.timestamp < tomorrow_start)
            .where(DCATransaction.status == "SUCCESS")
            .where(DCATransaction.is_manual == False)
        ).first()
        
        if existing_tx:
            logger.debug("DCA already executed today, skipping")
            return False
        
        return True
    
    def _should_execute_weekly(
        self, 
        strategy: DCAStrategy, 
        session: Session, 
        now: datetime
    ) -> bool:
        """
        Check if weekly DCA should execute (correct day and no transaction this week).
        
        Args:
            strategy: The DCA strategy configuration
            session: Database session
            now: Current UTC datetime
            
        Returns:
            True if correct day and no transaction this week, False otherwise
        """
        # Check if today is the configured day of week in strategy timezone.
        current_day = now.strftime('%A').lower()
        if current_day != strategy.execution_day_of_week:
            logger.debug(
                f"Not the configured day ({strategy.execution_day_of_week}), "
                f"today is {current_day}"
            )
            return False
        
        # Start of week in strategy timezone, converted to UTC for DB query.
        # Week starts on Monday (weekday 0).
        days_since_monday = now.weekday()
        week_start_local = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
        week_start = week_start_local.astimezone(timezone.utc)
        
        existing_tx = session.exec(
            select(DCATransaction)
            .where(DCATransaction.timestamp >= week_start)
            .where(DCATransaction.status == "SUCCESS")
            .where(DCATransaction.is_manual == False)
        ).first()
        
        if existing_tx:
            logger.debug("DCA already executed this week, skipping")
            return False
        
        return True
    
    def _execute_dca(self, strategy: DCAStrategy, session: Session):
        """
        Execute the DCA transaction.
        
        Args:
            strategy: The DCA strategy configuration
            session: Database session
        """
        logger.info("Executing scheduled DCA transaction")
        
        try:
            # Calculate DCA decision
            decision = calculate_dca_decision(session)
            
            logger.info(
                f"DCA Decision: AHR999={decision.ahr999_value:.4f}, "
                f"Price=${decision.price_usd:.2f}, "
                f"Band={decision.ahr_band}, Multiplier={decision.multiplier:.2f}x, "
                f"Suggested=${decision.suggested_amount_usd:.2f}, "
                f"CanExecute={decision.can_execute} ({decision.reason})"
            )
            
            if not decision.can_execute:
                return
            
            # Calculate BTC amount (Simulated default)
            btc_amount = decision.suggested_amount_usd / decision.price_usd if decision.price_usd > 0 else 0
            
            # Default values for simulated trade
            source = "SIMULATED"
            executed_price = decision.price_usd
            executed_btc = btc_amount
            executed_usd = decision.suggested_amount_usd
            binance_order_id = None  # Will be set for LIVE trades
            fee_amount = 0.0  # Will be set for LIVE trades
            fee_asset = "USDC"  # Will be set for LIVE trades
            exchange = None
            exchange_order_id = None
            exchange_symbol = None
            
            # Execute Real Trade if LIVE mode
            if strategy.execution_mode == "LIVE":
                try:
                    from dca_service.services.security import decrypt_text
                    from dca_service.services.exchange_config import (
                        get_active_exchange,
                        get_credentials,
                        get_exchange_symbol,
                    )
                    import asyncio
                    
                    exchange = get_active_exchange(session)
                    exchange_symbol = get_exchange_symbol(exchange)
                    creds = get_credentials(session, exchange, "TRADING")
                    if not creds or not creds.api_key_encrypted:
                        raise ValueError(f"{exchange} trading credentials not configured. Please add trading API keys in settings.")
                    
                    api_key = decrypt_text(creds.api_key_encrypted)
                    api_secret = decrypt_text(creds.api_secret_encrypted)
                    
                    async def execute_live_trade():
                        if exchange == "KRAKEN":
                            from dca_service.services.kraken_client import KrakenClient
                            client = KrakenClient(api_key, api_secret)
                        else:
                            from dca_service.services.binance_client import BinanceClient
                            client = BinanceClient(api_key, api_secret)
                        try:
                            return await client.execute_market_order_with_confirmation(
                                symbol=exchange_symbol,
                                quote_quantity=decision.suggested_amount_usd,
                                max_wait_seconds=10,
                                poll_interval=1.0
                            )
                        finally:
                            await client.close()
                    
                    logger.info(f"LIVE MODE: Attempting to buy ${decision.suggested_amount_usd:.2f} of BTC on {exchange}...")
                    result = asyncio.run(execute_live_trade())
                    
                    exchange_order_id = str(result["order_id"])
                    if exchange == "BINANCE":
                        binance_order_id = result["order_id"]
                    executed_btc = result["total_btc"]
                    executed_price = result["avg_price"]
                    executed_usd = result["quote_spent"]
                    fee_amount = result["total_fee"]
                    fee_asset = result["fee_asset"]
                    
                    source = "DCA"  # Changed from "BINANCE" to "DCA" for bot-triggered trades
                    logger.info(
                        f"LIVE TRADE SUCCESSFUL: {exchange} order {exchange_order_id} - "
                        f"Bought {executed_btc:.8f} BTC @ ${executed_price:,.2f} avg "
                        f"(Fee: {fee_amount:.8f} {fee_asset})"
                    )
                    
                except Exception as e:
                    logger.error(f"LIVE Trading failed: {e}")
                    # Don't re-raise - we'll record as FAILED transaction instead
                    source = f"{exchange or 'EXCHANGE'}_FAILED"
                    error_msg = str(e)
                    # Check for specific error types
                    if "401" in error_msg or "permissions" in error_msg.lower():
                        error_msg = "Invalid API key or insufficient trading permissions"
                    elif "network" in error_msg.lower() or "timeout" in error_msg.lower():
                        error_msg = f"Network error: {error_msg[:100]}"
                    else:
                        error_msg = f"Trade failed: {error_msg[:100]}"
            
            # Create transaction record (SUCCESS or FAILED)
            if source.endswith("_FAILED"):
                transaction = DCATransaction(
                    status="FAILED",
                    fiat_amount=decision.suggested_amount_usd,
                    btc_amount=0.0,  # No BTC received
                    price=decision.price_usd,
                    ahr999=decision.ahr999_value,
                    notes=error_msg,
                    intended_amount_usd=decision.suggested_amount_usd,
                    executed_amount_usd=0.0,  # Nothing executed
                    executed_amount_btc=0.0,
                    avg_execution_price_usd=0.0,
                    fee_amount=0.0,
                    fee_asset="USDC",
                    source=source,
                    binance_order_id=None,  # Failed trades have no order ID
                    exchange=exchange,
                    exchange_symbol=exchange_symbol,
                )
            else:
                transaction = DCATransaction(
                    status="SUCCESS",
                    fiat_amount=decision.suggested_amount_usd,
                    btc_amount=executed_btc,
                    price=executed_price,
                    ahr999=decision.ahr999_value,
                    notes=f"Automated {strategy.execution_frequency} DCA ({strategy.execution_mode})",
                    intended_amount_usd=decision.suggested_amount_usd,
                    executed_amount_usd=executed_usd,
                    executed_amount_btc=executed_btc,
                    avg_execution_price_usd=executed_price,
                    fee_amount=fee_amount,  # Now using actual fee from confirmed trades
                    fee_asset=fee_asset,  # Now using actual fee asset
                    source=source,
                    binance_order_id=binance_order_id,  # Save Binance order ID
                    exchange=exchange,
                    exchange_order_id=exchange_order_id,
                    exchange_symbol=exchange_symbol,
                )

                # Deduct executed amount from accumulated savings
                # Safe to deduct because we checked budget availability in calculate_dca_decision
                if strategy.accumulated_savings > 0:
                     strategy.accumulated_savings = max(0.0, strategy.accumulated_savings - executed_usd)
                     session.add(strategy)
            
            session.add(transaction)
            session.commit()
            session.refresh(transaction)
            
            if transaction.status == "FAILED":
                logger.error(
                    f"FAILED Transaction Created: ID={transaction.id}, "
                    f"Intended=${transaction.intended_amount_usd:.2f}, "
                    f"Error={error_msg}"
                )
                # Send failure email
                try:
                    from dca_service.services.mailer import send_trade_failure_notification
                    send_trade_failure_notification(transaction, decision, error_msg)
                except Exception as email_err:
                    logger.error(f"Failed to send failure notification email: {email_err}")
            else:
                logger.info(
                    f"Transaction Created: ID={transaction.id}, "
                    f"Intended=${transaction.intended_amount_usd:.2f}, "
                    f"Executed=${transaction.executed_amount_usd:.2f} ({transaction.executed_amount_btc:.8f} BTC), "
                    f"Source={transaction.source}, StrategyID={strategy.id}"
                )
                # Send success email
                try:
                    from dca_service.services.mailer import send_dca_notification
                    from dca_service.api.wallet_api import fetch_wallet_summary
                    import asyncio
                    
                    # Fetch real wallet stats for email
                    # We need to run this async function synchronously
                    async def get_stats():
                        return await fetch_wallet_summary(session)
                    
                    try:
                        wallet_summary = asyncio.run(get_stats())
                        total_btc = wallet_summary.total_btc
                    except Exception as stats_err:
                        logger.error(f"Failed to fetch wallet stats for email: {stats_err}")
                        total_btc = None
                    
                    send_dca_notification(transaction, decision, total_btc)
                except Exception as e:
                    logger.error(f"Failed to send DCA notification email: {e}")
            
            # Trigger static file generation for successful transactions
            # This updates charts and data files on the website
            if transaction.status == "SUCCESS":
                try:
                    from dca_service.services.static_generator import trigger_static_generation
                    trigger_static_generation(background=True)
                    logger.info("Triggered static file generation after successful DCA transaction")
                except Exception as e:
                    logger.error(f"Failed to trigger static file generation: {e}")
                    # Don't re-raise - static generation failure shouldn't fail the transaction
            
            # Broadcast event to connected clients for immediate UI update
            try:
                from dca_service.sse import sse_manager
                sse_manager.broadcast("transaction_created", {
                    "id": transaction.id,
                    "amount_usd": executed_usd if transaction.status == "SUCCESS" else 0.0,
                    "amount_btc": executed_btc if transaction.status == "SUCCESS" else 0.0,
                    "price": executed_price if transaction.status == "SUCCESS" else decision.price_usd,
                    "source": source,
                    "status": transaction.status
                })
            except Exception as e:
                logger.warning(f"Failed to broadcast SSE event: {e}")
            
        except Exception as e:
            session.rollback()
            logger.exception(f"Fatal error in DCA execution: {e}")

    def _run_static_generation_job(self):
        """Run scheduled static analysis generation in the background."""
        try:
            from dca_service.services.static_generator import trigger_static_generation

            trigger_static_generation(background=True)
            logger.info("Triggered scheduled static file generation")
        except Exception as e:
            logger.error(f"Failed to trigger scheduled static generation: {e}")

    def _sync_trades_job(self):
        """
        Background job to sync trades from the active exchange.
        """
        try:
            # We need to run the async sync service synchronously here
            import asyncio
            from dca_service.services.sync_service import TradeSyncService
            
            async def run_sync():
                with Session(engine) as session:
                    service = TradeSyncService(session)
                    await service.sync_trades()
            
            asyncio.run(run_sync())
            
        except Exception as e:
            logger.error(f"Error in background trade sync: {e}")


# Global scheduler instance
scheduler = DCAScheduler()
