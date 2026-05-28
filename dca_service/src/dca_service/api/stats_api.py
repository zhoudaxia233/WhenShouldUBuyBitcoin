from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks, Response
from sqlmodel import Session, select, col
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone, timedelta
import pandas as pd
import httpx
import math
import json
import hashlib
import logging
import csv
import io
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
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
MARKET_CONTEXT_MAX_AGE_DAYS = 3
MACRO_CONTEXT_MAX_AGE_DAYS = 7


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
        # Free-data bottoming helpers from metrics CSV (optional)
        "ahr999": None,
        "ahr999_sub_1": None,
        "ahr999_sub_07": None,
        "rsi14": None,
        "rsi14w": None,
        "is_rsi_daily_oversold": None,
        "is_rsi_weekly_oversold_proxy": None,
        "is_rsi_bottoming_signal": None,
        "volume_ratio_30": None,
        "is_post_panic_volume_contraction": None,
        "bottoming_tech_signal_count": 0,
        "metrics_as_of_date": None,
        "metrics_age_days": None,
        "is_stale": True,
        "freshness_max_age_days": MARKET_CONTEXT_MAX_AGE_DAYS,
        "dca_cost": None,
        "trend_value": None,
        "ratio_dca_current": None,
        "ratio_trend_current": None,
        "is_double_undervalued": False,
    }
    try:
        csv_path = _resolve_metrics_csv_path()
        if not csv_path.exists():
            return context

        prices: List[float] = []
        last_row: Optional[Dict[str, Any]] = None
        last_metric_date = None
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                last_row = row
                date_str = row.get("date")
                if date_str:
                    try:
                        last_metric_date = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                    except (ValueError, TypeError):
                        pass
                price_str = row.get("close_price")
                if not price_str:
                    continue
                try:
                    prices.append(float(price_str))
                except (ValueError, TypeError):
                    continue

        if len(prices) < 2:
            return context

        metrics_age_days = None
        metrics_is_stale = True
        if last_metric_date is not None:
            metrics_age_days = (datetime.now(timezone.utc).date() - last_metric_date).days
            metrics_is_stale = metrics_age_days < 0 or metrics_age_days > MARKET_CONTEXT_MAX_AGE_DAYS

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

        def _maybe_float_from_last(key: str) -> Optional[float]:
            if not last_row:
                return None
            raw = last_row.get(key)
            if raw in (None, "", "nan", "NaN"):
                return None
            try:
                val = float(raw)
                return val if math.isfinite(val) else None
            except (TypeError, ValueError):
                return None

        def _maybe_bool_from_last(key: str) -> Optional[bool]:
            if not last_row:
                return None
            raw = last_row.get(key)
            if raw in (None, ""):
                return None
            return str(raw).strip().lower() in {"1", "true", "yes"}

        ahr999_val = _maybe_float_from_last("ahr999")
        dca_cost = _maybe_float_from_last("dca_cost")
        trend_value = _maybe_float_from_last("trend_value")
        ratio_dca_current = (current_price_usd / dca_cost) if dca_cost and dca_cost > 0 else _maybe_float_from_last("ratio_dca")
        ratio_trend_current = (
            current_price_usd / trend_value if trend_value and trend_value > 0 else _maybe_float_from_last("ratio_trend")
        )
        is_double_undervalued = bool(
            ratio_dca_current is not None
            and ratio_trend_current is not None
            and ratio_dca_current < 1.0
            and ratio_trend_current < 1.0
        )
        rsi14_val = _maybe_float_from_last("rsi14")
        rsi14w_val = _maybe_float_from_last("rsi14w")
        volume_ratio_30 = _maybe_float_from_last("volume_ratio_30")
        is_rsi_daily_oversold = _maybe_bool_from_last("is_rsi_daily_oversold")
        is_rsi_weekly_oversold_proxy = _maybe_bool_from_last("is_rsi_weekly_oversold_proxy")
        is_rsi_bottoming_signal = _maybe_bool_from_last("is_rsi_bottoming_signal")
        is_post_panic_volume_contraction = _maybe_bool_from_last("is_post_panic_volume_contraction")
        bottoming_tech_signal_count = 0
        if ahr999_val is not None and ahr999_val < 1.0:
            bottoming_tech_signal_count += 1
        if is_rsi_bottoming_signal is True:
            bottoming_tech_signal_count += 1
        if is_post_panic_volume_contraction is True:
            bottoming_tech_signal_count += 1

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
            "ahr999": float(ahr999_val) if ahr999_val is not None else None,
            "ahr999_sub_1": bool(ahr999_val < 1.0) if ahr999_val is not None else None,
            "ahr999_sub_07": bool(ahr999_val < 0.7) if ahr999_val is not None else None,
            "rsi14": float(rsi14_val) if rsi14_val is not None else None,
            "rsi14w": float(rsi14w_val) if rsi14w_val is not None else None,
            "is_rsi_daily_oversold": is_rsi_daily_oversold,
            "is_rsi_weekly_oversold_proxy": is_rsi_weekly_oversold_proxy,
            "is_rsi_bottoming_signal": is_rsi_bottoming_signal,
            "volume_ratio_30": float(volume_ratio_30) if volume_ratio_30 is not None else None,
            "is_post_panic_volume_contraction": is_post_panic_volume_contraction,
            "bottoming_tech_signal_count": int(bottoming_tech_signal_count),
            "metrics_as_of_date": last_metric_date.isoformat() if last_metric_date is not None else None,
            "metrics_age_days": int(metrics_age_days) if metrics_age_days is not None else None,
            "is_stale": bool(metrics_is_stale),
            "freshness_max_age_days": MARKET_CONTEXT_MAX_AGE_DAYS,
            "dca_cost": float(dca_cost) if dca_cost is not None else None,
            "trend_value": float(trend_value) if trend_value is not None else None,
            "ratio_dca_current": float(ratio_dca_current) if ratio_dca_current is not None else None,
            "ratio_trend_current": float(ratio_trend_current) if ratio_trend_current is not None else None,
            "is_double_undervalued": bool(is_double_undervalued),
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
        "oi_percentile": None,
        "oi_quadrant": None,
        "ma_regime": None,
        "ma_spread": None,
        "usdjpy_risk_level": None,
        "overall_summary": None,
        # Free proxies from daily report snapshot
        "fear_greed_value": None,
        "fear_greed_classification": None,
        "fear_panic_score": None,
        "is_extreme_fear_proxy": None,
        "hashrate_30d_change_pct": None,
        "miner_stress_proxy": None,
        "is_stale": True,
        "freshness_max_age_days": MACRO_CONTEXT_MAX_AGE_DAYS,
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
        free_bottoming_metrics = (
            section_metrics.get("Supplemental Bottoming Signals", {})
            or
            section_metrics.get("Sentiment & Miner Proxies (Free)", {})
            or section_metrics.get("Free Bottoming Signals", {})
        )

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
        report_is_stale = report_age_days is None or report_age_days < 0 or report_age_days > MACRO_CONTEXT_MAX_AGE_DAYS

        macro_risk_score = _maybe_float(macro_metrics.get("score"))
        macro_risk_regime = macro_metrics.get("regime")
        stress_flags = funding_metrics.get("stress_flags")
        net_liq_delta = _maybe_float(liquidity_metrics.get("net_liquidity_90d_delta"))
        oi_30d_change = _maybe_float(futures_metrics.get("oi_30d_change_pct"))
        oi_percentile = _maybe_float(futures_metrics.get("oi_percentile"))
        oi_quadrant = futures_metrics.get("quadrant")
        ma_regime = ma_metrics.get("regime")
        ma_spread = _maybe_float(ma_metrics.get("ma_spread"))
        usdjpy_risk_level = usdjpy_metrics.get("risk_level")
        fear_greed_value = _maybe_float(free_bottoming_metrics.get("fear_greed_value"))
        fear_greed_classification = free_bottoming_metrics.get("fear_greed_classification")
        fear_panic_score = _maybe_float(free_bottoming_metrics.get("fear_panic_score"))
        is_extreme_fear_proxy = free_bottoming_metrics.get("is_extreme_fear_proxy")
        hashrate_30d_change_pct = _maybe_float(free_bottoming_metrics.get("hashrate_30d_change_pct"))
        miner_stress_proxy = free_bottoming_metrics.get("miner_stress_proxy")

        return {
            "available": True,
            "report_date": report_date,
            "report_age_days": int(report_age_days) if report_age_days is not None else None,
            "macro_risk_score": macro_risk_score,
            "macro_risk_regime": str(macro_risk_regime) if macro_risk_regime is not None else None,
            "stress_flags": int(stress_flags) if stress_flags is not None else None,
            "net_liquidity_90d_delta": net_liq_delta,
            "oi_30d_change_pct": oi_30d_change,
            "oi_percentile": oi_percentile,
            "oi_quadrant": str(oi_quadrant) if oi_quadrant is not None else None,
            "ma_regime": str(ma_regime) if ma_regime is not None else None,
            "ma_spread": ma_spread,
            "usdjpy_risk_level": str(usdjpy_risk_level) if usdjpy_risk_level is not None else None,
            "overall_summary": overall_summary,
            "fear_greed_value": fear_greed_value,
            "fear_greed_classification": str(fear_greed_classification) if fear_greed_classification is not None else None,
            "fear_panic_score": fear_panic_score,
            "is_extreme_fear_proxy": bool(is_extreme_fear_proxy) if is_extreme_fear_proxy is not None else None,
            "hashrate_30d_change_pct": hashrate_30d_change_pct,
            "miner_stress_proxy": str(miner_stress_proxy) if miner_stress_proxy is not None else None,
            "is_stale": bool(report_is_stale),
            "freshness_max_age_days": MACRO_CONTEXT_MAX_AGE_DAYS,
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
            total_btc = None
            try:
                # Keep email portfolio stats consistent with the DCA execution path:
                # prefer real wallet summary (Binance hot wallet + configured cold wallet).
                from dca_service.api.wallet_api import fetch_wallet_summary
                wallet_summary = asyncio.run(fetch_wallet_summary(bg_session))
                total_btc = wallet_summary.total_btc
            except Exception:
                # Fall back to mailer-side DB approximation if wallet summary fetch fails.
                total_btc = None
            from dca_service.services.mailer import send_dca_notification
            send_dca_notification(tx, decision=None, total_btc=total_btc)
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





def _build_wealth_distribution_from_live_data(force_refresh: bool = False) -> Tuple[List[Tuple[float, float, float, str]], Dict[str, Any]]:
    """
    Build wealth distribution list from BitInfoCharts data with provenance.
    
    Behavior:
    - Fresh cache (< 24h): Returns cached data instantly
    - Expired cache (> 24h): Fetches new data, falls back to stale cache if fetch fails
    - No runtime cache: Uses bundled static data when live fetch fails, labeled in metadata
    
    Returns:
        Tuple of wealth distribution tiers and source metadata.
        Tiers are (min_btc, max_btc, percentile_top, percentile_str), sorted by min_btc descending.
        percentile_top is float for comparison, percentile_str preserves original formatting.
        
    Raises:
        ValueError: If no distribution data is available from live, runtime cache, or bundled static data
    """
    from dca_service.services.distribution_scraper import (
        fetch_distribution_with_status,
        parse_tier_range,
        parse_percentile_value,
    )

    snapshot = fetch_distribution_with_status(
        use_cache=not force_refresh,
        allow_static_fallback=True,
        allow_stale_cache=True,
    )
    distribution_data = snapshot.get("data") or []
    
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
    
    logger.info(
        "Built wealth distribution from %s data: %s tiers",
        snapshot.get("source", "unknown"),
        len(wealth_dist),
    )
    return wealth_dist, snapshot

@router.get("/stats/distribution")
def get_wealth_distribution(
    force_refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
):
    """Return the wealth distribution table with data freshness headers."""
    from dca_service.services.distribution_scraper import fetch_distribution_with_status
    try:
        snapshot = fetch_distribution_with_status(
            use_cache=not force_refresh,
            allow_static_fallback=True,
            allow_stale_cache=True,
        )
        headers = {
            "X-Data-Status": str(snapshot.get("data_status") or "live"),
            "X-Data-Source": str(snapshot.get("source") or "bitinfocharts"),
        }
        if snapshot.get("as_of"):
            headers["X-Data-As-Of"] = str(snapshot["as_of"])
        return JSONResponse(content=snapshot["data"], headers=headers)
    except ValueError as e:
        raise HTTPException(
            status_code=503,
            detail="Wealth distribution data is currently unavailable",
        ) from e

@router.get("/stats/percentile")
async def get_user_percentile(
    force_refresh: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Calculate the user's wealth percentile based on total BTC holdings.
    
    Uses BitInfoCharts distribution data:
    - Fresh cache (< 24h): Returns cached data instantly
    - Expired cache (> 24h): Fetches new data, falls back to stale cache if fetch fails
    - No cache: Raises HTTP 503 error (won't show bad data)
    """
    from dca_service.api.wallet_api import get_wallet_summary
    
    # Use the same logic as wallet summary to ensure consistency
    wallet_summary = await get_wallet_summary(session)
    total_btc = wallet_summary.total_btc
    
    try:
        # Get wealth distribution (raises ValueError if no data available)
        wealth_distribution, distribution_meta = _build_wealth_distribution_from_live_data(force_refresh=force_refresh)
        
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
            "data_status": distribution_meta.get("data_status", "live"),
            "source": distribution_meta.get("source", "bitinfocharts"),
            "as_of": distribution_meta.get("as_of"),
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
            "data_status": "unavailable",
            "source": "unavailable",
            "as_of": None,
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
                "manual_flags": [],
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
        group["manual_flags"].append(bool(tx.is_manual))
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
                "manual_flags": group["manual_flags"],
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
                "manual_flags": e.get("manual_flags", []),
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
                "weighted_avg_buy_price_usd": None,
                "weighted_avg_price_position": None,
                "high_zone_buy_ratio": 0.0,
                "low_zone_buy_ratio": 0.0,
                "high_zone_usd_ratio": 0.0,
                "low_zone_usd_ratio": 0.0,
                "burst_trading_ratio": 0.0,
                "size_price_position_corr": None,
                "largest_event_share": 0.0,
                "top3_event_share": 0.0,
                "weekend_ratio": 0.0,
                "manual_event_ratio": 0.0,
                "dca_event_ratio": 0.0,
                "active_buy_event_ratio": 0.0,
                "active_buy_usd_ratio": 0.0,
                "dca_usd_ratio": 0.0,
                "active_buy_avg_cost_usd": None,
                "dca_avg_cost_usd": None,
                "active_buy_cost_premium_pct": None,
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
    high_zone_usd = 0.0
    low_zone_usd = 0.0
    burst_count = 0
    weekend_count = 0
    manual_count = 0
    dca_count = 0
    active_buy_count = 0
    active_buy_usd = 0.0
    active_buy_btc = 0.0
    dca_usd = 0.0
    dca_btc = 0.0
    price_positions: List[float] = []

    diagnostics: List[Dict[str, Any]] = []
    for idx, event in enumerate(events):
        ts = event["timestamp"]
        if ts.weekday() >= 5:
            weekend_count += 1
        purchase_type = _classify_purchase_trigger(
            event.get("source_types", []),
            event.get("manual_flags", []),
        )
        if "MANUAL" in event["source_types"] or purchase_type == "ACTIVE_BUY":
            manual_count += 1
        if "DCA" in event["source_types"] or purchase_type == "DCA":
            dca_count += 1
        if purchase_type == "ACTIVE_BUY":
            active_buy_count += 1
            active_buy_usd += max(float(event["amount_usd"]), 0.0)
            active_buy_btc += max(float(event["amount_btc"]), 0.0)
        elif purchase_type == "DCA":
            dca_usd += max(float(event["amount_usd"]), 0.0)
            dca_btc += max(float(event["amount_btc"]), 0.0)

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
            high_zone_usd += max(float(event["amount_usd"]), 0.0)
        if price_position <= 0.25:
            low_zone_count += 1
            low_zone_usd += max(float(event["amount_usd"]), 0.0)

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
                "purchase_type": purchase_type,
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
    weighted_avg_buy_price_usd = (total_invested_usd / total_btc) if total_btc > 0 else None
    active_buy_avg_cost_usd = (active_buy_usd / active_buy_btc) if active_buy_btc > 0 else None
    dca_avg_cost_usd = (dca_usd / dca_btc) if dca_btc > 0 else None
    active_buy_cost_premium_pct = (
        ((active_buy_avg_cost_usd - dca_avg_cost_usd) / dca_avg_cost_usd) * 100.0
        if active_buy_avg_cost_usd is not None and dca_avg_cost_usd is not None and dca_avg_cost_usd > 0
        else None
    )
    all_prices = [max(e["avg_price_usd"], 0.0) for e in events if e["avg_price_usd"] > 0]
    weighted_avg_price_position = None
    if weighted_avg_buy_price_usd is not None and all_prices:
        min_price = min(all_prices)
        max_price = max(all_prices)
        if max_price > min_price:
            weighted_avg_price_position = (weighted_avg_buy_price_usd - min_price) / (max_price - min_price)
            weighted_avg_price_position = min(max(float(weighted_avg_price_position), 0.0), 1.0)
        else:
            weighted_avg_price_position = 0.5
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
        "weighted_avg_buy_price_usd": float(weighted_avg_buy_price_usd) if weighted_avg_buy_price_usd is not None else None,
        "weighted_avg_price_position": (
            float(weighted_avg_price_position) if weighted_avg_price_position is not None else None
        ),
        "high_zone_buy_ratio": float(high_zone_count / event_count) if event_count > 0 else 0.0,
        "low_zone_buy_ratio": float(low_zone_count / event_count) if event_count > 0 else 0.0,
        "high_zone_usd_ratio": float(high_zone_usd / total_invested_usd) if total_invested_usd > 0 else 0.0,
        "low_zone_usd_ratio": float(low_zone_usd / total_invested_usd) if total_invested_usd > 0 else 0.0,
        "burst_trading_ratio": float(burst_count / len(intervals_days)) if intervals_days else 0.0,
        "size_price_position_corr": _safe_corr(event_amounts, price_positions),
        "largest_event_share": float(largest_event_share),
        "top3_event_share": float(top3_event_share),
        "weekend_ratio": float(weekend_count / event_count) if event_count > 0 else 0.0,
        "manual_event_ratio": float(manual_count / event_count) if event_count > 0 else 0.0,
        "dca_event_ratio": float(dca_count / event_count) if event_count > 0 else 0.0,
        "active_buy_event_ratio": float(active_buy_count / event_count) if event_count > 0 else 0.0,
        "active_buy_usd_ratio": float(active_buy_usd / total_invested_usd) if total_invested_usd > 0 else 0.0,
        "dca_usd_ratio": float(dca_usd / total_invested_usd) if total_invested_usd > 0 else 0.0,
        "active_buy_avg_cost_usd": (
            float(active_buy_avg_cost_usd) if active_buy_avg_cost_usd is not None else None
        ),
        "dca_avg_cost_usd": float(dca_avg_cost_usd) if dca_avg_cost_usd is not None else None,
        "active_buy_cost_premium_pct": (
            float(active_buy_cost_premium_pct) if active_buy_cost_premium_pct is not None else None
        ),
    }

    style_tags: List[str] = []
    if summary["low_zone_buy_ratio"] >= summary["high_zone_buy_ratio"] + 0.1:
        style_tags.append("Dip Buyer")
    if summary["high_zone_buy_ratio"] >= summary["low_zone_buy_ratio"] + 0.1:
        style_tags.append("Momentum Chaser")
    if (
        summary["high_zone_usd_ratio"] >= 0.45
        and summary["high_zone_usd_ratio"] >= summary["high_zone_buy_ratio"] + 0.20
    ):
        style_tags.append("High-cost Weighted")
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

    if (
        summary["high_zone_usd_ratio"] >= 0.45
        and summary["high_zone_usd_ratio"] >= summary["high_zone_buy_ratio"] + 0.20
    ):
        issues.append(
            {
                "severity": "warning",
                "title": "High-cost basis from larger high-zone buys",
                "detail": "High-zone buys are a much larger share of deployed capital than of event count, which keeps average cost elevated.",
            }
        )

    if (
        summary["low_zone_buy_ratio"] >= 0.50
        and summary["low_zone_usd_ratio"] <= summary["low_zone_buy_ratio"] - 0.20
    ):
        issues.append(
            {
                "severity": "warning",
                "title": "Low-zone count overstates deployed capital",
                "detail": "Many buys occurred in lower zones, but a smaller share of total USD was deployed there, so average cost repairs slowly.",
            }
        )

    if (
        summary["weighted_avg_price_position"] is not None
        and summary["weighted_avg_price_position"] >= 0.45
        and summary["low_zone_buy_ratio"] >= 0.50
    ):
        issues.append(
            {
                "severity": "info",
                "title": "Average cost still mid-to-high",
                "detail": "Your average cost is still high relative to your observed buy range despite frequent lower-zone entries.",
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
    total_invested_usd = float(summary.get("total_invested_usd", 0.0) or 0.0)
    total_btc = float(summary.get("total_btc", 0.0) or 0.0)
    current_avg_cost_usd = (total_invested_usd / total_btc) if total_btc > 0 else None
    proposed_btc = amount_usdc / current_price_usd if current_price_usd > 0 else 0.0
    proposed_avg_cost_after_buy = None
    proposed_avg_cost_delta = None
    proposed_avg_cost_delta_pct = None
    if total_btc + proposed_btc > 0:
        proposed_avg_cost_after_buy = (total_invested_usd + amount_usdc) / (total_btc + proposed_btc)
        if current_avg_cost_usd is not None:
            proposed_avg_cost_delta = proposed_avg_cost_after_buy - current_avg_cost_usd
            proposed_avg_cost_delta_pct = (
                (proposed_avg_cost_delta / current_avg_cost_usd) * 100.0 if current_avg_cost_usd > 0 else None
            )
    cost_basis_repair_opportunity = bool(
        current_avg_cost_usd is not None
        and current_price_usd > 0
        and current_price_usd < current_avg_cost_usd
    )

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
    market_available_raw = bool(market_ctx.get("available"))
    market_is_stale = bool(market_ctx.get("is_stale")) if "is_stale" in market_ctx else False
    metrics_age_days = market_ctx.get("metrics_age_days")
    try:
        metrics_age_days_int = int(metrics_age_days) if metrics_age_days is not None else None
    except (TypeError, ValueError):
        metrics_age_days_int = None
    if metrics_age_days_int is not None and (
        metrics_age_days_int < 0 or metrics_age_days_int > MARKET_CONTEXT_MAX_AGE_DAYS
    ):
        market_is_stale = True
    market_context_usable = bool(market_available_raw and not market_is_stale)

    if market_context_usable:
        deep_value_regime = bool(market_ctx.get("deep_value_regime"))
        breakout_high_regime = bool(market_ctx.get("breakout_high_regime"))
        near_180d_low = bool(market_ctx.get("near_180d_low"))
        near_ath = bool(market_ctx.get("near_ath") or market_ctx.get("near_180d_high"))
        new_ath = bool(market_ctx.get("new_ath"))
        new_180d_low = bool(market_ctx.get("new_180d_low"))
        drop_24h_pct = _as_float(market_ctx.get("drop_24h_pct"))
        current_vs_180d_low_pct = _as_float(market_ctx.get("current_vs_180d_low_pct"))
        current_vs_ath_pct = _as_float(market_ctx.get("current_vs_ath_pct"))
        ahr999_now = _as_float(market_ctx.get("ahr999"))
        ahr999_sub_1 = bool(market_ctx.get("ahr999_sub_1")) if market_ctx.get("ahr999_sub_1") is not None else False
        ahr999_sub_07 = bool(market_ctx.get("ahr999_sub_07")) if market_ctx.get("ahr999_sub_07") is not None else False
        rsi14_now = _as_float(market_ctx.get("rsi14"))
        rsi14w_now = _as_float(market_ctx.get("rsi14w"))
        is_rsi_bottoming_signal = (
            bool(market_ctx.get("is_rsi_bottoming_signal"))
            if market_ctx.get("is_rsi_bottoming_signal") is not None
            else False
        )
        is_post_panic_volume_contraction = (
            bool(market_ctx.get("is_post_panic_volume_contraction"))
            if market_ctx.get("is_post_panic_volume_contraction") is not None
            else False
        )
        ratio_dca_current = _as_float(market_ctx.get("ratio_dca_current") or market_ctx.get("ratio_dca"))
        ratio_trend_current = _as_float(market_ctx.get("ratio_trend_current") or market_ctx.get("ratio_trend"))
        double_undervalued = bool(market_ctx.get("is_double_undervalued"))
    else:
        deep_value_regime = False
        breakout_high_regime = False
        near_180d_low = False
        near_ath = False
        new_ath = False
        new_180d_low = False
        drop_24h_pct = None
        current_vs_180d_low_pct = None
        current_vs_ath_pct = None
        ahr999_now = None
        ahr999_sub_1 = False
        ahr999_sub_07 = False
        rsi14_now = None
        rsi14w_now = None
        is_rsi_bottoming_signal = False
        is_post_panic_volume_contraction = False
        ratio_dca_current = None
        ratio_trend_current = None
        double_undervalued = False

    persistent_value_regime = bool(
        market_context_usable
        and double_undervalued
        and (ratio_dca_current is None or ratio_dca_current <= 1.00)
        and (ratio_trend_current is None or ratio_trend_current <= 0.70)
        and cost_basis_repair_opportunity
    )

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
    recent_active_buy_24h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 24 * 3600
        and _classify_purchase_trigger(e.get("source_types", []), e.get("manual_flags", [])) == "ACTIVE_BUY"
    )
    recent_active_buy_48h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 48 * 3600
        and _classify_purchase_trigger(e.get("source_types", []), e.get("manual_flags", [])) == "ACTIVE_BUY"
    )
    recent_active_buy_72h_count = sum(
        1
        for e in events
        if isinstance(e.get("timestamp"), datetime)
        and (now_utc - e["timestamp"]).total_seconds() <= 72 * 3600
        and _classify_purchase_trigger(e.get("source_types", []), e.get("manual_flags", [])) == "ACTIVE_BUY"
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
    high_zone_usd_ratio = float(summary.get("high_zone_usd_ratio", 0.0) or 0.0)
    low_zone_usd_ratio = float(summary.get("low_zone_usd_ratio", 0.0) or 0.0)
    active_buy_event_ratio = float(summary.get("active_buy_event_ratio", 0.0) or 0.0)
    active_buy_usd_ratio = float(summary.get("active_buy_usd_ratio", 0.0) or 0.0)
    dca_usd_ratio = float(summary.get("dca_usd_ratio", 0.0) or 0.0)
    active_buy_avg_cost_usd = _as_float(summary.get("active_buy_avg_cost_usd"))
    dca_avg_cost_usd = _as_float(summary.get("dca_avg_cost_usd"))
    active_buy_cost_premium_pct = _as_float(summary.get("active_buy_cost_premium_pct"))

    burst_habit = bool(burst_ratio >= 0.45 and event_count >= 8)
    inconsistent_habit = bool(event_amount_cv >= 0.9 and event_count >= 8)
    high_zone_habit = bool(high_zone_ratio >= 0.55 and high_zone_ratio > low_zone_ratio + 0.15 and event_count >= 8)
    high_cost_weighted_habit = bool(
        high_zone_usd_ratio >= 0.45 and high_zone_usd_ratio >= high_zone_ratio + 0.20 and event_count >= 6
    )
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

    price_vs_avg_cost_pct = (
        ((current_price_usd - current_avg_cost_usd) / current_avg_cost_usd) * 100.0
        if current_avg_cost_usd
        else None
    )
    if price_vs_avg_cost_pct is None:
        active_buy_drawdown_tier = None
    elif price_vs_avg_cost_pct <= -35.0:
        active_buy_drawdown_tier = "35%"
    elif price_vs_avg_cost_pct <= -25.0:
        active_buy_drawdown_tier = "25%"
    elif price_vs_avg_cost_pct <= -15.0:
        active_buy_drawdown_tier = "15%"
    else:
        active_buy_drawdown_tier = None
    active_buy_drawdown_gate = active_buy_drawdown_tier is not None

    macro_risk_score = _as_float(macro_ctx.get("macro_risk_score"))
    macro_risk_regime = str(macro_ctx.get("macro_risk_regime") or "").strip().lower() or None
    stress_flags = macro_ctx.get("stress_flags")
    try:
        stress_flags_int = int(stress_flags) if stress_flags is not None else None
    except (TypeError, ValueError):
        stress_flags_int = None
    net_liquidity_delta = _as_float(macro_ctx.get("net_liquidity_90d_delta"))
    oi_30d_change_pct = _as_float(macro_ctx.get("oi_30d_change_pct"))
    oi_percentile = _as_float(macro_ctx.get("oi_percentile"))
    oi_quadrant = str(macro_ctx.get("oi_quadrant") or "").strip()
    oi_quadrant_lower = oi_quadrant.lower()
    ma_regime = str(macro_ctx.get("ma_regime") or "").strip().lower() or None
    ma_spread = _as_float(macro_ctx.get("ma_spread"))
    fear_greed_value = _as_float(macro_ctx.get("fear_greed_value"))
    fear_panic_score = _as_float(macro_ctx.get("fear_panic_score"))
    is_extreme_fear_proxy = (
        bool(macro_ctx.get("is_extreme_fear_proxy"))
        if macro_ctx.get("is_extreme_fear_proxy") is not None
        else False
    )
    hashrate_30d_change_pct = _as_float(macro_ctx.get("hashrate_30d_change_pct"))
    miner_stress_proxy = str(macro_ctx.get("miner_stress_proxy") or "").strip().lower() or None
    report_age_days = macro_ctx.get("report_age_days")
    try:
        report_age_days_int = int(report_age_days) if report_age_days is not None else None
    except (TypeError, ValueError):
        report_age_days_int = None
    macro_is_stale = bool(macro_ctx.get("is_stale")) if "is_stale" in macro_ctx else False
    if report_age_days_int is not None and (
        report_age_days_int < 0 or report_age_days_int > MACRO_CONTEXT_MAX_AGE_DAYS
    ):
        macro_is_stale = True
    macro_available = bool(macro_ctx.get("available") and not macro_is_stale)
    if not macro_available:
        macro_risk_score = None
        macro_risk_regime = None
        stress_flags_int = None
        net_liquidity_delta = None
        oi_30d_change_pct = None
        oi_percentile = None
        oi_quadrant = ""
        oi_quadrant_lower = ""
        ma_regime = None
        ma_spread = None
        fear_greed_value = None
        fear_panic_score = None
        is_extreme_fear_proxy = False
        hashrate_30d_change_pct = None
        miner_stress_proxy = None

    # Multi-signal capitulation mode:
    # If price is deeply depressed and several independent stress/deleveraging
    # signals align, do not auto-downsize solely because of historical sizing habits.
    capitulation_signals = 0
    if persistent_value_regime:
        capitulation_signals += 1
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
    strong_dip_add_mode = bool(
        ((deep_value_regime or new_180d_low) and capitulation_signals >= 3)
        or (persistent_value_regime and capitulation_signals >= 2)
    )
    range_30d_pct = _as_float(market_ctx.get("range_30d_pct")) if market_context_usable else None
    realized_vol_30d_pct = _as_float(market_ctx.get("realized_vol_30d_pct")) if market_context_usable else None
    sideways_30d = bool(market_ctx.get("sideways_30d")) if market_context_usable else False
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
    active_buy_dominant = bool(
        event_count >= 8
        and active_buy_usd_ratio >= 0.70
        and active_buy_event_ratio >= 0.50
    )
    active_buy_underperforming_dca = bool(
        active_buy_cost_premium_pct is not None
        and active_buy_cost_premium_pct >= 3.0
    )
    recent_active_buy_dense = bool(recent_active_buy_24h_count >= 1 or recent_active_buy_72h_count >= 2)
    active_buy_pressure = bool(
        dense_buy_mode
        and active_buy_dominant
        and recent_active_buy_dense
        and (active_buy_underperforming_dca or high_cost_weighted_habit)
    )
    dense_sideways_no_extra_mode = bool(
        dense_buy_mode
        and ongoing_dense_flow
        and (local_sideways_by_trades or sideways_30d)
        and not macro_takeoff_mode
        and not strong_dip_add_mode
        and not persistent_value_regime
    )
    active_buy_discipline_mode = bool(
        active_buy_pressure
        and not active_buy_drawdown_gate
        and not macro_takeoff_mode
        and not strong_dip_add_mode
        and not persistent_value_regime
    )
    no_extra_add_needed_mode = bool(
        dense_sideways_no_extra_mode
        or active_buy_discipline_mode
    )

    reasons: List[str] = []
    applied_lessons: List[str] = []
    macro_notes: List[str] = []
    tech_notes: List[str] = []
    freshness_notes: List[str] = []
    if market_available_raw and not market_context_usable:
        if metrics_age_days_int is not None:
            freshness_notes.append(
                f"market CSV is stale ({metrics_age_days_int}d old; as of {market_ctx.get('metrics_as_of_date') or 'unknown'}), so technical market signals are ignored."
            )
        else:
            freshness_notes.append("market CSV freshness is unknown/stale, so technical market signals are ignored.")
    if bool(macro_ctx.get("available")) and not macro_available:
        if report_age_days_int is not None:
            freshness_notes.append(
                f"macro snapshot is stale ({report_age_days_int}d old; as of {macro_ctx.get('report_date') or 'unknown'}), so macro signals are ignored."
            )
        else:
            freshness_notes.append("macro snapshot freshness is unknown/stale, so macro signals are ignored.")

    valuation_support_signals: List[str] = []
    valuation_defense_signals: List[str] = []
    if market_context_usable:
        if double_undervalued:
            valuation_support_signals.append("double undervaluation")
        if ratio_trend_current is not None:
            if ratio_trend_current <= 0.70:
                valuation_support_signals.append(f"trend ratio {ratio_trend_current:.2f}")
            elif ratio_trend_current >= 1.15:
                valuation_defense_signals.append(f"trend ratio {ratio_trend_current:.2f}")
        if ratio_dca_current is not None:
            if ratio_dca_current < 1.0:
                valuation_support_signals.append(f"DCA ratio {ratio_dca_current:.2f}")
            elif ratio_dca_current >= 1.10:
                valuation_defense_signals.append(f"DCA ratio {ratio_dca_current:.2f}")
        if ahr999_now is not None:
            if ahr999_now < 0.70:
                valuation_support_signals.append(f"AHR999 {ahr999_now:.2f}")
            elif ahr999_now < 1.0:
                valuation_support_signals.append(f"AHR999 {ahr999_now:.2f}")
            elif ahr999_now >= 1.20:
                valuation_defense_signals.append(f"AHR999 {ahr999_now:.2f}")
        if current_vs_180d_low_pct is not None and current_vs_180d_low_pct <= 5.0:
            valuation_support_signals.append(f"{current_vs_180d_low_pct:.1f}% above 180d low")
        if current_vs_ath_pct is not None and current_vs_ath_pct >= -5.0:
            valuation_defense_signals.append(f"{current_vs_ath_pct:.1f}% from ATH")
    if breakout_high_regime or new_ath or near_ath:
        valuation_defense_signals.append("near breakout/high zone")
    if valuation_defense_signals and not (deep_value_regime or persistent_value_regime):
        valuation_bias = "defensive"
    elif valuation_support_signals:
        valuation_bias = "supportive"
    else:
        valuation_bias = "neutral"

    price_vs_avg_cost_pct = (
        ((current_price_usd - current_avg_cost_usd) / current_avg_cost_usd) * 100.0
        if current_avg_cost_usd
        else None
    )
    cost_basis_signals: List[str] = []
    if cost_basis_repair_opportunity and price_vs_avg_cost_pct is not None:
        cost_basis_signals.append(f"price {price_vs_avg_cost_pct:.1f}% below avg cost")
        cost_basis_bias = "supportive"
    elif price_vs_avg_cost_pct is not None and price_vs_avg_cost_pct >= 12.0:
        cost_basis_signals.append(f"price {price_vs_avg_cost_pct:.1f}% above avg cost")
        cost_basis_bias = "defensive"
    else:
        cost_basis_bias = "neutral"

    macro_support_signals: List[str] = []
    macro_defense_signals: List[str] = []
    if macro_available:
        if macro_risk_score is not None:
            if macro_risk_score <= 35.0:
                macro_support_signals.append(f"risk {macro_risk_score:.1f}")
            elif macro_risk_score >= 70.0:
                macro_defense_signals.append(f"risk {macro_risk_score:.1f}")
        if stress_flags_int is not None:
            if stress_flags_int == 0:
                macro_support_signals.append("no stress flags")
            elif stress_flags_int >= 2:
                macro_defense_signals.append(f"stress flags {stress_flags_int}")
        if net_liquidity_delta is not None:
            if net_liquidity_delta >= 80.0:
                macro_support_signals.append(f"net liquidity {net_liquidity_delta:+.1f}B")
            elif net_liquidity_delta <= -120.0:
                macro_defense_signals.append(f"net liquidity {net_liquidity_delta:+.1f}B")
    if macro_defense_signals:
        macro_bias = "defensive"
    elif macro_support_signals:
        macro_bias = "supportive"
    else:
        macro_bias = "neutral"

    trend_signals: List[str] = []
    if ma_regime == "bearish":
        trend_bias = "defensive"
        trend_signals.append("MA regime bearish")
    elif ma_regime == "bullish":
        trend_bias = "supportive"
        trend_signals.append("MA regime bullish")
    else:
        trend_bias = "neutral"
    if ma_spread is not None:
        trend_signals.append(f"MA spread {ma_spread:+.0f}")

    leverage_support_signals: List[str] = []
    leverage_defense_signals: List[str] = []
    if macro_available:
        if oi_percentile is not None:
            if oi_percentile >= 85.0:
                leverage_defense_signals.append(f"OI percentile {oi_percentile:.1f}")
            elif oi_percentile <= 20.0:
                leverage_support_signals.append(f"OI percentile {oi_percentile:.1f}")
        if oi_quadrant_lower:
            if "crowded" in oi_quadrant_lower or "squeeze" in oi_quadrant_lower:
                leverage_defense_signals.append(oi_quadrant)
            elif "deleverag" in oi_quadrant_lower or "washed" in oi_quadrant_lower:
                leverage_support_signals.append(oi_quadrant)
        if oi_30d_change_pct is not None:
            if oi_30d_change_pct >= 25.0:
                leverage_defense_signals.append(f"OI 30d {oi_30d_change_pct:+.1f}%")
            elif oi_30d_change_pct <= -15.0:
                leverage_support_signals.append(f"OI 30d {oi_30d_change_pct:+.1f}%")
    if leverage_defense_signals:
        leverage_bias = "defensive"
    elif leverage_support_signals:
        leverage_bias = "supportive"
    else:
        leverage_bias = "neutral"

    multiplier = 1.0
    if persistent_value_regime:
        multiplier *= 1.80
        reasons.append("BTC is double-undervalued and below your cost basis, so a larger repair add is allowed.")
        if strong_dip_add_mode:
            multiplier *= 1.12
            reasons.append("Cost-basis repair has multi-signal support, so the size cap is loosened.")
    elif deep_value_regime or new_180d_low:
        multiplier *= 1.65
        reasons.append("Price is in a deep pullback zone, so adding now is allowed with a larger size than baseline.")
        if strong_dip_add_mode:
            multiplier *= 1.25
            reasons.append("Multi-signal capitulation setup confirmed, so larger add size is allowed.")
    elif no_extra_add_needed_mode:
        multiplier *= 0.50 if active_buy_discipline_mode else 0.68
        if active_buy_discipline_mode:
            reasons.append(
                "Active buys are already dense, dominant, and more expensive than DCA; wait for DCA or a 15%+ cost-basis drawdown."
            )
        else:
            reasons.append(f"Market is sideways while your {cadence_label} is already dense, so extra add is usually unnecessary.")
    elif macro_takeoff_mode:
        multiplier *= 1.15
        reasons.append("Macro takeoff signals are aligned, so adding above baseline is justified.")
    elif price_position <= 0.25 or near_180d_low:
        multiplier *= 1.20
        reasons.append("Price is in your historical lower zone, which fits your dip-buy edge.")
    elif breakout_high_regime or new_ath:
        multiplier *= 0.55
        reasons.append("Price is in a breakout-high regime, so size should stay defensive.")
    elif near_ath or price_position >= 0.80:
        multiplier *= 0.72
        reasons.append("Price is near historical highs, so this add should be smaller.")

    allow_practical_value_boost = not (
        no_extra_add_needed_mode
        or breakout_high_regime
        or near_ath
        or new_ath
        or deep_value_regime
        or persistent_value_regime
    )
    if allow_practical_value_boost and valuation_bias == "supportive":
        multiplier *= 1.06
        reasons.append("Practical valuation ratios are below long-term anchors, so a modest add is supported.")
    elif valuation_bias == "defensive" and not (deep_value_regime or persistent_value_regime):
        multiplier *= 0.94
        reasons.append("Practical valuation ratios are no longer cheap, so size is trimmed.")

    if allow_practical_value_boost and cost_basis_bias == "supportive":
        multiplier *= 1.04
        reasons.append("The add helps repair your average cost without relying only on buy frequency.")
    elif cost_basis_bias == "defensive" and not (deep_value_regime or persistent_value_regime):
        multiplier *= 0.96
        reasons.append("Current price is already above your average cost, so cost-basis repair is not active.")

    if macro_available:
        if macro_risk_score is not None:
            if macro_risk_score >= 70:
                multiplier *= 0.92 if (deep_value_regime or persistent_value_regime) else 0.82
                macro_notes.append(f"Macro risk score {macro_risk_score:.1f}/100 is high; size is trimmed.")
            elif macro_risk_score <= 35:
                multiplier *= 1.05
                macro_notes.append(f"Macro risk score {macro_risk_score:.1f}/100 is contained; normal risk budget is acceptable.")
        if stress_flags_int is not None:
            if stress_flags_int >= 2:
                multiplier *= 0.95 if (deep_value_regime or persistent_value_regime) else 0.88
                macro_notes.append(f"Funding stress flags = {stress_flags_int}; keep risk tighter.")
            elif stress_flags_int == 0:
                macro_notes.append("Funding stress flags are low.")
        if net_liquidity_delta is not None:
            if net_liquidity_delta <= -120:
                multiplier *= 0.96 if (deep_value_regime or persistent_value_regime) else 0.90
                macro_notes.append(f"Net liquidity 90d delta is weak ({net_liquidity_delta:+.1f}B), so keep size controlled.")
            elif net_liquidity_delta >= 80:
                multiplier *= 1.07
                macro_notes.append(f"Net liquidity 90d delta is supportive ({net_liquidity_delta:+.1f}B).")
        if leverage_bias == "defensive":
            leverage_factor = 0.95 if (deep_value_regime or persistent_value_regime) else 0.92
            if oi_percentile is not None and oi_percentile >= 90.0 and not (deep_value_regime or persistent_value_regime):
                leverage_factor = 0.88
            multiplier *= leverage_factor
            macro_notes.append(
                "Futures positioning is crowded ("
                + "; ".join(leverage_defense_signals[:2])
                + "); trim add size."
            )
        elif leverage_bias == "supportive":
            multiplier *= 1.05
            macro_notes.append(
                "Futures positioning shows prior deleveraging ("
                + "; ".join(leverage_support_signals[:2])
                + "); normal adds are easier to justify."
            )
        if ma_regime == "bearish" and not (deep_value_regime or persistent_value_regime):
            multiplier *= 0.95
            macro_notes.append("Trend regime is bearish, so size is capped slightly.")
        elif ma_regime == "bullish":
            multiplier *= 1.04
            macro_notes.append("Trend regime is bullish, which supports risk-taking.")
        if macro_risk_regime and macro_risk_regime != "neutral":
            macro_notes.append(f"Macro regime: {macro_risk_regime}.")
    else:
        if bool(macro_ctx.get("available")) and macro_is_stale:
            macro_notes.append("Macro snapshot is stale and ignored; decision uses live price + your history only.")
        else:
            macro_notes.append("Macro snapshot unavailable; decision uses live price + your history only.")

    # Free-data technical bottoming overlays (advisory only):
    # Use as small, capped sizing/risk adjustments and never override hard WAIT guards.
    # AHR999 is read from existing metrics CSV (no reimplementation here).
    tech_signal_hits = 0
    tech_signal_labels: List[str] = []
    tech_multiplier_factor = 1.0

    if ahr999_sub_1:
        tech_signal_hits += 1
        tech_signal_labels.append("AHR999<1")
        tech_multiplier_factor *= 1.05
        if ahr999_sub_07:
            tech_multiplier_factor *= 1.05
            tech_signal_labels.append("AHR999<0.7")

    if is_rsi_bottoming_signal:
        tech_signal_hits += 1
        tech_signal_labels.append("RSI bottoming")
        tech_multiplier_factor *= 1.08
    elif (rsi14_now is not None and rsi14_now < 30.0) or (rsi14w_now is not None and rsi14w_now <= 35.0):
        # Partial credit if only one of the two RSI conditions is met.
        tech_multiplier_factor *= 1.03
        tech_signal_labels.append("RSI partial")

    if is_post_panic_volume_contraction:
        tech_signal_hits += 1
        tech_signal_labels.append("post-panic volume contraction")
        tech_multiplier_factor *= 1.06

    # Free sentiment/miner proxies from daily_report snapshot
    if is_extreme_fear_proxy or (fear_greed_value is not None and fear_greed_value <= 25.0):
        tech_signal_hits += 1
        tech_signal_labels.append("F&G extreme fear")
        tech_multiplier_factor *= 1.05
        if fear_greed_value is not None and fear_greed_value <= 15.0:
            tech_multiplier_factor *= 1.03
            tech_signal_labels.append("F&G <=15")

    if hashrate_30d_change_pct is not None and hashrate_30d_change_pct <= -5.0:
        tech_signal_hits += 1
        tech_signal_labels.append("hashrate down 30d")
        tech_multiplier_factor *= 1.03
        if hashrate_30d_change_pct <= -10.0:
            tech_multiplier_factor *= 1.02
            tech_signal_labels.append("hashrate <-10%")

    if tech_signal_hits >= 2:
        tech_multiplier_factor *= 1.05
        tech_signal_labels.append("multi-signal confluence")

    # Do not use bottoming overlays to fight breakout/high-chase protections.
    allow_tech_bottoming_boost = not (breakout_high_regime or near_ath or new_ath)
    tech_multiplier_applied = 1.0
    if allow_tech_bottoming_boost and tech_multiplier_factor > 1.0:
        tech_multiplier_applied = min(tech_multiplier_factor, 1.20)
        multiplier *= tech_multiplier_applied
        if tech_signal_labels:
            tech_notes.append(
                "Technical bottoming overlays support size: "
                + ", ".join(tech_signal_labels[:4])
                + f" (capped factor x{tech_multiplier_applied:.2f})."
            )
    elif tech_signal_hits > 0 and not allow_tech_bottoming_boost:
        tech_notes.append("Bottoming overlays detected but ignored because price is in/near breakout-high regime.")

    if tech_signal_hits > 0 and allow_tech_bottoming_boost:
        bottoming_bias = "supportive"
    elif tech_signal_hits > 0:
        bottoming_bias = "neutral"
    else:
        bottoming_bias = "neutral"

    if burst_habit and recent_48h_count >= 1:
        if strong_dip_add_mode:
            multiplier *= 0.98
            applied_lessons.append("Burst habit penalty is mostly relaxed because this is a confirmed capitulation setup.")
        else:
            multiplier *= 0.92 if deep_value_regime else 0.80
            applied_lessons.append("You often cluster buys within 48h; size is reduced to avoid burst-overtrading.")

    if (high_zone_habit or high_cost_weighted_habit) and (breakout_high_regime or near_ath or price_position >= 0.75):
        multiplier *= 0.85
        applied_lessons.append("Your high-cost exposure is already meaningful; high-zone adds get an extra size haircut.")

    if active_buy_pressure and not active_buy_drawdown_gate:
        applied_lessons.append("Dense active-buy pressure is active; discretionary adds wait for DCA or a 15%+ cost-basis drawdown.")

    suggested_amount = max(10.0, baseline_amount * multiplier)
    if inconsistent_habit:
        # Keep size executable and stable, but allow wider ranges in deep drawdowns.
        if strong_dip_add_mode or persistent_value_regime:
            upper = max(baseline_amount * 10.0, amount_usdc * 1.10)
        else:
            upper = baseline_amount * (3.00 if deep_value_regime else 1.20)
        lower = baseline_amount * 0.85
        suggested_amount = min(max(suggested_amount, lower), upper)
        applied_lessons.append("Your historical sizing is unstable; suggestion is anchored to reduce noise in outcomes.")

    suggested_amount = round(max(10.0, suggested_amount), 2)
    proposed_gap_pct = ((amount_usdc - suggested_amount) / suggested_amount * 100.0) if suggested_amount > 0 else 0.0

    decision = "BUY"
    if not (deep_value_regime or persistent_value_regime):
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
        if deep_value_regime or persistent_value_regime:
            band = 0.35
        else:
            band = 0.10 if inconsistent_habit else 0.15
        range_min = round(max(10.0, suggested_amount * (1 - band)), 2)
        range_max = round(max(range_min, suggested_amount * (1 + band)), 2)
    else:
        range_min = 0.0
        range_max = 0.0

    lower_alignment_factor = 0.65 if (deep_value_regime or persistent_value_regime) else 0.85
    upper_alignment_factor = 1.35 if (deep_value_regime or persistent_value_regime) else 1.15
    input_below_suggested = bool(amount_usdc < suggested_amount * lower_alignment_factor)
    input_above_suggested = bool(amount_usdc > suggested_amount * upper_alignment_factor)

    if not reasons:
        reasons.append("No major risk signal is active; this setup is close to your normal decision profile.")
    reasons.extend(macro_notes[:2])
    reasons.extend(tech_notes[:1])
    reasons = reasons[:4]

    if not applied_lessons:
        applied_lessons.append("No major bad-habit penalty was triggered in this setup.")

    if decision == "WAIT":
        action_code = "NO_BUY"
        advised_amount_usdc = 0.0
        input_alignment = "WAIT"
        action_now = "No buy now."
        if no_extra_add_needed_mode:
            if active_buy_discipline_mode:
                call_reason = (
                    "No extra active buy: active buys are already dense, dominant, and more expensive than DCA; "
                    "wait for DCA or a 15%+ cost-basis drawdown."
                )
            elif recent_trade_range_pct is not None:
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
        if input_above_suggested:
            action_code = "BUY_LESS"
            input_alignment = "ABOVE_SUGGESTED"
            action_now = f"Buy less: ${suggested_amount:,.2f}."
            if deep_value_regime or persistent_value_regime:
                call_reason = "Deep-value signals support adding, but your input is above the widened size band."
            else:
                call_reason = "Your input is larger than the rational size for this setup."
            final_call = f"BUY LESS: ${suggested_amount:,.2f}"
        elif input_below_suggested:
            action_code = "BUY_MORE"
            input_alignment = "BELOW_SUGGESTED"
            action_now = f"Buy more: ${suggested_amount:,.2f}."
            if deep_value_regime or persistent_value_regime:
                call_reason = "Deep-value signals support adding; your input is below the widened size band."
            else:
                call_reason = "Your input is below the size implied by current edge."
            final_call = f"BUY MORE: ${suggested_amount:,.2f}"
        elif strong_dip_add_mode:
            action_code = "BUY_AS_PLANNED"
            input_alignment = "ALIGNED_CAPITULATION"
            action_now = f"Buy ${amount_usdc:,.2f} now."
            call_reason = "Capitulation setup is confirmed across multiple signals."
            final_call = f"BUY AS PLANNED: ${amount_usdc:,.2f}"
        elif persistent_value_regime:
            action_code = "BUY_AS_PLANNED"
            input_alignment = "ALIGNED_DEEP_VALUE"
            action_now = f"Buy ${amount_usdc:,.2f} now."
            call_reason = "Double-undervaluation and cost-basis repair both support this add."
            final_call = f"BUY AS PLANNED: ${amount_usdc:,.2f}"
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
    if leverage_bias == "defensive":
        risk_score += 4 if (deep_value_regime or persistent_value_regime) else 7
    elif leverage_bias == "supportive":
        risk_score -= 3
    if trend_bias == "defensive" and not (deep_value_regime or persistent_value_regime):
        risk_score += 4
    if deep_value_regime:
        risk_score -= 18
    if persistent_value_regime:
        risk_score -= 14
    if allow_tech_bottoming_boost and tech_signal_hits >= 2:
        risk_score -= min(8, 4 + (tech_signal_hits - 2) * 2)
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
    suggested_avg_cost_after_buy = None
    suggested_avg_cost_delta = None
    if decision == "BUY" and total_btc + estimated_btc > 0:
        suggested_avg_cost_after_buy = (total_invested_usd + suggested_amount) / (total_btc + estimated_btc)
        if current_avg_cost_usd is not None:
            suggested_avg_cost_delta = suggested_avg_cost_after_buy - current_avg_cost_usd
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
    if freshness_notes:
        lines.append("Data freshness: " + " ".join(freshness_notes))
    if current_avg_cost_usd is not None and proposed_avg_cost_after_buy is not None:
        delta_text = (
            f"{proposed_avg_cost_delta:+,.2f}"
            if proposed_avg_cost_delta is not None
            else "+0.00"
        )
        lines.append(
            "Cost basis: "
            f"current avg ${current_avg_cost_usd:,.2f}; "
            f"your proposed add would move it to ${proposed_avg_cost_after_buy:,.2f} "
            f"({delta_text})."
        )
    lines.append(
        "Price context: "
        f"{price_vs_hist_median_pct:+.2f}% vs your historical median fill, "
        f"{(current_vs_180d_low_pct if current_vs_180d_low_pct is not None else 0.0):+.2f}% vs 180d low, "
        f"24h move {(drop_24h_pct if drop_24h_pct is not None else 0.0):+.2f}%."
    )
    lines.append(
        "Practical signals: "
        f"valuation {valuation_bias}; "
        f"cost basis {cost_basis_bias}; "
        f"macro {macro_bias}; "
        f"trend {trend_bias}; "
        f"leverage {leverage_bias}; "
        f"bottoming {bottoming_bias}."
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
    tech_parts: List[str] = []
    if ahr999_now is not None:
        tech_parts.append(f"AHR999 {ahr999_now:.3f}")
    if rsi14_now is not None:
        tech_parts.append(f"RSI14 {rsi14_now:.1f}")
    if rsi14w_now is not None:
        tech_parts.append(f"RSI14W* {rsi14w_now:.1f}")
    if market_context_usable and market_ctx.get("volume_ratio_30") is not None:
        try:
            tech_parts.append(f"vol/30D {float(market_ctx['volume_ratio_30']):.2f}x")
        except (TypeError, ValueError):
            pass
    if fear_greed_value is not None:
        tech_parts.append(f"F&G {fear_greed_value:.0f}")
    if fear_panic_score is not None:
        tech_parts.append(f"panic {fear_panic_score:.0f}/100")
    if hashrate_30d_change_pct is not None:
        tech_parts.append(f"hashrate30d {hashrate_30d_change_pct:+.1f}%")
    tech_flags: List[str] = []
    if ahr999_sub_1:
        tech_flags.append("AHR999<1")
    if is_rsi_bottoming_signal:
        tech_flags.append("RSI bottoming")
    if is_post_panic_volume_contraction:
        tech_flags.append("post-panic volume contraction")
    if is_extreme_fear_proxy:
        tech_flags.append("F&G extreme fear")
    if hashrate_30d_change_pct is not None and hashrate_30d_change_pct <= -5.0:
        tech_flags.append("miner stress proxy")
    if tech_parts or tech_flags:
        suffix = f" | flags: {', '.join(tech_flags)}" if tech_flags else ""
        lines.append("Technical bottoming: " + ", ".join(tech_parts) + suffix + ".")
    lines.append("Why:")
    displayed_reasons = reasons[:2]
    for idx, reason in enumerate(displayed_reasons, start=1):
        lines.append(f"{idx}. {reason}")
    lines.append("Applied lesson:")
    for idx, lesson in enumerate(applied_lessons[:1], start=len(displayed_reasons) + 1):
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
            "high_zone_buy_ratio": high_zone_ratio,
            "low_zone_buy_ratio": low_zone_ratio,
            "high_zone_usd_ratio": high_zone_usd_ratio,
            "low_zone_usd_ratio": low_zone_usd_ratio,
            "high_cost_weighted_habit": high_cost_weighted_habit,
            "dense_buy_mode": dense_buy_mode,
            "dense_dca_mode": dense_buy_mode,
            "source_mix_label": source_mix_label,
            "dca_event_ratio": dca_event_ratio,
            "manual_event_ratio": manual_event_ratio,
            "active_buy_event_ratio": active_buy_event_ratio,
            "active_buy_usd_ratio": active_buy_usd_ratio,
            "dca_usd_ratio": dca_usd_ratio,
            "active_buy_avg_cost_usd": (
                float(active_buy_avg_cost_usd) if active_buy_avg_cost_usd is not None else None
            ),
            "dca_avg_cost_usd": float(dca_avg_cost_usd) if dca_avg_cost_usd is not None else None,
            "active_buy_cost_premium_pct": (
                float(active_buy_cost_premium_pct) if active_buy_cost_premium_pct is not None else None
            ),
            "active_buy_dominant": active_buy_dominant,
            "active_buy_underperforming_dca": active_buy_underperforming_dca,
            "active_buy_pressure": active_buy_pressure,
            "active_buy_drawdown_gate": active_buy_drawdown_gate,
            "active_buy_drawdown_tier": active_buy_drawdown_tier,
            "active_buy_discipline_mode": active_buy_discipline_mode,
            "dense_sideways_no_extra_mode": dense_sideways_no_extra_mode,
            "no_extra_add_needed_mode": no_extra_add_needed_mode,
            "recent_sideways_by_trades": local_sideways_by_trades,
            "recent_trade_range_pct": float(recent_trade_range_pct) if recent_trade_range_pct is not None else None,
            "current_vs_recent_trade_median_pct": (
                float(current_vs_recent_trade_median_pct) if current_vs_recent_trade_median_pct is not None else None
            ),
            "recent_events_24h": recent_24h_count,
            "recent_events_48h": recent_48h_count,
            "recent_events_72h": recent_72h_count,
            "recent_active_buy_events_24h": recent_active_buy_24h_count,
            "recent_active_buy_events_48h": recent_active_buy_48h_count,
            "recent_active_buy_events_72h": recent_active_buy_72h_count,
            "last_event_time": last_event_ts.isoformat() if isinstance(last_event_ts, datetime) else None,
        },
        "cost_basis_context": {
            "total_invested_usd": float(total_invested_usd),
            "total_btc": float(total_btc),
            "current_avg_cost_usd": float(current_avg_cost_usd) if current_avg_cost_usd is not None else None,
            "current_price_usd": float(current_price_usd),
            "price_vs_avg_cost_pct": (
                float(((current_price_usd - current_avg_cost_usd) / current_avg_cost_usd) * 100.0)
                if current_avg_cost_usd
                else None
            ),
            "cost_basis_repair_opportunity": bool(cost_basis_repair_opportunity),
            "proposed_btc": float(proposed_btc),
            "proposed_avg_cost_after_buy_usd": (
                float(proposed_avg_cost_after_buy) if proposed_avg_cost_after_buy is not None else None
            ),
            "proposed_avg_cost_delta_usd": (
                float(proposed_avg_cost_delta) if proposed_avg_cost_delta is not None else None
            ),
            "proposed_avg_cost_delta_pct": (
                float(proposed_avg_cost_delta_pct) if proposed_avg_cost_delta_pct is not None else None
            ),
            "suggested_avg_cost_after_buy_usd": (
                float(suggested_avg_cost_after_buy) if suggested_avg_cost_after_buy is not None else None
            ),
            "suggested_avg_cost_delta_usd": (
                float(suggested_avg_cost_delta) if suggested_avg_cost_delta is not None else None
            ),
            "persistent_value_regime": bool(persistent_value_regime),
            "is_double_undervalued": bool(double_undervalued),
            "ratio_dca_current": float(ratio_dca_current) if ratio_dca_current is not None else None,
            "ratio_trend_current": float(ratio_trend_current) if ratio_trend_current is not None else None,
        },
        "practical_signal_context": {
            "valuation": {
                "bias": valuation_bias,
                "signals": valuation_support_signals if valuation_bias != "defensive" else valuation_defense_signals,
                "support_signals": valuation_support_signals,
                "defense_signals": valuation_defense_signals,
                "ratio_dca_current": float(ratio_dca_current) if ratio_dca_current is not None else None,
                "ratio_trend_current": float(ratio_trend_current) if ratio_trend_current is not None else None,
                "ahr999": float(ahr999_now) if ahr999_now is not None else None,
                "current_vs_180d_low_pct": (
                    float(current_vs_180d_low_pct) if current_vs_180d_low_pct is not None else None
                ),
                "current_vs_ath_pct": float(current_vs_ath_pct) if current_vs_ath_pct is not None else None,
            },
            "cost_basis": {
                "bias": cost_basis_bias,
                "signals": cost_basis_signals,
                "current_avg_cost_usd": float(current_avg_cost_usd) if current_avg_cost_usd is not None else None,
                "price_vs_avg_cost_pct": float(price_vs_avg_cost_pct) if price_vs_avg_cost_pct is not None else None,
                "repair_opportunity": bool(cost_basis_repair_opportunity),
            },
            "macro": {
                "bias": macro_bias,
                "available": bool(macro_available),
                "support_signals": macro_support_signals,
                "defense_signals": macro_defense_signals,
                "macro_risk_score": float(macro_risk_score) if macro_risk_score is not None else None,
                "stress_flags": stress_flags_int,
                "net_liquidity_90d_delta": (
                    float(net_liquidity_delta) if net_liquidity_delta is not None else None
                ),
            },
            "trend": {
                "bias": trend_bias,
                "signals": trend_signals,
                "ma_regime": ma_regime,
                "ma_spread": float(ma_spread) if ma_spread is not None else None,
            },
            "leverage": {
                "bias": leverage_bias,
                "support_signals": leverage_support_signals,
                "defense_signals": leverage_defense_signals,
                "oi_percentile": float(oi_percentile) if oi_percentile is not None else None,
                "oi_quadrant": oi_quadrant or None,
                "oi_30d_change_pct": float(oi_30d_change_pct) if oi_30d_change_pct is not None else None,
            },
            "bottoming": {
                "bias": bottoming_bias,
                "signals": tech_signal_labels[:4],
                "tech_signal_hits": int(tech_signal_hits),
                "allow_tech_bottoming_boost": bool(allow_tech_bottoming_boost),
            },
        },
        "market_context": market_ctx,
        "macro_context": macro_ctx,
        "data_freshness": {
            "market_context_usable": bool(market_context_usable),
            "market_is_stale": bool(market_is_stale),
            "metrics_as_of_date": market_ctx.get("metrics_as_of_date"),
            "metrics_age_days": metrics_age_days_int,
            "market_max_age_days": MARKET_CONTEXT_MAX_AGE_DAYS,
            "macro_context_usable": bool(macro_available),
            "macro_is_stale": bool(macro_is_stale),
            "macro_report_date": macro_ctx.get("report_date"),
            "macro_report_age_days": report_age_days_int,
            "macro_max_age_days": MACRO_CONTEXT_MAX_AGE_DAYS,
            "notes": freshness_notes,
        },
        "technical_bottoming_context": {
            "ahr999": ahr999_now,
            "ahr999_sub_1": bool(ahr999_sub_1),
            "ahr999_sub_07": bool(ahr999_sub_07),
            "rsi14": rsi14_now,
            "rsi14w": rsi14w_now,
            "is_rsi_bottoming_signal": bool(is_rsi_bottoming_signal),
            "is_post_panic_volume_contraction": bool(is_post_panic_volume_contraction),
            "fear_greed_value": fear_greed_value,
            "fear_panic_score": fear_panic_score,
            "is_extreme_fear_proxy": bool(is_extreme_fear_proxy),
            "hashrate_30d_change_pct": hashrate_30d_change_pct,
            "miner_stress_proxy": miner_stress_proxy,
            "tech_signal_hits": int(tech_signal_hits),
            "tech_multiplier_applied": float(tech_multiplier_applied),
            "allow_tech_bottoming_boost": bool(allow_tech_bottoming_boost),
        },
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
            fills = live_result.get("trades") or []
            fill_trade_ids = []
            for fill in fills:
                try:
                    fill_trade_ids.append(int(fill.get("id")))
                except (TypeError, ValueError, AttributeError):
                    continue
            # We store at most one Binance trade id on the aggregate order row.
            # For split fills, order_id + source="BINANCE" prevents sync duplicates.
            primary_trade_id = fill_trade_ids[0] if fill_trade_ids else None
            if executed_price <= 0 or executed_btc <= 0:
                raise ValueError("Live order returned invalid execution data.")

            # Idempotency guard: sync service may import the same Binance trade in a narrow
            # race window before this request writes its local transaction row.
            existing_tx = None
            if binance_order_id is not None:
                existing_tx = session.exec(
                    select(DCATransaction)
                    .where(DCATransaction.binance_order_id == binance_order_id)
                    .order_by(col(DCATransaction.timestamp).desc())
                ).first()

            if existing_tx:
                tx = existing_tx
                tx.status = "SUCCESS"
                tx.fiat_amount = executed_usd
                tx.btc_amount = executed_btc
                tx.price = executed_price
                tx.ahr999 = 0.0
                tx.notes = notes
                tx.intended_amount_usd = amount_usdc
                tx.executed_amount_usd = executed_usd
                tx.executed_amount_btc = executed_btc
                tx.avg_execution_price_usd = executed_price
                tx.fee_amount = fee_amount
                tx.fee_asset = fee_asset
                # Distinguish "manual-triggered but app-executed" from "synced manual import"
                # so incremental sync recognizes this order as already recorded.
                tx.source = "BINANCE"
                tx.is_manual = True
                if tx.binance_order_id is None:
                    tx.binance_order_id = binance_order_id
                if tx.binance_trade_id is None and primary_trade_id is not None:
                    tx.binance_trade_id = primary_trade_id
                session.add(tx)
            else:
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
                    source="BINANCE",
                    is_manual=True,
                    binance_order_id=binance_order_id,
                    binance_trade_id=primary_trade_id,
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
                source="MANUAL",
                is_manual=True,
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
        source="MANUAL",
        is_manual=True,
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


PURCHASE_CSV_FIELDS = [
    "purchase_datetime",
    "purchase_type",
    "usd_spent",
    "btc_bought",
    "avg_price_usd",
    "fee_usd",
]


def _csv_number(value: float, digits: int = 12) -> float:
    return float(round(float(value or 0.0), digits))


def _classify_purchase_trigger(sources: List[str], manual_flags: List[bool]) -> str:
    source_set = {source.upper() for source in sources if source}
    any_manual = any(manual_flags)
    if "DCA" in source_set or ("SIMULATED" in source_set and not any_manual):
        return "DCA"
    if "BINANCE" in source_set or "MANUAL" in source_set:
        return "ACTIVE_BUY"
    if "SIMULATED" in source_set:
        return "SIMULATED"
    return "UNKNOWN"


def _build_purchase_csv(transactions: List[DCATransaction]) -> str:
    grouped: Dict[str, Dict[str, Any]] = {}
    ordered_keys: List[str] = []

    for idx, tx in enumerate(transactions):
        amount_usd = _effective_fiat_amount(tx)
        amount_btc = _effective_btc_amount(tx)
        avg_price = _effective_price(tx)
        if amount_usd <= 0 or amount_btc <= 0:
            continue

        timestamp = tx.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        if tx.binance_order_id is not None:
            key = f"order:{tx.binance_order_id}"
        else:
            fallback_id = tx.id if tx.id is not None else idx
            key = f"tx:{fallback_id}"

        if key not in grouped:
            grouped[key] = {
                "timestamp": timestamp,
                "amount_usd": 0.0,
                "amount_btc": 0.0,
                "weighted_price_sum": 0.0,
                "price_weight": 0.0,
                "fee_usd": 0.0,
                "fill_count": 0,
                "binance_order_id": tx.binance_order_id,
                "trade_ids": [],
                "sources": [],
                "manual_flags": [],
                "notes": [],
            }
            ordered_keys.append(key)

        group = grouped[key]
        group["timestamp"] = min(group["timestamp"], timestamp)
        group["amount_usd"] += amount_usd
        group["amount_btc"] += amount_btc
        group["fill_count"] += 1
        group["sources"].append(tx.source or "UNKNOWN")
        group["manual_flags"].append(bool(tx.is_manual))
        if tx.notes and tx.notes not in group["notes"]:
            group["notes"].append(tx.notes)
        if tx.binance_trade_id is not None:
            group["trade_ids"].append(int(tx.binance_trade_id))

        group["fee_usd"] += _fee_to_usd(tx, avg_price)

        weight = amount_btc if amount_btc > 0 else amount_usd
        if weight > 0:
            group["price_weight"] += weight
            group["weighted_price_sum"] += avg_price * weight

    rows = []
    for key in ordered_keys:
        group = grouped[key]
        timestamp = group["timestamp"]
        avg_price = (
            group["weighted_price_sum"] / group["price_weight"]
            if group["price_weight"] > 0
            else 0.0
        )
        sources = sorted(set(group["sources"]))
        rows.append(
            {
                "purchase_datetime": timestamp.isoformat(),
                "purchase_type": _classify_purchase_trigger(sources, group["manual_flags"]),
                "usd_spent": _csv_number(group["amount_usd"]),
                "btc_bought": _csv_number(group["amount_btc"]),
                "avg_price_usd": _csv_number(avg_price),
                "fee_usd": _csv_number(group["fee_usd"]),
                "_sort_key": timestamp.isoformat(),
            }
        )

    rows.sort(key=lambda row: row["_sort_key"])

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=PURCHASE_CSV_FIELDS,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in PURCHASE_CSV_FIELDS})

    return output.getvalue()


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


@router.get("/stats/trading-style.csv")
def download_trading_style_csv(
    language: str = Query(default="en"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Export successful BTC purchases as order-level CSV rows.

    Split fills with the same binance_order_id are merged into one purchase row.
    """
    txs = session.exec(
        select(DCATransaction)
        .where(DCATransaction.status == "SUCCESS")
        .order_by(DCATransaction.timestamp)
    ).all()
    csv_text = _build_purchase_csv(txs)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="bitcoin-purchases.csv"',
        },
    )
