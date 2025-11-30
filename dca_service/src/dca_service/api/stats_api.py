from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import pandas as pd
import re
import logging

from dca_service.database import get_session
from dca_service.models import DCATransaction, GlobalSettings, User
from dca_service.auth.dependencies import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_tier_range(tier_str: str) -> Optional[Tuple[float, float]]:
    """
    Parse tier string from distribution scraper to extract min_btc and max_btc.
    
    Examples:
        "1000000+" -> (1000000, float('inf'))
        "100000-1000000" -> (100000, 1000000)
        "[0.1 - 1 BTC)" -> (0.1, 1)
        "[0.001-0.01 BTC)" -> (0.001, 0.01)
    """
    try:
        tier_str = tier_str.strip()
        
        # Handle format like '[0.1 - 1 BTC)' or '[0.1-1 BTC)'
        # Remove brackets and 'BTC)' suffix
        tier_str = tier_str.replace('[', '').replace(']', '').replace('(', '').replace(')', '')
        if 'BTC' in tier_str:
            tier_str = tier_str.split('BTC')[0].strip()
        
        # Handle "X+" format (e.g., "1000000+")
        if tier_str.endswith('+'):
            min_btc = float(tier_str[:-1].replace(',', '').strip())
            return (min_btc, float('inf'))
        
        # Handle "X-Y" format (e.g., "100000-1000000" or "0.1 - 1")
        if '-' in tier_str:
            parts = tier_str.split('-')
            if len(parts) == 2:
                min_btc = float(parts[0].strip().replace(',', ''))
                max_btc = float(parts[1].strip().replace(',', ''))
                return (min_btc, max_btc)
        
        # Try to parse as a single number
        try:
            value = float(tier_str.replace(',', '').strip())
            return (value, float('inf'))
        except ValueError:
            pass
        
        logger.warning(f"Could not parse tier string: '{tier_str}'")
        return None
    except Exception as e:
        logger.warning(f"Error parsing tier string '{tier_str}': {e}")
        return None


def _parse_percentile_value(percentile_str: str) -> Optional[float]:
    """
    Parse percentile string to extract numeric value.
    
    Examples:
        "Top 27.38%" -> 27.38
        "Top 0.00002%" -> 0.00002
        "Top 100.0%" -> 100.0
    """
    try:
        # Extract number from strings like "Top 27.38%" or "Top 0.00002%"
        match = re.search(r'([\d.]+)', percentile_str)
        if match:
            return float(match.group(1))
        return None
    except Exception as e:
        logger.warning(f"Error parsing percentile string '{percentile_str}': {e}")
        return None


def _build_wealth_distribution_from_live_data() -> List[Tuple[float, float, float, str]]:
    """
    Build wealth distribution list from live scraped data.
    
    Behavior:
    - Fresh cache (< 24h): Returns cached data instantly
    - Expired cache (> 24h): Fetches new data, falls back to stale cache if fetch fails
    - No cache: Raises error (won't show bad data)
    
    Returns:
        List of (min_btc, max_btc, percentile_top, percentile_str) tuples, sorted by min_btc descending.
        percentile_top is float for comparison, percentile_str preserves original formatting.
        
    Raises:
        ValueError: If no distribution data is available (no cache and fetch failed)
    """
    from dca_service.services.distribution_scraper import fetch_distribution
    
    # fetch_distribution handles:
    # - Fresh cache: returns immediately
    # - Expired cache + fetch fails: returns stale cache
    # - No cache + fetch fails: raises ValueError
    distribution_data = fetch_distribution(use_cache=True)
    
    if not distribution_data:
        raise ValueError("No distribution data available")
    
    # Parse distribution data into (min_btc, max_btc, percentile_top, percentile_str) format
    wealth_dist = []
    for item in distribution_data:
        tier_str = item.get("tier", "")
        percentile_str = item.get("percentile", "")
        
        tier_range = _parse_tier_range(tier_str)
        percentile_value = _parse_percentile_value(percentile_str)
        
        if tier_range and percentile_value is not None:
            min_btc, max_btc = tier_range
            wealth_dist.append((min_btc, max_btc, percentile_value, percentile_str))
        else:
            logger.warning(f"Skipping invalid distribution item: tier={tier_str}, percentile={percentile_str}")
    
    if not wealth_dist:
        raise ValueError("Failed to parse any valid distribution data")
    
    # Sort by min_btc descending (largest first)
    wealth_dist.sort(key=lambda x: x[0], reverse=True)
    
    logger.info(f"Built wealth distribution from live data: {len(wealth_dist)} tiers")
    return wealth_dist

