from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import pandas as pd
import httpx
import math
import json
import hashlib
import logging
import csv
from pathlib import Path
from dca_service.config import settings

from dca_service.database import get_session
from dca_service.models import DCATransaction, User, SummaryApiSettings
from dca_service.auth.dependencies import get_current_user
from dca_service.services.security import decrypt_text

router = APIRouter()
logger = logging.getLogger(__name__)
TRADING_STYLE_AI_CACHE: Dict[str, Dict[str, Any]] = {}
TRADING_STYLE_AI_PROMPT_VERSION = "v2_concise_chill"


def _normalize_language(language: str | None) -> str:
    lang = (language or "").strip().lower()
    return "zh" if lang.startswith("zh") else "en"


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


def _effective_fiat_amount(tx: DCATransaction) -> float:
    return float(tx.executed_amount_usd or tx.fiat_amount or 0.0)


def _effective_btc_amount(tx: DCATransaction) -> float:
    return float(tx.executed_amount_btc or tx.btc_amount or 0.0)


def _effective_price(tx: DCATransaction) -> float:
    return float(tx.avg_execution_price_usd or tx.price or 0.0)


def _fee_to_usd(tx: DCATransaction, price_usd: float) -> float:
    fee_amount = float(tx.fee_amount or 0.0)
    fee_asset = (tx.fee_asset or "USDC").upper()
    if fee_amount <= 0:
        return 0.0
    if fee_asset == "BTC":
        return fee_amount * max(price_usd, 0.0)
    return fee_amount


def _safe_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return None
    xs_series = pd.Series(xs, dtype=float)
    ys_series = pd.Series(ys, dtype=float)
    if float(xs_series.std(ddof=0)) == 0.0 or float(ys_series.std(ddof=0)) == 0.0:
        return None
    try:
        corr = xs_series.corr(ys_series)
        if corr is None or math.isnan(corr):
            return None
        return float(corr)
    except Exception:
        return None


def _safe_median(values: List[float], fallback: float = 0.0) -> float:
    if not values:
        return fallback
    return float(pd.Series(values, dtype=float).median())


def _safe_mean(values: List[float], fallback: float = 0.0) -> float:
    if not values:
        return fallback
    return float(pd.Series(values, dtype=float).mean())


def _classify_relative_amount(relative_amount: float) -> str:
    if relative_amount >= 2.0:
        return "aggressive"
    if relative_amount >= 1.35:
        return "large"
    if relative_amount <= 0.65:
        return "small"
    return "normal"


def _classify_price_position(price_position: float) -> str:
    if price_position <= 0.2:
        return "near_past_low"
    if price_position <= 0.45:
        return "lower_half"
    if price_position <= 0.8:
        return "upper_half"
    return "near_past_high"


