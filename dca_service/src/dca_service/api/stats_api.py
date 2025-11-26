from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List, Dict, Any
from datetime import datetime, timezone
import pandas as pd

from dca_service.database import get_session
from dca_service.models import DCATransaction, GlobalSettings

router = APIRouter()

# Hardcoded Bitcoin Wealth Distribution (Source: BitInfoCharts, Nov 2024)
# Format: (min_btc, max_btc, percentile_top)
# percentile_top means "if you have this much, you are in the top X%"
WEALTH_DISTRIBUTION = [
    (1000000, float('inf'), 0.00002), # Top 4 addresses
    (100000, 1000000, 0.0004),        # Top ~90 addresses
    (10000, 100000, 0.01),            # Top ~2000 addresses
    (1000, 10000, 0.04),              # Top ~16k addresses
    (100, 1000, 0.28),                # Top ~150k addresses
    (10, 100, 2.04),                  # Top ~1.3M addresses
    (1, 10, 12.65),                   # Top ~8M addresses
    (0.1, 1, 27.38),                  # Top ~17M addresses
    (0.01, 0.1, 48.66),               # Top ~30M addresses
    (0.001, 0.01, 69.94),             # Top ~43M addresses
    (0, 0.001, 100.0)                 # Everyone else
]

@router.get("/stats/distribution")
def get_wealth_distribution():
    """Return the hardcoded wealth distribution table."""
    return [
        {"tier": "> 1,000,000 BTC", "percentile": "Top 0.00002%"},
        {"tier": "100,000 - 1,000,000 BTC", "percentile": "Top 0.0004%"},
        {"tier": "10,000 - 100,000 BTC", "percentile": "Top 0.01%"},
        {"tier": "1,000 - 10,000 BTC", "percentile": "Top 0.04%"},
        {"tier": "100 - 1,000 BTC", "percentile": "Top 0.28%"},
        {"tier": "10 - 100 BTC", "percentile": "Top 2.04%"},
        {"tier": "1 - 10 BTC", "percentile": "Top 12.65%"},
        {"tier": "0.1 - 1 BTC", "percentile": "Top 27.38%"},
        {"tier": "0.01 - 0.1 BTC", "percentile": "Top 48.66%"},
        {"tier": "0.001 - 0.01 BTC", "percentile": "Top 69.94%"},
        {"tier": "< 0.001 BTC", "percentile": "Bottom 30%"}
    ]

@router.get("/stats/percentile")
async def get_user_percentile(session: Session = Depends(get_session)):
    """Calculate the user's wealth percentile based on total BTC holdings."""
    # Use the same logic as wallet summary to ensure consistency
    from dca_service.api.wallet_api import get_wallet_summary
    
    wallet_summary = await get_wallet_summary(session)
    total_btc = wallet_summary.total_btc
    
    # Determine Percentile
    percentile = 100.0
    for min_b, max_b, p_top in WEALTH_DISTRIBUTION:
        if total_btc >= min_b:
            percentile = p_top
            break
            
    return {
        "total_btc": total_btc,
        "percentile_top": percentile,
        "message": f"You are in the Top {percentile}% of Bitcoin Holders"
    }

@router.get("/stats/fees")
def get_total_fees(session: Session = Depends(get_session)):
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
def get_pnl_data(session: Session = Depends(get_session)):
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
