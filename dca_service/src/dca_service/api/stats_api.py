from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import pandas as pd
import re
import logging
import csv
from pathlib import Path
from dca_service.config import settings

from dca_service.database import get_session
from dca_service.models import DCATransaction, GlobalSettings, User
from dca_service.auth.dependencies import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_metrics_csv_path() -> Path:
    """Resolve metrics CSV path using the same conventions as metrics provider."""
    csv_path_str = settings.METRICS_CSV_PATH
    csv_path = Path(csv_path_str)
    if csv_path.is_absolute():
        return csv_path

    # dca_service/src/dca_service/api/stats_api.py -> dca_service/
    dca_service_dir = Path(__file__).resolve().parent.parent.parent.parent
    if csv_path_str.startswith("../"):
        relative_part = csv_path_str[3:]
        resolved = (dca_service_dir.parent / relative_part).resolve()
    else:
        resolved = (dca_service_dir / csv_path_str).resolve()

    if not resolved.exists():
        alt_path = Path(csv_path_str)
        if alt_path.exists():
            return alt_path.resolve()
    return resolved


def _build_market_price_series(
    first_tx_time: datetime,
    tx_dates: List[str],
    tx_prices: List[float],
    tx_avg_prices: List[float],
) -> Tuple[List[str], List[float], List[float]]:
    """
    Build continuous market price series from first buy date to today.
    Falls back to transaction points if CSV is unavailable.
    """
    first_date = first_tx_time.date()
    today = datetime.now(timezone.utc).date()

    try:
        csv_path = _resolve_metrics_csv_path()
        if not csv_path.exists():
            raise FileNotFoundError(f"Metrics CSV not found: {csv_path}")

        market_dates: List[str] = []
        market_prices: List[float] = []

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date_str = row.get("date")
                price_str = row.get("close_price")
                if not date_str or not price_str:
                    continue
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d").date()
                    p = float(price_str)
                except (ValueError, TypeError):
                    continue
                if d < first_date or d > today:
                    continue
                market_dates.append(d.isoformat())
                market_prices.append(p)

        if not market_dates:
            raise ValueError("No market rows in selected range")

        # Build average-cost timeline as step function over market dates.
        tx_daily_avg: Dict[str, float] = {}
        for d, avg in zip(tx_dates, tx_avg_prices):
            tx_daily_avg[d[:10]] = avg

        avg_timeline: List[float] = []
        running_avg = tx_avg_prices[0] if tx_avg_prices else 0.0
        for d in market_dates:
            if d in tx_daily_avg:
                running_avg = tx_daily_avg[d]
            avg_timeline.append(running_avg)

        return market_dates, market_prices, avg_timeline
    except Exception as e:
        logger.warning(f"Falling back to tx-only price series for stats chart: {e}")
        return tx_dates, tx_prices, tx_avg_prices





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
    from dca_service.services.distribution_scraper import fetch_distribution, parse_tier_range, parse_percentile_value
    
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
        
        tier_range = parse_tier_range(tier_str)
        percentile_value = parse_percentile_value(percentile_str)
        
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
        prices: List of BTC price at each transaction point
        purchase_btc: List of BTC amount purchased per transaction
        purchase_usd: List of USD amount invested per transaction
        btc_balance: List of cumulative BTC balance over time
    """
    # Fetch all successful transactions sorted by time
    txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
        .order_by(DCATransaction.timestamp)
    ).all()
    
    if not txs:
        return {
            "dates": [],
            "invested": [],
            "value": [],
            "avg_price": [],
            "fees": [],
            "prices": [],
            "purchase_btc": [],
            "purchase_usd": [],
            "btc_balance": [],
            "market_dates": [],
            "market_prices": [],
            "avg_price_timeline": [],
        }
    
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
            "fees": cumulative_fees,
            "current_price": current_price,
            "purchase_btc": tx.btc_amount or 0.0,
            "purchase_usd": tx.fiat_amount or 0.0,
        })

    tx_dates = [d["date"] for d in data]
    tx_prices = [d["current_price"] for d in data]
    tx_avg_prices = [d["avg_price"] for d in data]
    market_dates, market_prices, avg_price_timeline = _build_market_price_series(
        first_tx_time=txs[0].timestamp,
        tx_dates=tx_dates,
        tx_prices=tx_prices,
        tx_avg_prices=tx_avg_prices,
    )
        
    return {
        "dates": tx_dates,
        "invested": [d["invested"] for d in data],
        "value": [d["value"] for d in data],
        "avg_price": tx_avg_prices,
        "fees": [d["fees"] for d in data],
        "prices": tx_prices,
        "purchase_btc": [d["purchase_btc"] for d in data],
        "purchase_usd": [d["purchase_usd"] for d in data],
        "btc_balance": [d["btc_balance"] for d in data],
        "market_dates": market_dates,
        "market_prices": market_prices,
        "avg_price_timeline": avg_price_timeline,
    }
