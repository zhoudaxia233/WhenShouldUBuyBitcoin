"""
Wallet management API endpoints.
Handles cold wallet balance tracking and Binance hot wallet information.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import Optional

from dca_service.database import get_session
from dca_service.models import GlobalSettings, BinanceCredentials
from dca_service.api.schemas import WalletSummary, ColdWalletBalanceUpdate
from dca_service.services.binance_client import BinanceClient
from dca_service.services.security import decrypt_text
from dca_service.core.logging import logger
from sqlmodel import select

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _get_binance_client(session: Session) -> Optional[BinanceClient]:
    """
    Create authenticated Binance client from stored credentials.
    Prefers READ_ONLY credentials, falls back to TRADING if needed.
    
    Returns:
        BinanceClient instance or None if credentials not configured
    """
    # Try READ_ONLY credentials first
    creds = session.exec(
        select(BinanceCredentials).where(BinanceCredentials.credential_type == "READ_ONLY")
    ).first()
    
    # Fallback to TRADING credentials if READ_ONLY not found
    if not creds:
        creds = session.exec(
            select(BinanceCredentials).where(BinanceCredentials.credential_type == "TRADING")
        ).first()
    
    if not creds:
        logger.debug("No Binance credentials configured")
        return None
    
    try:
        api_key = decrypt_text(creds.api_key_encrypted)
        api_secret = decrypt_text(creds.api_secret_encrypted)
        return BinanceClient(api_key, api_secret)
    except Exception as e:
        logger.error(f"Failed to decrypt Binance credentials: {e}")
        return None


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
    
    # Try to get Binance data
    client = _get_binance_client(session)
    if client:
        try:
            # Fetch balances
            balances = await client.get_spot_balances(["BTC"])
            hot_wallet_balance = balances.get("BTC", 0.0)
            
            # Fetch current price
            current_price = await client.get_current_price("BTCUSDC")
            
            # Calculate average buy price (cost basis)
            hot_wallet_avg_price = await client.calculate_avg_buy_price("BTCUSDC")
            
            await client.close()
        except Exception as e:
            logger.error(f"Error fetching Binance data: {e}")
            if client:
                await client.close()
    else:
        # Fallback: try to get current price from data_fetcher if Binance not configured
        try:
            from whenshouldubuybitcoin.data_fetcher import get_realtime_btc_price
            _, current_price = get_realtime_btc_price()
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
async def get_wallet_summary(session: Session = Depends(get_session)):
    """
    Get comprehensive wallet information including:
    - Cold wallet balance (from database)
    - Hot wallet balance (from Binance)
    - Average buy price (calculated from Binance trade history)
    - Current BTC price
    - USD values for all holdings
    """
    return await fetch_wallet_summary(session)


@router.post("/cold-balance", response_model=WalletSummary)
async def update_cold_wallet_balance(
    update: ColdWalletBalanceUpdate,
    session: Session = Depends(get_session)
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
    return await get_wallet_summary(session)
