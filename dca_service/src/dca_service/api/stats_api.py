from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlmodel import Session, select
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta
import pandas as pd
import httpx
import math
import json
import hashlib
import logging
import csv
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from dca_service.config import settings

from dca_service.database import get_session, engine
from dca_service.models import (
    DCATransaction,
    User,
    SummaryApiSettings,
    DCAStrategy,
    BinanceCredentials,
)
from dca_service.auth.dependencies import get_current_user
from dca_service.services.security import decrypt_text
from dca_service.services.binance_client import BinanceClient

router = APIRouter()
logger = logging.getLogger(__name__)
TRADING_STYLE_AI_CACHE: Dict[str, Dict[str, Any]] = {}
TRADING_STYLE_AI_PROMPT_VERSION = "v2_concise_chill"
BINANCE_PUBLIC_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_PRICE_CACHE_TTL_SECONDS = 3
BINANCE_SAFE_POLL_SECONDS = 3
BINANCE_TICKER_REQUEST_WEIGHT = 2
BINANCE_PRICE_CACHE: Dict[str, Dict[str, Any]] = {}


def _normalize_language(language: str | None) -> str:
    lang = (language or "").strip().lower()
    return "zh" if lang.startswith("zh") else "en"


class AddPositionAdviceRequest(BaseModel):
    amount_usdc: float = Field(gt=0)
    current_price_usd: Optional[float] = Field(default=None, gt=0)
    symbol: str = Field(default="BTCUSDC", min_length=6, max_length=20)


class AddPositionConfirmRequest(BaseModel):
    amount_usdc: float = Field(gt=0)
    price_usd: float = Field(gt=0)
    symbol: str = Field(default="BTCUSDC", min_length=6, max_length=20)
    notes: Optional[str] = Field(default=None, max_length=300)


def _normalize_symbol(symbol: str | None) -> str:
    normalized = (symbol or "BTCUSDC").strip().upper()
    return normalized or "BTCUSDC"


def _extract_http_error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("msg")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
            err = data.get("error")
            if isinstance(err, dict):
                err_msg = err.get("message")
                if isinstance(err_msg, str) and err_msg.strip():
                    return err_msg.strip()
            message = data.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    except Exception:
        pass
    text = (resp.text or "").strip().replace("\n", " ")
    return text[:280] if text else ""


def _fetch_binance_realtime_price(symbol: str) -> Dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    now_utc = datetime.now(timezone.utc)

    cache_entry = BINANCE_PRICE_CACHE.get(normalized_symbol)
    if cache_entry and cache_entry.get("expires_at") and cache_entry["expires_at"] > now_utc:
        return {
            "symbol": normalized_symbol,
            "price": float(cache_entry["price"]),
            "updated_at": cache_entry["updated_at"],
            "cache_hit": True,
            "stale_fallback": False,
            "source": "binance_public_api",
            "cache_ttl_seconds": BINANCE_PRICE_CACHE_TTL_SECONDS,
            "poll_recommendation_seconds": BINANCE_SAFE_POLL_SECONDS,
            "request_weight": BINANCE_TICKER_REQUEST_WEIGHT,
        }

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.get(BINANCE_PUBLIC_TICKER_URL, params={"symbol": normalized_symbol})

        if response.status_code >= 400:
            detail = _extract_http_error_detail(response)
            reason = f"Binance ticker HTTP {response.status_code}"
            if detail:
                reason = f"{reason}: {detail}"
            raise ValueError(reason)

        body = response.json()
        price = float(body["price"])
        if price <= 0:
            raise ValueError("Binance returned non-positive price")

        updated_at = now_utc.isoformat()
        BINANCE_PRICE_CACHE[normalized_symbol] = {
            "price": price,
            "updated_at": updated_at,
            "expires_at": now_utc + timedelta(seconds=BINANCE_PRICE_CACHE_TTL_SECONDS),
        }
        return {
            "symbol": normalized_symbol,
            "price": price,
            "updated_at": updated_at,
            "cache_hit": False,
            "stale_fallback": False,
            "source": "binance_public_api",
            "cache_ttl_seconds": BINANCE_PRICE_CACHE_TTL_SECONDS,
            "poll_recommendation_seconds": BINANCE_SAFE_POLL_SECONDS,
            "request_weight": BINANCE_TICKER_REQUEST_WEIGHT,
        }
    except Exception as e:
        # Use stale cache if available to avoid fully breaking the UI.
        if cache_entry and cache_entry.get("price"):
            return {
                "symbol": normalized_symbol,
                "price": float(cache_entry["price"]),
                "updated_at": cache_entry["updated_at"],
                "cache_hit": False,
                "stale_fallback": True,
                "source": "binance_public_api",
                "cache_ttl_seconds": BINANCE_PRICE_CACHE_TTL_SECONDS,
                "poll_recommendation_seconds": BINANCE_SAFE_POLL_SECONDS,
                "request_weight": BINANCE_TICKER_REQUEST_WEIGHT,
                "warning": f"Using stale price cache due to fetch error: {e}",
            }
        raise HTTPException(status_code=502, detail=f"Failed to fetch realtime price: {e}")


