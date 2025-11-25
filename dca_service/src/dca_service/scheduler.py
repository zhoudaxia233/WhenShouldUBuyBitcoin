"""
DCA Scheduler - Automatic execution of DCA transactions

Uses APScheduler to check every minute if a DCA transaction should be executed
based on the strategy configuration (execution_time_utc, execution_frequency).
"""
from datetime import datetime, timezone
from typing import Optional
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from dca_service.database import engine
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision
from dca_service.core.logging import logger


class DCAScheduler:
    """
    Background scheduler for automatic DCA execution.
    
    Checks every minute if conditions are met to execute a DCA transaction:
    - Strategy is active
    - Current time matches execution_time_utc
    - Frequency matches (daily or correct day of week for weekly)
    - No transaction already executed today (for daily) or this week (for weekly)
    """
    
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
        
        self.scheduler.start()
        self.is_running = True
        logger.info("DCA Scheduler started - checking every minute")
    
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
        now = datetime.now(timezone.utc)
        
        if not strategy.is_active:
            return False
        
        # Parse execution time (format: "HH:MM")
        try:
            exec_hour, exec_minute = map(int, strategy.execution_time_utc.split(':'))
        except (ValueError, AttributeError):
            logger.error(f"Invalid execution_time_utc format: {strategy.execution_time_utc}")
            return False
        
        # Check if current time matches execution time (within the same minute)
        if now.hour != exec_hour or now.minute != exec_minute:
            return False
        
        # Check frequency-specific conditions
        if strategy.execution_frequency == "daily":
            return self._should_execute_daily(session, now)
        elif strategy.execution_frequency == "weekly":
            return self._should_execute_weekly(strategy, session, now)
        else:
            logger.error(f"Unknown execution frequency: {strategy.execution_frequency}")
            return False
    
    def _should_execute_daily(self, session: Session, now: datetime) -> bool:
        """
        Check if daily DCA should execute (no transaction today yet).
        
        Args:
            session: Database session
            now: Current UTC datetime
            
        Returns:
            True if no transaction executed today, False otherwise
        """
        # Check if we already executed today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        existing_tx = session.exec(
            select(DCATransaction)
            .where(DCATransaction.timestamp >= today_start)
            .where(DCATransaction.status == "SUCCESS")
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
        # Check if today is the configured day of week
        current_day = now.strftime('%A').lower()
        if current_day != strategy.execution_day_of_week:
            logger.debug(
                f"Not the configured day ({strategy.execution_day_of_week}), "
                f"today is {current_day}"
            )
            return False
        
        # Check if we already executed this week
        # Week starts on Monday (weekday 0)
        days_since_monday = now.weekday()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start.replace(day=now.day - days_since_monday)
        
        existing_tx = session.exec(
            select(DCATransaction)
            .where(DCATransaction.timestamp >= week_start)
            .where(DCATransaction.status == "SUCCESS")
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
            
            # Execute Real Trade if LIVE mode
            if strategy.execution_mode == "LIVE":
                try:
                    from dca_service.models import BinanceCredentials
                    from dca_service.services.security import decrypt_text
                    from dca_service.services.binance_client import BinanceClient
                    import asyncio
                    
                    # 1. Get TRADING credentials (not read-only)
                    creds = session.exec(
                        select(BinanceCredentials).where(BinanceCredentials.credential_type == "TRADING")
                    ).first()
                    if not creds or not creds.api_key_encrypted:
                        raise ValueError("Trading credentials not configured. Please add trading API keys in settings.")
                    
                    # 2. Decrypt both api_key and api_secret
                    api_key = decrypt_text(creds.api_key_encrypted)
                    api_secret = decrypt_text(creds.api_secret_encrypted)
                    
                    # 3. Define async execution wrapper
                    async def execute_live_trade():
                        client = BinanceClient(api_key, api_secret)
                        try:
                            # Use BTCUSDC as default symbol
                            return await client.create_market_buy_order("BTCUSDC", decision.suggested_amount_usd)
                        finally:
                            await client.close()
                    
                    # 4. Run async code synchronously
                    logger.info(f"LIVE MODE: Attempting to buy ${decision.suggested_amount_usd:.2f} of BTC on Binance...")
                    order_response = asyncio.run(execute_live_trade())
                    
                    # 5. Parse Response
                    # orderId = Binance order ID (for tracking)
                    # cummulativeQuoteQty = Total USD spent
                    # executedQty = Total BTC bought
                    binance_order_id = order_response.get("orderId")  # Save order ID
                    executed_usd = float(order_response.get("cummulativeQuoteQty", 0.0))
                    executed_btc = float(order_response.get("executedQty", 0.0))
                    
                    if executed_btc > 0:
                        executed_price = executed_usd / executed_btc
                    
                    source = "BINANCE"
                    logger.info(f"LIVE TRADE SUCCESSFUL: Order#{binance_order_id} - Bought {executed_btc:.8f} BTC for ${executed_usd:.2f}")
                    
                except Exception as e:
                    logger.error(f"LIVE Trading failed: {e}")
                    # Don't re-raise - we'll record as FAILED transaction instead
                    source = "BINANCE_FAILED"
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
                    binance_order_id=None  # Failed trades have no order ID
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
                    fee_amount=0.0,
                    fee_asset="USDC",
                    source=source,
                    binance_order_id=binance_order_id  # Save Binance order ID
                )
            
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
                    send_dca_notification(transaction, decision)
                except Exception as e:
                    logger.error(f"Failed to send DCA notification email: {e}")
            
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


# Global scheduler instance
scheduler = DCAScheduler()