def _aggregate_behavior_events(transactions: List[DCATransaction]) -> Dict[str, Any]:
    """
    Convert raw transaction fills into behavior events.
    Key rule:
    - Same binance_order_id => one event (split fills aggregated).
    - No order_id => keep as individual event.
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []

    for idx, tx in enumerate(transactions):
        amount_usd = _effective_fiat_amount(tx)
        amount_btc = _effective_btc_amount(tx)
        price_usd = _effective_price(tx)
        timestamp = tx.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        if tx.binance_order_id is not None:
            key = f"order:{tx.binance_order_id}"
            event_type = "ORDER"
        else:
            fallback_id = tx.id if tx.id is not None else idx
            key = f"tx:{fallback_id}"
            event_type = "SINGLE"

        if key not in grouped:
            grouped[key] = {
                "event_key": key,
                "event_type": event_type,
                "binance_order_id": tx.binance_order_id,
                "timestamp_start": timestamp,
                "timestamp_end": timestamp,
                "fill_count": 0,
                "amount_usd": 0.0,
                "amount_btc": 0.0,
                "fee_usd": 0.0,
                "weight_for_price": 0.0,
                "weighted_price_sum": 0.0,
                "tx_ids": [],
                "trade_ids": [],
                "sources": set(),
            }
            ordered_keys.append(key)

        group = grouped[key]
        group["timestamp_start"] = min(group["timestamp_start"], timestamp)
        group["timestamp_end"] = max(group["timestamp_end"], timestamp)
        group["fill_count"] += 1
        group["amount_usd"] += amount_usd
        group["amount_btc"] += amount_btc
        group["fee_usd"] += _fee_to_usd(tx, price_usd)
        group["tx_ids"].append(tx.id)
        if tx.binance_trade_id is not None:
            group["trade_ids"].append(tx.binance_trade_id)
        group["sources"].add(tx.source or "UNKNOWN")

        weight = amount_usd if amount_usd > 0 else amount_btc
        if weight > 0:
            group["weight_for_price"] += weight
            group["weighted_price_sum"] += price_usd * weight

    events: List[Dict[str, Any]] = []
    for key in ordered_keys:
        group = grouped[key]
        weight = group["weight_for_price"]
        if weight > 0:
            avg_price = group["weighted_price_sum"] / weight
        else:
            avg_price = 0.0

        events.append(
            {
                "event_key": group["event_key"],
                "event_type": group["event_type"],
                "binance_order_id": group["binance_order_id"],
                "timestamp": group["timestamp_start"],
                "timestamp_end": group["timestamp_end"],
                "fill_count": int(group["fill_count"]),
                "amount_usd": float(group["amount_usd"]),
                "amount_btc": float(group["amount_btc"]),
                "avg_price_usd": float(avg_price),
                "fee_usd": float(group["fee_usd"]),
                "source_types": sorted(group["sources"]),
                "tx_ids": [tid for tid in group["tx_ids"] if tid is not None],
                "trade_ids": group["trade_ids"],
            }
        )

    events.sort(key=lambda e: e["timestamp"])

    split_event_count = sum(1 for e in events if e["fill_count"] > 1)
    return {
        "events": events,
        "raw_fill_count": len(transactions),
        "event_count": len(events),
        "split_event_count": split_event_count,
        "split_fill_extra_count": len(transactions) - len(events),
    }


def _trading_style_source_signature(events: List[Dict[str, Any]]) -> str:
    canonical = []
    for e in events:
        canonical.append(
            {
                "binance_order_id": e.get("binance_order_id"),
                "timestamp": e.get("timestamp").isoformat() if isinstance(e.get("timestamp"), datetime) else str(e.get("timestamp")),
                "timestamp_end": e.get("timestamp_end").isoformat() if isinstance(e.get("timestamp_end"), datetime) else str(e.get("timestamp_end")),
                "fill_count": e.get("fill_count"),
                "amount_usd": round(float(e.get("amount_usd", 0.0)), 8),
                "amount_btc": round(float(e.get("amount_btc", 0.0)), 12),
                "avg_price_usd": round(float(e.get("avg_price_usd", 0.0)), 8),
                "fee_usd": round(float(e.get("fee_usd", 0.0)), 8),
                "source_types": e.get("source_types", []),
                "trade_ids": e.get("trade_ids", []),
            }
        )
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_behavior_analysis(events: List[Dict[str, Any]], aggregate_meta: Dict[str, Any]) -> Dict[str, Any]:
    if not events:
        return {
            "summary": {
                "raw_fill_count": aggregate_meta.get("raw_fill_count", 0),
                "behavior_event_count": 0,
                "split_event_count": 0,
                "split_fill_extra_count": 0,
                "avg_fills_per_event": 0.0,
                "total_invested_usd": 0.0,
                "total_btc": 0.0,
                "analysis_window_days": 0.0,
                "events_per_30d": 0.0,
                "median_interval_days": None,
                "avg_event_usd": 0.0,
                "event_amount_cv": 0.0,
                "high_zone_buy_ratio": 0.0,
                "low_zone_buy_ratio": 0.0,
                "burst_trading_ratio": 0.0,
                "size_price_position_corr": None,
                "largest_event_share": 0.0,
                "top3_event_share": 0.0,
                "weekend_ratio": 0.0,
                "manual_event_ratio": 0.0,
                "dca_event_ratio": 0.0,
            },
            "style_tags": ["No Data"],
            "issues": [{"severity": "info", "title": "No transactions", "detail": "No successful buy transaction found."}],
            "event_diagnostics": [],
        }

    event_amounts = [max(e["amount_usd"], 0.0) for e in events]
    timestamps = [e["timestamp"] for e in events]

    intervals_days: List[float] = []
    high_zone_count = 0
    low_zone_count = 0
    burst_count = 0
    weekend_count = 0
    manual_count = 0
    dca_count = 0
    price_positions: List[float] = []

    diagnostics: List[Dict[str, Any]] = []
    for idx, event in enumerate(events):
        ts = event["timestamp"]
        if ts.weekday() >= 5:
            weekend_count += 1
        if "MANUAL" in event["source_types"]:
            manual_count += 1
        if "DCA" in event["source_types"]:
            dca_count += 1

        prev_event = events[idx - 1] if idx > 0 else None
        interval_days = None
        if prev_event is not None:
            interval_days = (ts - prev_event["timestamp"]).total_seconds() / 86400.0
            intervals_days.append(interval_days)
            if interval_days <= 2.0:
                burst_count += 1

        past_events = events[:idx]
        past_window = events[max(0, idx - 10):idx]

        past_window_amounts = [max(e["amount_usd"], 0.0) for e in past_window if e["amount_usd"] > 0]
        baseline_amount = _safe_median(past_window_amounts, fallback=max(event["amount_usd"], 1e-9))
        relative_amount = event["amount_usd"] / baseline_amount if baseline_amount > 0 else 1.0
        relative_amount_label = _classify_relative_amount(relative_amount)

        past_prices = [max(e["avg_price_usd"], 0.0) for e in past_events if e["avg_price_usd"] > 0]
        historical_prices = past_prices + [max(event["avg_price_usd"], 0.0)]
        if historical_prices:
            hist_min = min(historical_prices)
            hist_max = max(historical_prices)
        else:
            hist_min = 0.0
            hist_max = 0.0
        if hist_max > hist_min:
            price_position = (event["avg_price_usd"] - hist_min) / (hist_max - hist_min)
        else:
            price_position = 0.5
        price_positions.append(float(price_position))

        if price_position >= 0.75:
            high_zone_count += 1
        if price_position <= 0.25:
            low_zone_count += 1

        past_median_price = _safe_median(past_prices, fallback=event["avg_price_usd"])
        if past_median_price > 0:
            price_vs_past_median_pct = ((event["avg_price_usd"] - past_median_price) / past_median_price) * 100.0
        else:
            price_vs_past_median_pct = 0.0

        diagnostics.append(
            {
                "event_time": ts.isoformat(),
                "event_key": event["event_key"],
                "event_type": event["event_type"],
                "binance_order_id": event["binance_order_id"],
                "amount_usd": event["amount_usd"],
                "amount_btc": event["amount_btc"],
                "avg_price_usd": event["avg_price_usd"],
                "fill_count": event["fill_count"],
                "fee_usd": event["fee_usd"],
                "source_types": event["source_types"],
                "interval_since_prev_days": interval_days,
                "relative_amount_to_past_median": relative_amount,
                "relative_amount_label": relative_amount_label,
                "price_position_in_past_range": float(price_position),
                "price_position_label": _classify_price_position(float(price_position)),
                "price_vs_past_median_pct": float(price_vs_past_median_pct),
            }
        )

    total_invested_usd = float(sum(event_amounts))
    total_btc = float(sum(max(e["amount_btc"], 0.0) for e in events))
    first_ts = timestamps[0]
    last_ts = timestamps[-1]
    span_days = max((last_ts - first_ts).total_seconds() / 86400.0, 1.0)
    event_count = len(events)

    event_amount_mean = _safe_mean(event_amounts, fallback=0.0)
    event_amount_std = float(pd.Series(event_amounts, dtype=float).std(ddof=0)) if event_amounts else 0.0
    event_amount_cv = (event_amount_std / event_amount_mean) if event_amount_mean > 0 else 0.0

    sorted_amounts_desc = sorted(event_amounts, reverse=True)
    largest_event_share = (sorted_amounts_desc[0] / total_invested_usd) if total_invested_usd > 0 and sorted_amounts_desc else 0.0
    top3_event_share = (sum(sorted_amounts_desc[:3]) / total_invested_usd) if total_invested_usd > 0 and sorted_amounts_desc else 0.0

    summary = {
        "raw_fill_count": int(aggregate_meta.get("raw_fill_count", event_count)),
        "behavior_event_count": int(event_count),
        "split_event_count": int(aggregate_meta.get("split_event_count", 0)),
        "split_fill_extra_count": int(aggregate_meta.get("split_fill_extra_count", 0)),
        "avg_fills_per_event": (aggregate_meta.get("raw_fill_count", event_count) / event_count) if event_count > 0 else 0.0,
        "total_invested_usd": total_invested_usd,
        "total_btc": total_btc,
        "analysis_window_days": float(span_days),
        "events_per_30d": float((event_count / span_days) * 30.0),
        "median_interval_days": (_safe_median(intervals_days) if intervals_days else None),
        "avg_event_usd": float(event_amount_mean),
        "event_amount_cv": float(event_amount_cv),
        "high_zone_buy_ratio": float(high_zone_count / event_count) if event_count > 0 else 0.0,
        "low_zone_buy_ratio": float(low_zone_count / event_count) if event_count > 0 else 0.0,
        "burst_trading_ratio": float(burst_count / len(intervals_days)) if intervals_days else 0.0,
        "size_price_position_corr": _safe_corr(event_amounts, price_positions),
        "largest_event_share": float(largest_event_share),
        "top3_event_share": float(top3_event_share),
        "weekend_ratio": float(weekend_count / event_count) if event_count > 0 else 0.0,
        "manual_event_ratio": float(manual_count / event_count) if event_count > 0 else 0.0,
        "dca_event_ratio": float(dca_count / event_count) if event_count > 0 else 0.0,
    }

    style_tags: List[str] = []
    if summary["low_zone_buy_ratio"] >= summary["high_zone_buy_ratio"] + 0.1:
        style_tags.append("Dip Buyer")
    if summary["high_zone_buy_ratio"] >= summary["low_zone_buy_ratio"] + 0.1:
        style_tags.append("Momentum Chaser")
    if summary["event_amount_cv"] <= 0.25:
        style_tags.append("Fixed-size DCA")
    if summary["burst_trading_ratio"] >= 0.45 and event_count >= 8:
        style_tags.append("Burst Trader")
    if summary["manual_event_ratio"] >= 0.7:
        style_tags.append("Manual Dominant")
    if not style_tags:
        style_tags.append("Balanced DCA")

    issues: List[Dict[str, str]] = []
    if event_count < 8:
        issues.append(
            {
                "severity": "info",
                "title": "Limited sample size",
                "detail": "Behavior interpretation confidence is limited because the event count is still small.",
            }
        )

    if summary["high_zone_buy_ratio"] >= 0.55 and summary["high_zone_buy_ratio"] > summary["low_zone_buy_ratio"] + 0.15:
        issues.append(
            {
                "severity": "warning",
                "title": "Possible high-price chasing",
                "detail": "A large share of buys happened near the top of your historical range at the moment of execution.",
            }
        )

    corr = summary["size_price_position_corr"]
    if corr is not None and corr >= 0.25 and event_count >= 6:
        issues.append(
            {
                "severity": "warning",
                "title": "Larger size at higher prices",
                "detail": "Position size tends to increase when your own observed price range is already in upper zones.",
            }
        )

    if summary["burst_trading_ratio"] >= 0.45 and event_count >= 8:
        issues.append(
            {
                "severity": "warning",
                "title": "High burst frequency",
                "detail": "Many trades happen within 48 hours of each other, which may indicate reactive execution.",
            }
        )

    if summary["largest_event_share"] >= 0.35:
        issues.append(
            {
                "severity": "warning",
                "title": "Concentrated single-event risk",
                "detail": "Your largest event contributes over 35% of total invested amount.",
            }
        )

    if summary["event_amount_cv"] >= 0.9 and event_count >= 8:
        issues.append(
            {
                "severity": "warning",
                "title": "Inconsistent sizing",
                "detail": "Sizing volatility is high, making risk and outcome attribution harder.",
            }
        )

    if summary["split_event_count"] > 0:
        issues.append(
            {
                "severity": "info",
                "title": "Split fills detected",
                "detail": "Some orders were split into multiple fills and have been merged into single behavior events for this analysis.",
            }
        )

    return {
        "summary": summary,
        "style_tags": style_tags,
        "issues": issues,
        "event_diagnostics": diagnostics,
    }


def _run_ai_style_analysis(
    session: Session,
    analysis_data: Dict[str, Any],
    include_ai: bool,
    *,
    language: str,
    source_signature: str,
) -> Dict[str, Any]:
    normalized_language = _normalize_language(language)
    status = {
        "attempted": False,
        "success": False,
        "reason": "",
        "provider": None,
        "model": None,
        "language": normalized_language,
        "cache_hit": False,
        "source_signature": source_signature,
        "prompt_version": TRADING_STYLE_AI_PROMPT_VERSION,
    }
    if not include_ai:
        status["reason"] = "AI analysis skipped by request."
        return {"status": status, "analysis": None}

    cache_key = f"{normalized_language}:{source_signature}:{TRADING_STYLE_AI_PROMPT_VERSION}"
    cached = TRADING_STYLE_AI_CACHE.get(cache_key)
    if cached and isinstance(cached.get("analysis"), str) and cached.get("analysis"):
        status["success"] = True
        status["cache_hit"] = True
        status["reason"] = "Source unchanged. Reused cached AI analysis."
        status["provider"] = cached.get("provider")
        status["model"] = cached.get("model")
        return {"status": status, "analysis": cached["analysis"]}

    summary_settings = session.exec(select(SummaryApiSettings)).first()
    if not summary_settings:
        status["reason"] = "Summary API settings are not configured."
        return {"status": status, "analysis": None}
    if not summary_settings.is_enabled:
        status["reason"] = "Summary API is disabled in settings."
        return {"status": status, "analysis": None}

    provider = (summary_settings.provider or "openai").strip().lower()
    model = (summary_settings.model or "gpt-4o-mini").strip()
    base_url = (summary_settings.base_url or "https://api.openai.com/v1").strip()
    status["provider"] = provider
    status["model"] = model

    if provider != "openai":
        status["reason"] = f"Unsupported provider: {provider}"
        return {"status": status, "analysis": None}

    try:
        api_key = decrypt_text(summary_settings.api_key_encrypted)
    except Exception as e:
        status["reason"] = f"Failed to decrypt API key: {e}"
        return {"status": status, "analysis": None}

    if not api_key:
        status["reason"] = "Missing API key."
        return {"status": status, "analysis": None}

    status["attempted"] = True
    endpoint = base_url.rstrip("/") + "/chat/completions"

    payload_for_model = {
        "summary": analysis_data.get("summary", {}),
        "style_tags": analysis_data.get("style_tags", []),
        "issues": analysis_data.get("issues", []),
        "event_diagnostics": analysis_data.get("event_diagnostics", [])[-120:],
        "method_constraints": analysis_data.get("method_constraints", {}),
    }
    user_payload_text = json.dumps(payload_for_model, ensure_ascii=False)

    if normalized_language == "zh":
        system_prompt = (
            "你是BTC买入执行行为分析师。"
            "语气要简明、chill、像朋友复盘，不要官话。"
            "必须严格避免后视偏差。"
            "每个行为只能基于当时和之前可见信息评价。"
            "只使用提供的指标与诊断数据。"
            "输出用中文Markdown，控制在8-12行以内。"
            "结构固定为："
            "1) 风格判断（2-3句）"
            "2) 主要问题（最多3条，按严重度）"
            "3) 下一步建议（最多4条，可直接执行）。"
        )
        user_prompt = (
            "下面是用户交易行为统计数据（同一订单ID拆单已合并为一个行为事件）。\n"
            "请基于这些数据分析交易风格与潜在问题，禁止使用未来信息倒推过去决策。\n\n"
            f"{user_payload_text}"
        )
    else:
        system_prompt = (
            "You are a BTC buy-execution behavior analyst. "
            "Use a concise, chill, coach-like tone. No corporate fluff. "
            "You must strictly avoid hindsight bias. "
            "Each action can only be judged using information available at that time and earlier history. "
            "Use only the supplied metrics and diagnostics. "
            "Respond in Markdown in 8-12 lines max with sections: "
            "1) Style Assessment (2-3 short sentences) "
            "2) Key Issues (max 3, ranked by severity) "
            "3) Actionable Improvements (max 4)."
        )
        user_prompt = (
            "Below is the user's trading behavior dataset (split fills with same order ID are merged as one event).\n"
            "Analyze style and potential problems using only these metrics. No hindsight bias.\n\n"
            f"{user_payload_text}"
        )

    try:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )

        if response.status_code >= 400:
            status["reason"] = f"AI provider HTTP {response.status_code}"
            return {"status": status, "analysis": None}

        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            status["reason"] = "AI response has no choices."
            return {"status": status, "analysis": None}
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not content:
            status["reason"] = "AI response has empty content."
            return {"status": status, "analysis": None}

        status["success"] = True
        status["reason"] = ""
        TRADING_STYLE_AI_CACHE[cache_key] = {
            "analysis": content,
            "provider": provider,
            "model": model,
            "language": normalized_language,
            "source_signature": source_signature,
            "prompt_version": TRADING_STYLE_AI_PROMPT_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"status": status, "analysis": content}
    except Exception as e:
        status["reason"] = f"AI call failed: {e}"
        return {"status": status, "analysis": None}


@router.get("/stats/trading-style")
def get_trading_style_analysis(
    include_ai: bool = Query(default=True),
    language: str = Query(default="en"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Analyze transaction behavior style.

    Important:
    - Split fills with same binance_order_id are merged into one behavior event.
    - Diagnostics are built with no hindsight (event-time + prior history only).
    """
    txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
        .order_by(DCATransaction.timestamp)
    ).all()

    buy_txs = []
    for tx in txs:
        amount_usd = _effective_fiat_amount(tx)
        amount_btc = _effective_btc_amount(tx)
        if amount_usd > 0 and amount_btc > 0:
            buy_txs.append(tx)

    aggregate_meta = _aggregate_behavior_events(buy_txs)
    source_signature = _trading_style_source_signature(aggregate_meta["events"])
    behavior_data = _build_behavior_analysis(aggregate_meta["events"], aggregate_meta)
    behavior_data["method_constraints"] = {
        "split_fill_handling": "Same binance_order_id merged into one event.",
        "no_hindsight": "Each event diagnostics use only event-time and prior events.",
    }
    behavior_data["source_signature"] = source_signature

    ai_result = _run_ai_style_analysis(
        session,
        behavior_data,
        include_ai=include_ai,
        language=language,
        source_signature=source_signature,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "language": _normalize_language(language),
        "source_signature": source_signature,
        "analysis_data": behavior_data,
        "ai_status": ai_result["status"],
        "ai_analysis": ai_result["analysis"],
    }
