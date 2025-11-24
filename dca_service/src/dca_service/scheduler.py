"""
DCA Scheduler - Automatic execution of DCA transactions

Uses APScheduler to check every minute if a DCA transaction should be executed
based on the strategy configuration (execution_time_utc, execution_frequency).
"""
from datetime import datetime, timezone
from typing import Optional
import logging
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from dca_service.database import engine
from dca_service.models import DCAStrategy, DCATransaction
from dca_service.services.dca_engine import calculate_dca_decision

# Configure logging for scheduler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


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
            print("⚠ DCA Scheduler already running")
            logger.warning("Scheduler already running")
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
        print("✓ DCA Scheduler started - checking every minute")
        logger.info("DCA Scheduler started - checking every minute")
    
    def stop(self):
        """Stop the background scheduler"""
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        print("✓ DCA Scheduler stopped")
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
            logger.error(f"Error in DCA scheduler: {e}", exc_info=True)
    
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
            
            if not decision.can_execute:
                logger.info(f"DCA execution skipped: {decision.reason}")
                return
            
            # Calculate BTC amount
            btc_amount = decision.suggested_amount_usd / decision.price_usd if decision.price_usd > 0 else 0
            
            # Create transaction based on execution mode
            source = "SIMULATED" if strategy.execution_mode == "DRY_RUN" else "BINANCE"
            
            transaction = DCATransaction(
                status="SUCCESS",
                fiat_amount=decision.suggested_amount_usd,
                btc_amount=btc_amount,
                price=decision.price_usd,
                ahr999=decision.ahr999_value,
                notes=f"Automated {strategy.execution_frequency} DCA",
                intended_amount_usd=decision.suggested_amount_usd,
                executed_amount_usd=decision.suggested_amount_usd,
                executed_amount_btc=btc_amount,
                avg_execution_price_usd=decision.price_usd,
                fee_amount=0.0,
                fee_asset="USDC",
                source=source
            )
            
            session.add(transaction)
            session.commit()
            session.refresh(transaction)
            
            logger.info(
                f"DCA transaction executed: ${decision.suggested_amount_usd:.2f} USD "
                f"for {btc_amount:.8f} BTC at ${decision.price_usd:.2f} "
                f"(mode: {strategy.execution_mode})"
            )
            
            # Broadcast event to connected clients for immediate UI update
            try:
                from dca_service.sse import sse_manager
                sse_manager.broadcast("transaction_created", {
                    "id": transaction.id,
                    "amount_usd": decision.suggested_amount_usd,
                    "amount_btc": btc_amount,
                    "price": decision.price_usd,
                    "source": source
                })
            except Exception as e:
                logger.warning(f"Failed to broadcast SSE event: {e}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to execute DCA transaction: {e}", exc_info=True)


# Global scheduler instance
scheduler = DCAScheduler()