def _load_recent_market_context(current_price_usd: float) -> Dict[str, Any]:
    """
    Build short-horizon market context from metrics CSV.
    Used to avoid over-penalizing aggressive adds during deep capitulation regimes.
    """
    context = {
        "available": False,
        "window_days": 180,
        "low_180d": None,
        "high_180d": None,
        "ath_price": None,
        "current_vs_180d_low_pct": None,
        "current_vs_180d_high_pct": None,
        "current_vs_ath_pct": None,
        "drop_24h_pct": None,
        "near_180d_low": False,
        "new_180d_low": False,
        "near_180d_high": False,
        "new_180d_high": False,
        "near_ath": False,
        "new_ath": False,
        "deep_value_regime": False,
        "breakout_high_regime": False,
        "range_30d_pct": None,
        "realized_vol_30d_pct": None,
        "sideways_30d": False,
    }
    try:
        csv_path = _resolve_metrics_csv_path()
        if not csv_path.exists():
            return context

        prices: List[float] = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                price_str = row.get("close_price")
                if not price_str:
                    continue
                try:
                    prices.append(float(price_str))
                except (ValueError, TypeError):
                    continue

        if len(prices) < 2:
            return context

        window = prices[-180:] if len(prices) >= 180 else prices
        low_180d = min(window)
        high_180d = max(window)
        ath_price = max(prices)
        prev_close = prices[-1]
        window_30d = prices[-30:] if len(prices) >= 30 else prices
        low_30d = min(window_30d)
        high_30d = max(window_30d)
        range_30d_pct = ((high_30d - low_30d) / low_30d) * 100.0 if low_30d > 0 else None
        returns_30d: List[float] = []
        for i in range(1, len(window_30d)):
            prev_px = window_30d[i - 1]
            curr_px = window_30d[i]
            if prev_px > 0:
                returns_30d.append((curr_px - prev_px) / prev_px)
        realized_vol_30d_pct = None
        if len(returns_30d) >= 2:
            try:
                realized_vol_30d_pct = float(pd.Series(returns_30d, dtype=float).std(ddof=0) * 100.0)
            except Exception:
                realized_vol_30d_pct = None

        current_vs_low_pct = ((current_price_usd - low_180d) / low_180d) * 100.0 if low_180d > 0 else None
        current_vs_high_pct = ((current_price_usd - high_180d) / high_180d) * 100.0 if high_180d > 0 else None
        current_vs_ath_pct = ((current_price_usd - ath_price) / ath_price) * 100.0 if ath_price > 0 else None
        drop_24h_pct = ((current_price_usd - prev_close) / prev_close) * 100.0 if prev_close > 0 else None

        near_180d_low = (current_vs_low_pct is not None) and (current_vs_low_pct <= 1.5)
        new_180d_low = current_price_usd < low_180d
        near_180d_high = (current_vs_high_pct is not None) and (current_vs_high_pct >= -1.0)
        new_180d_high = current_price_usd > high_180d
        near_ath = (current_vs_ath_pct is not None) and (current_vs_ath_pct >= -1.0)
        new_ath = current_price_usd > ath_price
        deep_value_regime = bool(near_180d_low and drop_24h_pct is not None and drop_24h_pct <= -6.0)
        breakout_high_regime = bool((near_ath or new_ath) and drop_24h_pct is not None and drop_24h_pct >= 3.5)
        sideways_30d = bool(
            range_30d_pct is not None
            and range_30d_pct <= 8.0
            and realized_vol_30d_pct is not None
            and realized_vol_30d_pct <= 2.0
        )

        return {
            "available": True,
            "window_days": 180,
            "low_180d": float(low_180d),
            "high_180d": float(high_180d),
            "ath_price": float(ath_price),
            "current_vs_180d_low_pct": float(current_vs_low_pct) if current_vs_low_pct is not None else None,
            "current_vs_180d_high_pct": float(current_vs_high_pct) if current_vs_high_pct is not None else None,
            "current_vs_ath_pct": float(current_vs_ath_pct) if current_vs_ath_pct is not None else None,
            "drop_24h_pct": float(drop_24h_pct) if drop_24h_pct is not None else None,
            "near_180d_low": bool(near_180d_low),
            "new_180d_low": bool(new_180d_low),
            "near_180d_high": bool(near_180d_high),
            "new_180d_high": bool(new_180d_high),
            "near_ath": bool(near_ath),
            "new_ath": bool(new_ath),
            "deep_value_regime": bool(deep_value_regime),
            "breakout_high_regime": bool(breakout_high_regime),
            "range_30d_pct": float(range_30d_pct) if range_30d_pct is not None else None,
            "realized_vol_30d_pct": float(realized_vol_30d_pct) if realized_vol_30d_pct is not None else None,
            "sideways_30d": bool(sideways_30d),
        }
    except Exception:
        return context