@router.get("/stats/distribution")
def get_wealth_distribution(current_user: User = Depends(get_current_user)):
    """Return the live wealth distribution table from BitInfoCharts."""
    from dca_service.services.distribution_scraper import fetch_distribution
    return fetch_distribution()

@router.get("/stats/percentile")
async def get_user_percentile(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Calculate the user's wealth percentile based on total BTC holdings.
    
    Uses live distribution data from BitInfoCharts:
    - Fresh cache (< 24h): Returns cached data instantly
    - Expired cache (> 24h): Fetches new data, falls back to stale cache if fetch fails
    - No cache: Raises HTTP 503 error (won't show bad data)
    """
    from fastapi import HTTPException
    from dca_service.api.wallet_api import get_wallet_summary
    
    # Use the same logic as wallet summary to ensure consistency
    wallet_summary = await get_wallet_summary(session)
    total_btc = wallet_summary.total_btc
    
    try:
        # Get wealth distribution (raises ValueError if no data available)
        wealth_distribution = _build_wealth_distribution_from_live_data()
        
        # Determine Percentile
        # Find the first tier where total_btc falls within the range [min_btc, max_btc)
        # Note: For the top tier with max_btc=inf, we only check min_btc
        percentile_value = 100.0
        percentile_str = "Top 100%"
        for min_b, max_b, p_top, p_str in wealth_distribution:
            if total_btc >= min_b:
                # Check upper bound (if max_b is not infinity)
                if max_b == float('inf') or total_btc < max_b:
                    percentile_value = p_top
                    percentile_str = p_str
                    break
                    
        return {
            "total_btc": total_btc,
            "percentile_top": percentile_value,
            "percentile_display": percentile_str,
            "message": f"You are in the {percentile_str} of Bitcoin Holders"
        }
        
    except ValueError as e:
        logger.error(f"Failed to get wealth distribution: {e}")
        # Return partial data instead of failing completely
        # This ensures the user at least sees their BTC total
        return {
            "total_btc": total_btc,
            "percentile_top": None,
            "percentile_display": "Data Unavailable",
            "message": "Wealth distribution data is currently unavailable"
        }

@router.get("/stats/fees")
def get_total_fees(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Get total fees paid across all transactions."""
    txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
    ).all()
    
    total_fees_usd = 0.0
    total_fees_btc = 0.0
    
    for tx in txs:
        fee_amount = tx.fee_amount or 0.0
        fee_asset = tx.fee_asset or "USDC"
        
        if fee_asset == "BTC":
            total_fees_btc += fee_amount
            # Approximate USD value using transaction price
            total_fees_usd += fee_amount * (tx.price or 0.0)
        else:  # USDC or USD
            total_fees_usd += fee_amount
    
    return {
        "total_fees_usd": total_fees_usd,
        "total_fees_btc": total_fees_btc,
        "transaction_count": len(txs)
    }

@router.get("/stats/pnl")
def get_pnl_data(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get PnL time-series data.
    Returns:
        dates: List of dates
        invested: List of cumulative USD invested
        value: List of portfolio value (BTC * Price)
        avg_price: List of average buy price
        fees: List of cumulative fees paid
    """
    # Fetch all successful transactions sorted by time
    txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
        .order_by(DCATransaction.timestamp)
    ).all()
    
    if not txs:
        return {"dates": [], "invested": [], "value": [], "avg_price": [], "fees": []}
    
    data = []
    cumulative_btc = 0.0
    cumulative_cost = 0.0
    cumulative_fees = 0.0
    
    for tx in txs:
        cumulative_btc += (tx.btc_amount or 0.0)
        cumulative_cost += (tx.fiat_amount or 0.0)
        
        # Add fees (approximate USD value for BTC fees)
        fee_amount = tx.fee_amount or 0.0
        fee_asset = tx.fee_asset or "USDC"
        if fee_asset == "BTC":
            cumulative_fees += fee_amount * (tx.price or 0.0)
        else:
            cumulative_fees += fee_amount
        
        current_price = tx.price or 0.0
        current_value = cumulative_btc * current_price
        
        avg_price = cumulative_cost / cumulative_btc if cumulative_btc > 0 else 0.0
        
        data.append({
            "date": tx.timestamp.isoformat(),
            "invested": cumulative_cost,
            "value": current_value,
            "btc_balance": cumulative_btc,
            "avg_price": avg_price,
            "fees": cumulative_fees
        })
        
    return {
        "dates": [d["date"] for d in data],
        "invested": [d["invested"] for d in data],
        "value": [d["value"] for d in data],
        "avg_price": [d["avg_price"] for d in data],
        "fees": [d["fees"] for d in data]
    }
