"""
Wallet management API endpoints.
Handles cold wallet balance tracking and active exchange hot wallet information.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlmodel import Session

from dca_service.database import get_session
from dca_service.models import GlobalSettings, User
from dca_service.api.schemas import WalletSummary, ColdWalletBalanceUpdate
from dca_service.services.security import decrypt_text
from dca_service.services.exchange_config import get_active_exchange, get_credentials, get_exchange_symbol
from dca_service.core.logging import logger
from dca_service.auth.dependencies import get_current_user

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _get_exchange_client(session: Session):
    """
    Create authenticated active-exchange client from stored credentials.
    Prefers READ_ONLY credentials, falls back to TRADING if needed.
    """
    exchange = get_active_exchange(session)
    creds = get_credentials(session, exchange, "READ_ONLY")
    if not creds:
        creds = get_credentials(session, exchange, "TRADING")
    
    if not creds:
        logger.debug(f"No {exchange} credentials configured")
        return None, exchange, get_exchange_symbol(exchange)
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
        if exchange == "KRAKEN":
            from dca_service.services.kraken_client import KrakenClient
            return KrakenClient(api_key, api_secret), exchange, get_exchange_symbol(exchange)
        from dca_service.services.binance_client import BinanceClient
        return BinanceClient(api_key, api_secret), exchange, get_exchange_symbol(exchange)
    except Exception as e:
        logger.error(f"Failed to decrypt {exchange} credentials: {e}")
        return None, exchange, get_exchange_symbol(exchange)


async def fetch_wallet_summary(session: Session) -> WalletSummary:
    """
    Fetch comprehensive wallet information.
    Reusable function for both API and internal services.
    """
    # Get cold wallet balance from singleton settings
    settings = session.get(GlobalSettings, 1)
    if not settings:
        # Initialize if doesn't exist (shouldn't happen with proper migration)
        logger.warning("GlobalSettings not found, initializing")
        settings = GlobalSettings(id=1, cold_wallet_balance=0.0)
        session.add(settings)
        session.commit()
    
    cold_wallet_balance = settings.cold_wallet_balance
    
    # Initialize hot wallet values
    hot_wallet_balance = 0.0
    hot_wallet_avg_price = 0.0
    current_price = 0.0
    
    client, exchange, exchange_symbol = _get_exchange_client(session)
    if client:
        try:
            # Fetch balances
            balances = await client.get_spot_balances(["BTC"])
            hot_wallet_balance = balances.get("BTC", 0.0)
            
            # Fetch current price
            current_price = await client.get_current_price(exchange_symbol)
            
            # Calculate average buy price (cost basis)
            hot_wallet_avg_price = await client.calculate_avg_buy_price(exchange_symbol)
            
            await client.close()
        except Exception as e:
            logger.error(f"Error fetching {exchange} data: {e}")
            if client:
                await client.close()
    else:
        # Fallback: try to get current price from the selected public exchange source.
        try:
            from whenshouldubuybitcoin.data_fetcher import get_realtime_btc_price_with_source
            _, current_price, _price_source = get_realtime_btc_price_with_source(exchange)
        except Exception as e:
            logger.warning(f"Could not fetch BTC price from fallback source: {e}")
            current_price = 0.0
    
    # Calculate totals
    total_btc = cold_wallet_balance + hot_wallet_balance
    cold_wallet_value = cold_wallet_balance * current_price
    hot_wallet_value = hot_wallet_balance * current_price
    total_value = total_btc * current_price
    
    return WalletSummary(
        cold_wallet_balance=cold_wallet_balance,
        hot_wallet_balance=hot_wallet_balance,
        hot_wallet_avg_price=hot_wallet_avg_price,
        total_btc=total_btc,
        current_price=current_price,
        cold_wallet_value_usd=cold_wallet_value,
        hot_wallet_value_usd=hot_wallet_value,
        total_value_usd=total_value
    )


@router.get("/summary", response_model=WalletSummary)
async def get_wallet_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Get comprehensive wallet information including:
    - Cold wallet balance (from database)
    - Hot wallet balance (from active exchange)
    - Average buy price (calculated from active exchange trade history)
    - Current BTC price
    - USD values for all holdings
    """
    return await fetch_wallet_summary(session)


@router.post("/cold-balance", response_model=WalletSummary)
async def update_cold_wallet_balance(
    update: ColdWalletBalanceUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Update the cold wallet balance.
    This directly sets the total BTC amount in cold storage.
    
    Returns the updated wallet summary.
    """
    settings = session.get(GlobalSettings, 1)
    if not settings:
        # Initialize if doesn't exist
        settings = GlobalSettings(id=1, cold_wallet_balance=0.0)
        session.add(settings)
    
    # Update balance
    settings.cold_wallet_balance = update.balance
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    
    logger.info(f"Cold wallet balance updated to {update.balance} BTC")
    
    # Return updated summary
    return await fetch_wallet_summary(session)