def _load_macro_context() -> Dict[str, Any]:
    """
    Load latest macro snapshot from docs/data/daily_report.json.
    Used by add-position guidance to ground decisions in current macro stats.
    """
    context = {
        "available": False,
        "report_date": None,
        "report_age_days": None,
        "macro_risk_score": None,
        "macro_risk_regime": None,
        "stress_flags": None,
        "net_liquidity_90d_delta": None,
        "oi_30d_change_pct": None,
        "ma_regime": None,
        "ma_spread": None,
        "usdjpy_risk_level": None,
        "overall_summary": None,
    }
    try:
        def _maybe_float(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        dca_service_dir = Path(__file__).resolve().parent.parent.parent.parent
        report_path = (dca_service_dir.parent / "docs" / "data" / "daily_report.json").resolve()
        if not report_path.exists():
            return context

        data = json.loads(report_path.read_text(encoding="utf-8"))
        sections = data.get("sections", []) or []
        section_metrics: Dict[str, Dict[str, Any]] = {}
        for section in sections:
            chart_name = str(section.get("chart") or "").strip()
            if chart_name:
                section_metrics[chart_name] = section.get("metrics", {}) or {}

        macro_metrics = section_metrics.get("Macro Risk Score", {})
        funding_metrics = section_metrics.get("Funding & Credit Stress", {})
        liquidity_metrics = section_metrics.get("Net Liquidity", {})
        futures_metrics = section_metrics.get("Futures OI & Price", {})
        ma_metrics = section_metrics.get("MA Cross Analysis", {})
        usdjpy_metrics = section_metrics.get("USD/JPY Risk Map", {})

        human_summary = data.get("human_summary", {}) or {}
        overall_summary = human_summary.get("overall_summary")
        if not isinstance(overall_summary, str):
            overall_summary = None

        report_date = data.get("report_date")
        report_age_days = None
        if isinstance(report_date, str):
            try:
                report_dt = datetime.fromisoformat(report_date).date()
                report_age_days = (datetime.now(timezone.utc).date() - report_dt).days
            except Exception:
                report_age_days = None

        macro_risk_score = _maybe_float(macro_metrics.get("score"))
        macro_risk_regime = macro_metrics.get("regime")
        stress_flags = funding_metrics.get("stress_flags")
        net_liq_delta = _maybe_float(liquidity_metrics.get("net_liquidity_90d_delta"))
        oi_30d_change = _maybe_float(futures_metrics.get("oi_30d_change_pct"))
        ma_regime = ma_metrics.get("regime")
        ma_spread = _maybe_float(ma_metrics.get("ma_spread"))
        usdjpy_risk_level = usdjpy_metrics.get("risk_level")

        return {
            "available": True,
            "report_date": report_date,
            "report_age_days": int(report_age_days) if report_age_days is not None else None,
            "macro_risk_score": macro_risk_score,
            "macro_risk_regime": str(macro_risk_regime) if macro_risk_regime is not None else None,
            "stress_flags": int(stress_flags) if stress_flags is not None else None,
            "net_liquidity_90d_delta": net_liq_delta,
            "oi_30d_change_pct": oi_30d_change,
            "ma_regime": str(ma_regime) if ma_regime is not None else None,
            "ma_spread": ma_spread,
            "usdjpy_risk_level": str(usdjpy_risk_level) if usdjpy_risk_level is not None else None,
            "overall_summary": overall_summary,
        }
    except Exception:
        return context


def _execute_live_add_position_order(
    session: Session,
    *,
    symbol: str,
    amount_usdc: float,
) -> Dict[str, Any]:
    creds = session.exec(
        select(BinanceCredentials).where(BinanceCredentials.credential_type == "TRADING")
    ).first()
    if not creds or not creds.api_key_encrypted:
        raise ValueError("Trading credentials not configured. Please add TRADING API keys in Binance settings.")

    api_key = decrypt_text(creds.api_key_encrypted)
    api_secret = decrypt_text(creds.api_secret_encrypted)

    async def _execute() -> Dict[str, Any]:
        client = BinanceClient(api_key, api_secret)
        try:
            return await client.execute_market_order_with_confirmation(
                symbol=symbol,
                quote_quantity=amount_usdc,
                max_wait_seconds=10,
                poll_interval=1.0,
            )
        finally:
            await client.close()

    return asyncio.run(_execute())


def _send_add_position_email_task(transaction_id: int) -> None:
    """
    Background email task for add-position confirmations.
    Uses a fresh DB session to avoid relying on request-scoped objects.
    """
    try:
        with Session(engine) as bg_session:
            tx = bg_session.get(DCATransaction, transaction_id)
            if not tx:
                return
            from dca_service.services.mailer import send_dca_notification
            send_dca_notification(tx, decision=None, total_btc=None)
    except Exception:
        # Email should never break API flow.
        pass


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


def _build_buy_behavior_snapshot(session: Session) -> Tuple[List[DCATransaction], Dict[str, Any], Dict[str, Any], str]:
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
    return buy_txs, aggregate_meta, behavior_data, source_signature


def _build_add_position_guidance(
    *,
    behavior_data: Dict[str, Any],
    events: List[Dict[str, Any]],
    amount_usdc: float,
    current_price_usd: float,
    market_context: Optional[Dict[str, Any]] = None,
    macro_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    def _as_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    summary = behavior_data.get("summary", {}) or {}
    style_tags = behavior_data.get("style_tags", []) or []

    historical_prices = [float(e.get("avg_price_usd", 0.0)) for e in events if float(e.get("avg_price_usd", 0.0)) > 0]
    hist_min = min(historical_prices) if historical_prices else current_price_usd
    hist_max = max(historical_prices) if historical_prices else current_price_usd
    hist_median = _safe_median(historical_prices, fallback=current_price_usd)

    if hist_max > hist_min:
        raw_price_position = (current_price_usd - hist_min) / (hist_max - hist_min)
        price_position = min(max(raw_price_position, 0.0), 1.0)
    else:
        price_position = 0.5
    price_zone_label = _classify_price_position(price_position)
    price_vs_hist_median_pct = (
        ((current_price_usd - hist_median) / hist_median) * 100.0 if hist_median > 0 else 0.0
    )

    market_ctx = market_context or {}
    macro_ctx = macro_context or {}
    deep_value_regime = bool(market_ctx.get("deep_value_regime"))
    breakout_high_regime = bool(market_ctx.get("breakout_high_regime"))
    near_ath = bool(market_ctx.get("near_ath") or market_ctx.get("near_180d_high"))
    new_ath = bool(market_ctx.get("new_ath"))
    new_180d_low = bool(market_ctx.get("new_180d_low"))
    drop_24h_pct = _as_float(market_ctx.get("drop_24h_pct"))
    current_vs_180d_low_pct = _as_float(market_ctx.get("current_vs_180d_low_pct"))

    recent_amounts = [float(e.get("amount_usd", 0.0)) for e in events[-10:] if float(e.get("amount_usd", 0.0)) > 0]
    baseline_amount = _safe_median(recent_amounts, fallback=float(summary.get("avg_event_usd", amount_usdc) or amount_usdc))
    if baseline_amount <= 0:
        baseline_amount = amount_usdc

    relative_amount = amount_usdc / baseline_amount if baseline_amount > 0 else 1.0
    relative_amount_label = _classify_relative_amount(relative_amount)

    now_utc = datetime.now(timezone.utc)
    recent_24h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 24 * 3600
    )
    recent_48h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 48 * 3600
    )
    recent_72h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 72 * 3600
    )
    last_event_ts = events[-1]["timestamp"] if events and isinstance(events[-1].get("timestamp"), datetime) else None

    recent_trade_prices = [float(e.get("avg_price_usd", 0.0)) for e in events[-14:] if float(e.get("avg_price_usd", 0.0)) > 0]
    recent_trade_median_price = _safe_median(recent_trade_prices, fallback=current_price_usd)
    if recent_trade_prices:
        recent_trade_min = min(recent_trade_prices)
        recent_trade_max = max(recent_trade_prices)
        recent_trade_range_pct = ((recent_trade_max - recent_trade_min) / recent_trade_min) * 100.0 if recent_trade_min > 0 else None
    else:
        recent_trade_range_pct = None
    current_vs_recent_trade_median_pct = (
        ((current_price_usd - recent_trade_median_price) / recent_trade_median_price) * 100.0
        if recent_trade_median_price > 0
        else None
    )

    burst_ratio = float(summary.get("burst_trading_ratio", 0.0) or 0.0)
    event_count = int(summary.get("behavior_event_count", 0) or 0)
    event_amount_cv = float(summary.get("event_amount_cv", 0.0) or 0.0)
    high_zone_ratio = float(summary.get("high_zone_buy_ratio", 0.0) or 0.0)
    low_zone_ratio = float(summary.get("low_zone_buy_ratio", 0.0) or 0.0)

    burst_habit = bool(burst_ratio >= 0.45 and event_count >= 8)
    inconsistent_habit = bool(event_amount_cv >= 0.9 and event_count >= 8)
    high_zone_habit = bool(high_zone_ratio >= 0.55 and high_zone_ratio > low_zone_ratio + 0.15 and event_count >= 8)
    dca_event_ratio = float(summary.get("dca_event_ratio", 0.0) or 0.0)
    manual_event_ratio = float(summary.get("manual_event_ratio", 0.0) or 0.0)
    if dca_event_ratio >= 0.60:
        cadence_label = "DCA cadence"
        source_mix_label = "dca_dominant"
    elif manual_event_ratio >= 0.60:
        cadence_label = "manual buy cadence"
        source_mix_label = "manual_dominant"
    else:
        cadence_label = "mixed buy cadence"
        source_mix_label = "mixed"

    macro_available = bool(macro_ctx.get("available"))
    macro_risk_score = _as_float(macro_ctx.get("macro_risk_score"))
    macro_risk_regime = str(macro_ctx.get("macro_risk_regime") or "").strip().lower() or None
    stress_flags = macro_ctx.get("stress_flags")
    try:
        stress_flags_int = int(stress_flags) if stress_flags is not None else None
    except (TypeError, ValueError):
        stress_flags_int = None
    net_liquidity_delta = _as_float(macro_ctx.get("net_liquidity_90d_delta"))
    oi_30d_change_pct = _as_float(macro_ctx.get("oi_30d_change_pct"))
    ma_regime = str(macro_ctx.get("ma_regime") or "").strip().lower() or None
    report_age_days = macro_ctx.get("report_age_days")
    try:
        report_age_days_int = int(report_age_days) if report_age_days is not None else None
    except (TypeError, ValueError):
        report_age_days_int = None

    # Multi-signal capitulation mode:
    # If price is deeply depressed and several independent stress/deleveraging
    # signals align, do not auto-downsize solely because of historical sizing habits.
    capitulation_signals = 0
    if deep_value_regime or new_180d_low:
        capitulation_signals += 1
    if drop_24h_pct is not None and drop_24h_pct <= -8.0:
        capitulation_signals += 1
    if (current_vs_180d_low_pct is not None and current_vs_180d_low_pct <= 1.0) or price_position <= 0.18:
        capitulation_signals += 1
    if oi_30d_change_pct is not None and oi_30d_change_pct <= -10.0:
        capitulation_signals += 1
    if macro_risk_score is not None and macro_risk_score <= 70.0:
        capitulation_signals += 1
    if stress_flags_int is not None and stress_flags_int <= 1:
        capitulation_signals += 1
    strong_dip_add_mode = bool((deep_value_regime or new_180d_low) and capitulation_signals >= 3)
    range_30d_pct = _as_float(market_ctx.get("range_30d_pct"))
    realized_vol_30d_pct = _as_float(market_ctx.get("realized_vol_30d_pct"))
    sideways_30d = bool(market_ctx.get("sideways_30d"))
    if not sideways_30d and range_30d_pct is not None and realized_vol_30d_pct is not None:
        sideways_30d = bool(range_30d_pct <= 12.0 and realized_vol_30d_pct <= 3.0)

    local_sideways_by_trades = bool(
        recent_trade_range_pct is not None
        and recent_trade_range_pct <= 8.5
        and current_vs_recent_trade_median_pct is not None
        and abs(current_vs_recent_trade_median_pct) <= 4.5
    )

    median_interval_days = _as_float(summary.get("median_interval_days"))
    dense_buy_mode = bool(
        event_count >= 10
        and burst_ratio >= 0.60
        and median_interval_days is not None
        and median_interval_days <= 1.5
    )

    macro_takeoff_mode = False
    if macro_available:
        macro_takeoff_mode = bool(
            (ma_regime == "bullish" or breakout_high_regime)
            and (net_liquidity_delta is None or net_liquidity_delta >= 80.0)
            and (macro_risk_score is None or macro_risk_score <= 60.0)
            and (stress_flags_int is None or stress_flags_int <= 1)
            and (oi_30d_change_pct is None or oi_30d_change_pct >= 5.0)
        )
    ongoing_dense_flow = bool(recent_24h_count >= 1 or recent_72h_count >= 2)
    no_extra_add_needed_mode = bool(
        dense_buy_mode
        and ongoing_dense_flow
        and (local_sideways_by_trades or sideways_30d)
        and not macro_takeoff_mode
        and not strong_dip_add_mode
    )

    reasons: List[str] = []
    applied_lessons: List[str] = []
    macro_notes: List[str] = []

    multiplier = 1.0
    if deep_value_regime or new_180d_low:
        multiplier *= 1.65
        reasons.append("Price is in a deep pullback zone, so adding now is allowed with a larger size than baseline.")
        if strong_dip_add_mode:
            multiplier *= 1.25
            reasons.append("Multi-signal capitulation setup confirmed, so larger add size is allowed.")
    elif no_extra_add_needed_mode:
        multiplier *= 0.68
        reasons.append(f"Market is sideways while your {cadence_label} is already dense, so extra add is usually unnecessary.")
    elif macro_takeoff_mode:
        multiplier *= 1.15
        reasons.append("Macro takeoff signals are aligned, so adding above baseline is justified.")
    elif price_position <= 0.25 or bool(market_ctx.get("near_180d_low")):
        multiplier *= 1.20
        reasons.append("Price is in your historical lower zone, which fits your dip-buy edge.")
    elif breakout_high_regime or new_ath:
        multiplier *= 0.55
        reasons.append("Price is in a breakout-high regime, so size should stay defensive.")
    elif near_ath or price_position >= 0.80:
        multiplier *= 0.72
        reasons.append("Price is near historical highs, so this add should be smaller.")

    if macro_available:
        if report_age_days_int is not None and report_age_days_int > 5:
            macro_notes.append(f"Macro snapshot is {report_age_days_int} days old, so macro weight is reduced.")
        if macro_risk_score is not None:
            if macro_risk_score >= 70:
                multiplier *= 0.92 if deep_value_regime else 0.82
                macro_notes.append(f"Macro risk score {macro_risk_score:.1f}/100 is high; size is trimmed.")
            elif macro_risk_score <= 35:
                multiplier *= 1.05
                macro_notes.append(f"Macro risk score {macro_risk_score:.1f}/100 is contained; normal risk budget is acceptable.")
        if stress_flags_int is not None:
            if stress_flags_int >= 2:
                multiplier *= 0.95 if deep_value_regime else 0.88
                macro_notes.append(f"Funding stress flags = {stress_flags_int}; keep risk tighter.")
            elif stress_flags_int == 0:
                macro_notes.append("Funding stress flags are low.")
        if net_liquidity_delta is not None:
            if net_liquidity_delta <= -120:
                multiplier *= 0.96 if deep_value_regime else 0.90
                macro_notes.append(f"Net liquidity 90d delta is weak ({net_liquidity_delta:+.1f}B), so keep size controlled.")
            elif net_liquidity_delta >= 80:
                multiplier *= 1.07
                macro_notes.append(f"Net liquidity 90d delta is supportive ({net_liquidity_delta:+.1f}B).")
        if oi_30d_change_pct is not None:
            if oi_30d_change_pct >= 25:
                multiplier *= 0.92
                macro_notes.append(f"Futures OI rose {oi_30d_change_pct:+.1f}% in 30d; avoid chasing crowded risk.")
            elif oi_30d_change_pct <= -15:
                multiplier *= 1.05
                macro_notes.append(f"Futures OI changed {oi_30d_change_pct:+.1f}% in 30d, showing prior deleveraging.")
        if ma_regime == "bearish" and not deep_value_regime:
            multiplier *= 0.95
            macro_notes.append("Trend regime is bearish, so size is capped slightly.")
        elif ma_regime == "bullish":
            multiplier *= 1.04
            macro_notes.append("Trend regime is bullish, which supports risk-taking.")
        if macro_risk_regime and macro_risk_regime != "neutral":
            macro_notes.append(f"Macro regime: {macro_risk_regime}.")
    else:
        macro_notes.append("Macro snapshot unavailable; decision uses live price + your history only.")

    if burst_habit and recent_48h_count >= 1:
        if strong_dip_add_mode:
            multiplier *= 0.98
            applied_lessons.append("Burst habit penalty is mostly relaxed because this is a confirmed capitulation setup.")
        else:
            multiplier *= 0.92 if deep_value_regime else 0.80
            applied_lessons.append("You often cluster buys within 48h; size is reduced to avoid burst-overtrading.")

    if high_zone_habit and (breakout_high_regime or near_ath or price_position >= 0.75):
        multiplier *= 0.85
        applied_lessons.append("You have a high-zone chasing pattern; this call applies an extra size haircut.")

    suggested_amount = max(10.0, baseline_amount * multiplier)
    if inconsistent_habit:
        # Keep size executable and stable, but allow wider ranges in deep drawdowns.
        if strong_dip_add_mode:
            upper = max(baseline_amount * 10.0, amount_usdc * 1.10)
        else:
            upper = baseline_amount * (3.00 if deep_value_regime else 1.20)
        lower = baseline_amount * 0.85
        suggested_amount = min(max(suggested_amount, lower), upper)
        applied_lessons.append("Your historical sizing is unstable; suggestion is anchored to reduce noise in outcomes.")

    if strong_dip_add_mode and amount_usdc > suggested_amount:
        suggested_amount = amount_usdc
        applied_lessons.append(
            "In confirmed capitulation mode, current size is not downscaled just for historical pattern mismatch."
        )

    suggested_amount = round(max(10.0, suggested_amount), 2)
    proposed_gap_pct = ((amount_usdc - suggested_amount) / suggested_amount * 100.0) if suggested_amount > 0 else 0.0

    decision = "BUY"
    if not deep_value_regime:
        if no_extra_add_needed_mode:
            decision = "WAIT"
            reasons.append(f"No extra add needed now: your ongoing {cadence_label} already covers this sideways regime.")
        elif (
            (breakout_high_regime or new_ath)
            and recent_48h_count >= 1
            and amount_usdc > suggested_amount * 1.10
            and not macro_takeoff_mode
        ):
            decision = "WAIT"
            reasons.append("You already bought recently and price is in a breakout-high state; skip this add now.")
        elif near_ath and burst_habit and amount_usdc > suggested_amount * 1.30 and not macro_takeoff_mode:
            decision = "WAIT"
            reasons.append("Near-high price plus your burst habit makes this add low quality right now.")
        elif macro_risk_score is not None and macro_risk_score >= 80 and amount_usdc > suggested_amount:
            decision = "WAIT"
            reasons.append("Macro stress is elevated and your proposed size is above model size.")

    if decision == "BUY":
        if suggested_amount <= baseline_amount * 0.80:
            size_bucket = "SMALL"
        elif suggested_amount <= baseline_amount * 1.35:
            size_bucket = "NORMAL"
        else:
            size_bucket = "LARGE"
    else:
        size_bucket = "NONE"

    if decision == "BUY":
        if deep_value_regime:
            band = 0.35
        else:
            band = 0.10 if inconsistent_habit else 0.15
        range_min = round(max(10.0, suggested_amount * (1 - band)), 2)
        range_max = round(max(range_min, suggested_amount * (1 + band)), 2)
    else:
        range_min = 0.0
        range_max = 0.0

    if not reasons:
        reasons.append("No major risk signal is active; this setup is close to your normal decision profile.")
    reasons.extend(macro_notes[:2])
    reasons = reasons[:4]

    if not applied_lessons:
        applied_lessons.append("No major bad-habit penalty was triggered in this setup.")

    if decision == "WAIT":
        action_code = "NO_BUY"
        advised_amount_usdc = 0.0
        input_alignment = "WAIT"
        action_now = "No buy now."
        if no_extra_add_needed_mode:
            if recent_trade_range_pct is not None:
                call_reason = (
                    f"No extra add needed: dense {cadence_label} already active and your recent range is only {recent_trade_range_pct:.2f}%."
                )
            else:
                call_reason = f"No extra add needed: your {cadence_label} is already dense in a range market."
        elif breakout_high_regime or near_ath or new_ath:
            call_reason = "Don't chase breakout highs right now."
        elif burst_habit and recent_48h_count >= 1:
            call_reason = "You already bought recently, so skip stacking entries."
        elif macro_risk_score is not None and macro_risk_score >= 80:
            call_reason = "Macro stress is elevated for this size."
        else:
            call_reason = reasons[0]
        final_call = "NO BUY"
    else:
        advised_amount_usdc = suggested_amount
        if strong_dip_add_mode:
            action_code = "BUY_AS_PLANNED"
            input_alignment = "ALIGNED_CAPITULATION"
            action_now = f"Buy ${amount_usdc:,.2f} now."
            call_reason = "Capitulation setup is confirmed across multiple signals."
            final_call = f"BUY AS PLANNED: ${amount_usdc:,.2f}"
        elif amount_usdc > suggested_amount * 1.15 and not deep_value_regime:
            action_code = "BUY_LESS"
            input_alignment = "ABOVE_SUGGESTED"
            action_now = f"Buy less: ${suggested_amount:,.2f}."
            call_reason = "Your input is larger than the rational size for this setup."
            final_call = f"BUY LESS: ${suggested_amount:,.2f}"
        elif amount_usdc < suggested_amount * 0.85:
            action_code = "BUY_MORE"
            input_alignment = "BELOW_SUGGESTED"
            action_now = f"Buy more: ${suggested_amount:,.2f}."
            call_reason = "Your input is below the size implied by current edge."
            final_call = f"BUY MORE: ${suggested_amount:,.2f}"
        else:
            action_code = "BUY_AS_PLANNED"
            input_alignment = "ALIGNED"
            action_now = f"Buy ${amount_usdc:,.2f} now."
            call_reason = "Your plan size is already in the rational range."
            final_call = f"BUY AS PLANNED: ${amount_usdc:,.2f}"

    risk_score = 35
    if breakout_high_regime or new_ath:
        risk_score += 20
    if near_ath:
        risk_score += 10
    if burst_habit and recent_48h_count >= 1:
        risk_score += 12
    if inconsistent_habit:
        risk_score += 8
    if macro_risk_score is not None and macro_risk_score >= 70:
        risk_score += 12
    if stress_flags_int is not None and stress_flags_int >= 2:
        risk_score += 8
    if deep_value_regime:
        risk_score -= 18
    if decision == "WAIT":
        risk_score = max(risk_score, 72)
    risk_score = int(min(max(risk_score, 0), 100))
    if risk_score >= 70:
        risk_level = "high"
    elif risk_score >= 40:
        risk_level = "medium"
    else:
        risk_level = "low"

    estimated_btc = suggested_amount / current_price_usd if (decision == "BUY" and current_price_usd > 0) else 0.0
    lines: List[str] = [f"Call: {final_call}"]
    if decision == "BUY":
        lines.append(
            f"Input: ${amount_usdc:,.2f} | Suggested now: ${suggested_amount:,.2f} "
            f"(range ${range_min:,.2f}-${range_max:,.2f}, {size_bucket.lower()})."
        )
        lines.append(f"Estimated BTC now: {estimated_btc:.8f} BTC")
    else:
        lines.append(f"Input: ${amount_usdc:,.2f} | Suggested now: skip this entry.")
    lines.append(f"Do now: {action_now}")
    lines.append(f"Short reason: {call_reason}")
    lines.append(
        "Price context: "
        f"{price_vs_hist_median_pct:+.2f}% vs your historical median fill, "
        f"{(market_ctx.get('current_vs_180d_low_pct') if market_ctx.get('current_vs_180d_low_pct') is not None else 0.0):+.2f}% vs 180d low, "
        f"24h move {(market_ctx.get('drop_24h_pct') if market_ctx.get('drop_24h_pct') is not None else 0.0):+.2f}%."
    )
    if recent_trade_range_pct is not None and current_vs_recent_trade_median_pct is not None:
        lines.append(
            "Flow context: "
            f"recent 14-event range {recent_trade_range_pct:.2f}%, "
            f"current {current_vs_recent_trade_median_pct:+.2f}% vs your recent median fill, "
            f"buys in 24h: {recent_24h_count}, in 72h: {recent_72h_count}."
        )
    if macro_available:
        macro_parts: List[str] = []
        if macro_risk_score is not None:
            macro_parts.append(f"risk {macro_risk_score:.1f}/100")
        if stress_flags_int is not None:
            macro_parts.append(f"stress_flags {stress_flags_int}")
        if net_liquidity_delta is not None:
            macro_parts.append(f"net_liquidity_90d {net_liquidity_delta:+.1f}B")
        if oi_30d_change_pct is not None:
            macro_parts.append(f"oi_30d {oi_30d_change_pct:+.1f}%")
        if macro_parts:
            lines.append("Macro context: " + ", ".join(macro_parts) + ".")
    lines.append("Why:")
    for idx, reason in enumerate(reasons[:2], start=1):
        lines.append(f"{idx}. {reason}")
    lines.append("Applied lesson:")
    for idx, lesson in enumerate(applied_lessons[:1], start=1):
        lines.append(f"{idx}. {lesson}")

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "size_bucket": size_bucket,
        "action_code": action_code,
        "advised_amount_usdc": float(advised_amount_usdc),
        "final_call": final_call,
        "call_reason": call_reason,
        "action_now": action_now,
        "input_alignment": input_alignment,
        "suggested_amount_usdc": suggested_amount if decision == "BUY" else 0.0,
        "proposed_amount_usdc": float(amount_usdc),
        "proposed_gap_pct_vs_suggested": float(proposed_gap_pct),
        "reasons": reasons,
        "applied_lessons": applied_lessons,
        "price_context": {
            "historical_min_price": float(hist_min),
            "historical_median_price": float(hist_median),
            "historical_max_price": float(hist_max),
            "price_position_in_historical_range": float(price_position),
            "price_zone_label": price_zone_label,
            "price_vs_historical_median_pct": float(price_vs_hist_median_pct),
        },
        "sizing_context": {
            "baseline_event_usd": float(baseline_amount),
            "relative_size_to_baseline": float(relative_amount),
            "relative_amount_label": relative_amount_label,
            "recommended_range_usdc": {
                "min": range_min,
                "max": range_max,
            },
            "suggested_amount_usdc": suggested_amount if decision == "BUY" else 0.0,
        },
        "behavior_context": {
            "style_tags": style_tags,
            "burst_trading_ratio": burst_ratio,
            "median_interval_days": summary.get("median_interval_days"),
            "event_amount_cv": event_amount_cv,
            "dense_buy_mode": dense_buy_mode,
            "dense_dca_mode": dense_buy_mode,
            "source_mix_label": source_mix_label,
            "dca_event_ratio": dca_event_ratio,
            "manual_event_ratio": manual_event_ratio,
            "no_extra_add_needed_mode": no_extra_add_needed_mode,
            "recent_sideways_by_trades": local_sideways_by_trades,
            "recent_trade_range_pct": float(recent_trade_range_pct) if recent_trade_range_pct is not None else None,
            "current_vs_recent_trade_median_pct": (
                float(current_vs_recent_trade_median_pct) if current_vs_recent_trade_median_pct is not None else None
            ),
            "recent_events_24h": recent_24h_count,
            "recent_events_48h": recent_48h_count,
            "recent_events_72h": recent_72h_count,
            "last_event_time": last_event_ts.isoformat() if isinstance(last_event_ts, datetime) else None,
        },
        "market_context": market_ctx,
        "macro_context": macro_ctx,
        "analysis_text": "\n".join(lines),
        "method_constraints": {
            "split_fill_handling": "Same binance_order_id merged into one event.",
            "no_hindsight": "Guidance is based on current and prior data only. No future information is used.",
        },
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

    event_diagnostics = analysis_data.get("event_diagnostics", []) or []
    compact_event_diagnostics = [
        {
            "event_time": item.get("event_time"),
            "amount_usd": item.get("amount_usd"),
            "avg_price_usd": item.get("avg_price_usd"),
            "interval_since_prev_days": item.get("interval_since_prev_days"),
            "relative_amount_label": item.get("relative_amount_label"),
            "price_position_label": item.get("price_position_label"),
        }
        for item in event_diagnostics[-30:]
    ]

    payload_for_model_full = {
        "summary": analysis_data.get("summary", {}),
        "style_tags": analysis_data.get("style_tags", []),
        "issues": analysis_data.get("issues", []),
        "event_diagnostics": event_diagnostics[-80:],
        "method_constraints": analysis_data.get("method_constraints", {}),
    }
    payload_for_model_compact = {
        "summary": analysis_data.get("summary", {}),
        "style_tags": analysis_data.get("style_tags", []),
        "issues": analysis_data.get("issues", []),
        "event_diagnostics": compact_event_diagnostics,
        "method_constraints": analysis_data.get("method_constraints", {}),
    }
    payload_for_model_minimal = {
        "summary": analysis_data.get("summary", {}),
        "style_tags": analysis_data.get("style_tags", []),
        "issues": analysis_data.get("issues", []),
        "method_constraints": analysis_data.get("method_constraints", {}),
    }

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
        user_prompt_template = (
            "下面是用户交易行为统计数据（同一订单ID拆单已合并为一个行为事件）。\n"
            "请基于这些数据分析交易风格与潜在问题，禁止使用未来信息倒推过去决策。\n\n"
            "{payload_json}"
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
        user_prompt_template = (
            "Below is the user's trading behavior dataset (split fills with same order ID are merged as one event).\n"
            "Analyze style and potential problems using only these metrics. No hindsight bias.\n\n"
            "{payload_json}"
        )

    def _extract_error_detail(resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    msg = err.get("message")
                    if isinstance(msg, str) and msg.strip():
                        return msg.strip()
                msg = data.get("message")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
        except Exception:
            pass
        text = (resp.text or "").strip().replace("\n", " ")
        return text[:280] if text else ""

    def _call_provider_with_payload(payload_obj: Dict[str, Any]) -> Dict[str, Any]:
        user_payload_text = json.dumps(payload_obj, ensure_ascii=False)
        user_prompt = user_prompt_template.format(payload_json=user_payload_text)
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
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )

            if response.status_code >= 400:
                detail = _extract_error_detail(response)
                reason = f"AI provider HTTP {response.status_code}"
                if detail:
                    reason = f"{reason}: {detail}"
                return {"ok": False, "reason": reason, "status_code": response.status_code}

            body = response.json()
            choices = body.get("choices") or []
            if not choices:
                return {"ok": False, "reason": "AI response has no choices.", "status_code": None}
            message = (choices[0] or {}).get("message") or {}
            content = message.get("content")
            if not content:
                return {"ok": False, "reason": "AI response has empty content.", "status_code": None}
            return {"ok": True, "content": content}
        except Exception as e:
            return {"ok": False, "reason": f"AI call failed: {e}", "status_code": None}

    try:
        attempts = [
            payload_for_model_full,
            payload_for_model_compact,
            payload_for_model_minimal,
        ]
        last_reason = ""
        last_http_status: Optional[int] = None
        content = None
        for payload_variant in attempts:
            result = _call_provider_with_payload(payload_variant)
            if result.get("ok"):
                content = result.get("content")
                break
            last_reason = result.get("reason", "")
            last_http_status = result.get("status_code")
            # Only retry for 400-like payload/request issues; others usually won't benefit.
            if last_http_status not in (400, 413, 422):
                break

        if not content:
            status["reason"] = last_reason or "AI provider request failed."
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


@router.get("/stats/realtime-price")
def get_realtime_price(
    symbol: str = Query(default="BTCUSDC"),
    current_user: User = Depends(get_current_user),
):
    """
    Return realtime ticker price from Binance public API with a short TTL cache.
    Cache + client polling guidance are tuned to stay far below Binance limits.
    """
    return _fetch_binance_realtime_price(symbol)


@router.post("/stats/add-position/advice")
def get_add_position_advice(
    payload: AddPositionAdviceRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Generate pre-order add-position guidance based on:
    - Current input size
    - Current market price (caller-provided or fetched)
    - Historical behavior snapshot (split fills merged by order id)

    The guidance avoids hindsight bias by using only past executed events + now.
    """
    normalized_symbol = _normalize_symbol(payload.symbol)
    if payload.current_price_usd is not None and payload.current_price_usd > 0:
        price_snapshot = {
            "symbol": normalized_symbol,
            "price": float(payload.current_price_usd),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cache_hit": False,
            "stale_fallback": False,
            "source": "user_input",
            "cache_ttl_seconds": BINANCE_PRICE_CACHE_TTL_SECONDS,
            "poll_recommendation_seconds": BINANCE_SAFE_POLL_SECONDS,
            "request_weight": BINANCE_TICKER_REQUEST_WEIGHT,
        }
    else:
        price_snapshot = _fetch_binance_realtime_price(normalized_symbol)

    _, aggregate_meta, behavior_data, source_signature = _build_buy_behavior_snapshot(session)
    market_context = _load_recent_market_context(float(price_snapshot["price"]))
    macro_context = _load_macro_context()
    guidance = _build_add_position_guidance(
        behavior_data=behavior_data,
        events=aggregate_meta.get("events", []) or [],
        amount_usdc=float(payload.amount_usdc),
        current_price_usd=float(price_snapshot["price"]),
        market_context=market_context,
        macro_context=macro_context,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_signature": source_signature,
        "symbol": normalized_symbol,
        "input": {
            "amount_usdc": float(payload.amount_usdc),
            "current_price_usd": float(price_snapshot["price"]),
        },
        "price_snapshot": price_snapshot,
        "analysis_data": {
            "summary": behavior_data.get("summary", {}),
            "style_tags": behavior_data.get("style_tags", []),
            "issues": behavior_data.get("issues", []),
            "method_constraints": behavior_data.get("method_constraints", {}),
            "source_signature": source_signature,
            "macro_context": macro_context,
        },
        "guidance": guidance,
    }


@router.post("/stats/add-position/confirm")
def confirm_add_position(
    payload: AddPositionConfirmRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Confirm add-position after reviewing advice.
    This records a simulated buy event for tracking and analytics.
    """
    normalized_symbol = _normalize_symbol(payload.symbol)
    amount_usdc = float(payload.amount_usdc)
    input_price_usd = float(payload.price_usd)
    if amount_usdc <= 0 or input_price_usd <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount or price.")

    strategy = session.exec(select(DCAStrategy)).first()
    execution_mode = ((strategy.execution_mode if strategy else "DRY_RUN") or "DRY_RUN").upper()
    if execution_mode not in {"DRY_RUN", "LIVE"}:
        execution_mode = "DRY_RUN"

    notes = (payload.notes or "").strip() or "Add Position confirmed after advice"
    notes = f"{notes} [{normalized_symbol}] ({execution_mode})"

    if execution_mode == "LIVE":
        try:
            live_result = _execute_live_add_position_order(
                session,
                symbol=normalized_symbol,
                amount_usdc=amount_usdc,
            )
            executed_price = float(live_result.get("avg_price") or 0.0)
            executed_btc = float(live_result.get("total_btc") or 0.0)
            executed_usd = float(live_result.get("quote_spent") or amount_usdc)
            fee_amount = float(live_result.get("total_fee") or 0.0)
            fee_asset = str(live_result.get("fee_asset") or "USDC")
            binance_order_id = live_result.get("order_id")
            if executed_price <= 0 or executed_btc <= 0:
                raise ValueError("Live order returned invalid execution data.")

            tx = DCATransaction(
                status="SUCCESS",
                fiat_amount=executed_usd,
                btc_amount=executed_btc,
                price=executed_price,
                ahr999=0.0,
                notes=notes,
                intended_amount_usd=amount_usdc,
                executed_amount_usd=executed_usd,
                executed_amount_btc=executed_btc,
                avg_execution_price_usd=executed_price,
                fee_amount=fee_amount,
                fee_asset=fee_asset,
                source="DCA",
                binance_order_id=binance_order_id,
            )
            session.add(tx)
            session.commit()
            session.refresh(tx)
            background_tasks.add_task(_send_add_position_email_task, tx.id)

            return {
                "success": True,
                "execution_mode": execution_mode,
                "message": (
                    f"LIVE buy executed: ${executed_usd:.2f} -> {executed_btc:.8f} BTC "
                    f"@ ${executed_price:.2f}"
                ),
                "transaction": tx,
            }
        except Exception as e:
            failed_tx = DCATransaction(
                status="FAILED",
                fiat_amount=amount_usdc,
                btc_amount=0.0,
                price=input_price_usd,
                ahr999=0.0,
                notes=f"{notes} | LIVE execution failed: {e}",
                intended_amount_usd=amount_usdc,
                executed_amount_usd=0.0,
                executed_amount_btc=0.0,
                avg_execution_price_usd=0.0,
                fee_amount=0.0,
                fee_asset="USDC",
                source="DCA",
            )
            session.add(failed_tx)
            session.commit()
            session.refresh(failed_tx)
            raise HTTPException(status_code=502, detail=f"LIVE buy failed: {e}")

    # DRY_RUN path
    btc_amount = amount_usdc / input_price_usd
    tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=amount_usdc,
        btc_amount=btc_amount,
        price=input_price_usd,
        ahr999=0.0,
        notes=notes,
        intended_amount_usd=amount_usdc,
        executed_amount_usd=amount_usdc,
        executed_amount_btc=btc_amount,
        avg_execution_price_usd=input_price_usd,
        fee_amount=0.0,
        fee_asset="USDC",
        source="SIMULATED",
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)
    background_tasks.add_task(_send_add_position_email_task, tx.id)

    return {
        "success": True,
        "execution_mode": execution_mode,
        "message": f"DRY_RUN buy recorded: ${amount_usdc:.2f} at ${input_price_usd:.2f}",
        "transaction": tx,
    }


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
    _, _, behavior_data, source_signature = _build_buy_behavior_snapshot(session)

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
