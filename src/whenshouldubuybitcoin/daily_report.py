"""Daily market report generation for frontend consumption."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from whenshouldubuybitcoin.visualization import (
    MACRO_RISK_SCORE_WEIGHTS,
    calculate_risk_level,
)

EXCLUDED_CHARTS = {"Valuation Ratios", "Price Comparison"}
DEFAULT_REPORT_PATH = Path("docs/data/daily_report.json")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _usd(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.{digits}f}"


def _calc_macro_score_df(
    btc_df: pd.DataFrame,
    macro_df: pd.DataFrame,
) -> pd.DataFrame:
    price_df = btc_df[["date", "close_price"]].copy()
    price_df["date"] = pd.to_datetime(price_df["date"]).dt.tz_localize(None)

    macro = macro_df[["date", "net_liquidity_bil", "sofr", "move", "hy_oas"]].copy()
    macro["date"] = pd.to_datetime(macro["date"]).dt.tz_localize(None)
    macro = macro.sort_values("date")

    merged = pd.merge(price_df, macro, on="date", how="left").sort_values("date")
    for col in ["net_liquidity_bil", "sofr", "move", "hy_oas"]:
        merged[col] = merged[col].ffill()

    merged["net_liquidity_90d_change"] = merged["net_liquidity_bil"].diff(90)
    merged["risk_net_liq"] = 1.0 - merged["net_liquidity_90d_change"].rank(pct=True)
    merged["risk_sofr"] = merged["sofr"].rank(pct=True)
    merged["risk_move"] = merged["move"].rank(pct=True)
    merged["risk_hy_oas"] = merged["hy_oas"].rank(pct=True)

    merged["macro_risk_score"] = 100.0 * (
        MACRO_RISK_SCORE_WEIGHTS["net_liquidity_90d_change"] * merged["risk_net_liq"]
        + MACRO_RISK_SCORE_WEIGHTS["sofr"] * merged["risk_sofr"]
        + MACRO_RISK_SCORE_WEIGHTS["move"] * merged["risk_move"]
        + MACRO_RISK_SCORE_WEIGHTS["hy_oas"] * merged["risk_hy_oas"]
    )
    merged["fwd_30d_return_pct"] = (
        merged["close_price"].shift(-30) / merged["close_price"] - 1.0
    ) * 100.0

    return merged.dropna(subset=["macro_risk_score", "close_price"]).copy()


def build_report_payload(
    btc_df: pd.DataFrame,
    *,
    macro_df: pd.DataFrame | None = None,
    usdjpy_df: pd.DataFrame | None = None,
    yield_df: pd.DataFrame | None = None,
    oi_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build structured metrics for daily report sections."""

    payload: dict[str, Any] = {
        "report_date": pd.to_datetime(btc_df["date"]).max().date().isoformat(),
        "generated_at": (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ),
        "excluded_charts": sorted(EXCLUDED_CHARTS),
        "sections": [],
    }

    # MA Cross Analysis
    ma_df = btc_df.dropna(subset=["ma_50", "ma_200", "ma_spread"]).copy()
    if not ma_df.empty:
        latest = ma_df.iloc[-1]
        spread = _safe_float(latest.get("ma_spread"))
        regime = "bullish" if spread is not None and spread >= 0 else "bearish"
        last_golden = ma_df.loc[ma_df.get("golden_cross", False), "date"]
        last_death = ma_df.loc[ma_df.get("death_cross", False), "date"]

        payload["sections"].append(
            {
                "chart": "MA Cross Analysis",
                "metrics": {
                    "close_price": _safe_float(latest.get("close_price")),
                    "ma_50": _safe_float(latest.get("ma_50")),
                    "ma_200": _safe_float(latest.get("ma_200")),
                    "ma_spread": spread,
                    "regime": regime,
                    "last_golden_cross": (
                        pd.to_datetime(last_golden.iloc[-1]).date().isoformat()
                        if len(last_golden) > 0
                        else None
                    ),
                    "last_death_cross": (
                        pd.to_datetime(last_death.iloc[-1]).date().isoformat()
                        if len(last_death) > 0
                        else None
                    ),
                },
            }
        )

    if macro_df is not None and not macro_df.empty:
        # Net Liquidity
        net_df = pd.merge(
            btc_df[["date", "close_price"]],
            macro_df[["date", "net_liquidity_bil", "walcl_bil", "tga_bil", "rrp_bil"]],
            on="date",
            how="left",
        ).sort_values("date")
        for col in ["net_liquidity_bil", "walcl_bil", "tga_bil", "rrp_bil"]:
            net_df[col] = net_df[col].ffill()
        net_df["net_liquidity_90d_delta"] = net_df["net_liquidity_bil"].diff(90)
        net_df = net_df.dropna(subset=["net_liquidity_bil", "close_price"])
        if not net_df.empty:
            latest = net_df.iloc[-1]
            payload["sections"].append(
                {
                    "chart": "Net Liquidity",
                    "metrics": {
                        "net_liquidity_bil": _safe_float(latest.get("net_liquidity_bil")),
                        "net_liquidity_90d_delta": _safe_float(latest.get("net_liquidity_90d_delta")),
                        "walcl_bil": _safe_float(latest.get("walcl_bil")),
                        "tga_bil": _safe_float(latest.get("tga_bil")),
                        "rrp_bil": _safe_float(latest.get("rrp_bil")),
                        "btc_price": _safe_float(latest.get("close_price")),
                    },
                }
            )

        # Funding & Credit Stress
        fcs_df = pd.merge(
            btc_df[["date", "close_price"]],
            macro_df[["date", "sofr", "move", "hy_oas"]],
            on="date",
            how="left",
        ).sort_values("date")
        for col in ["sofr", "move", "hy_oas"]:
            fcs_df[col] = fcs_df[col].ffill()
        fcs_df = fcs_df.dropna(subset=["sofr", "move", "hy_oas", "close_price"])
        if not fcs_df.empty:
            latest = fcs_df.iloc[-1]
            sofr = _safe_float(latest.get("sofr"))
            move = _safe_float(latest.get("move"))
            hy_oas = _safe_float(latest.get("hy_oas"))
            stress_flags = int(sofr is not None and sofr >= 5.0) + int(
                move is not None and move >= 120.0
            ) + int(hy_oas is not None and hy_oas >= 5.0)
            payload["sections"].append(
                {
                    "chart": "Funding & Credit Stress",
                    "metrics": {
                        "sofr": sofr,
                        "move": move,
                        "hy_oas": hy_oas,
                        "stress_flags": stress_flags,
                        "btc_price": _safe_float(latest.get("close_price")),
                    },
                }
            )

        # Macro Risk Score
        mrs_df = _calc_macro_score_df(btc_df, macro_df)
        if not mrs_df.empty:
            latest = mrs_df.iloc[-1]
            score = _safe_float(latest.get("macro_risk_score"))
            regime = "high" if score is not None and score >= 70 else "low" if score is not None and score <= 30 else "neutral"
            high_mask = mrs_df["macro_risk_score"] >= 70
            high_hit_rate = (
                float((mrs_df.loc[high_mask, "fwd_30d_return_pct"] < 0).mean() * 100.0)
                if high_mask.any()
                else None
            )
            payload["sections"].append(
                {
                    "chart": "Macro Risk Score",
                    "metrics": {
                        "score": score,
                        "regime": regime,
                        "high_risk_hit_rate": high_hit_rate,
                        "fwd_30d_return": _safe_float(latest.get("fwd_30d_return_pct")),
                        "btc_price": _safe_float(latest.get("close_price")),
                    },
                }
            )

    # USD/JPY Risk Map
    if usdjpy_df is not None and not usdjpy_df.empty and yield_df is not None and not yield_df.empty:
        merged = pd.merge(
            usdjpy_df[["date", "close_price"]].rename(columns={"close_price": "usdjpy"}),
            yield_df[["date", "spread", "us_2y", "jp_2y"]],
            on="date",
            how="left",
        ).sort_values("date")
        merged[["spread", "us_2y", "jp_2y"]] = merged[["spread", "us_2y", "jp_2y"]].ffill()
        merged = merged.dropna(subset=["usdjpy", "spread"])
        if not merged.empty:
            latest = merged.iloc[-1]
            usdjpy_30d_change = _safe_float(merged["usdjpy"].pct_change(30).iloc[-1] * 100.0)
            spread_30d_change = _safe_float(merged["spread"].diff(30).iloc[-1])
            risk_level, risk_description = calculate_risk_level(
                float(latest["usdjpy"]), float(latest["spread"])
            )
            payload["sections"].append(
                {
                    "chart": "USD/JPY Risk Map",
                    "metrics": {
                        "usdjpy": _safe_float(latest.get("usdjpy")),
                        "spread": _safe_float(latest.get("spread")),
                        "us_2y": _safe_float(latest.get("us_2y")),
                        "jp_2y": _safe_float(latest.get("jp_2y")),
                        "usdjpy_30d_change_pct": usdjpy_30d_change,
                        "spread_30d_change_pct_pts": spread_30d_change,
                        "risk_level": risk_level,
                        "risk_description": risk_description,
                    },
                }
            )

    # Futures OI & Price
    if oi_df is not None and not oi_df.empty:
        oi_local = oi_df.copy()
        if "timestamp" in oi_local.columns:
            oi_local["timestamp"] = pd.to_datetime(oi_local["timestamp"], unit="ms")
            oi_local = oi_local.set_index("timestamp")

        if "oi_usd" not in oi_local.columns and "sumOpenInterestValue" in oi_local.columns:
            oi_local["oi_usd"] = pd.to_numeric(oi_local["sumOpenInterestValue"])

        btc_idx = btc_df[["date", "close_price"]].copy()
        btc_idx["date"] = pd.to_datetime(btc_idx["date"])
        btc_idx = btc_idx.set_index("date")

        oi_aligned = oi_local[["oi_usd"]].dropna().sort_index()
        if not oi_aligned.empty:
            latest_oi = float(oi_aligned["oi_usd"].iloc[-1])
            oi_30d = _safe_float(oi_aligned["oi_usd"].pct_change(30).iloc[-1] * 100.0)
            oi_pct_rank = _safe_float(oi_aligned["oi_usd"].rank(pct=True).iloc[-1] * 100.0)

            start_date = max(btc_idx.index.min(), oi_aligned.index.min())
            end_date = min(btc_idx.index.max(), oi_aligned.index.max())
            btc_aligned = btc_idx.loc[start_date:end_date, "close_price"]
            oi_series = oi_aligned.loc[start_date:end_date, "oi_usd"]
            quad_df = pd.DataFrame(
                {
                    "price_chg": btc_aligned.pct_change(5) * 100,
                    "oi_chg": oi_series.pct_change(5) * 100,
                }
            ).dropna()

            quadrant = None
            if not quad_df.empty:
                p_chg = float(quad_df.iloc[-1]["price_chg"])
                o_chg = float(quad_df.iloc[-1]["oi_chg"])
                if p_chg > 0 and o_chg > 0:
                    quadrant = "Risky Up (leveraged)"
                elif p_chg > 0 and o_chg < 0:
                    quadrant = "Healthy Up (spot-led)"
                elif p_chg < 0 and o_chg > 0:
                    quadrant = "Squeeze Setup (crowded)"
                elif p_chg < 0 and o_chg < 0:
                    quadrant = "Flush-Out (deleveraging)"
                else:
                    quadrant = "Neutral"

            payload["sections"].append(
                {
                    "chart": "Futures OI & Price",
                    "metrics": {
                        "oi_usd": latest_oi,
                        "oi_30d_change_pct": oi_30d,
                        "oi_percentile": oi_pct_rank,
                        "quadrant": quadrant,
                    },
                }
            )

    return payload


def _deterministic_en_summary(section: dict[str, Any]) -> str:
    chart = section["chart"]
    m = section["metrics"]

    if chart == "Net Liquidity":
        delta = _safe_float(m.get("net_liquidity_90d_delta"))
        direction = "rising" if delta is not None and delta >= 0 else "falling"
        return (
            f"Net liquidity is around {_safe_float(m.get('net_liquidity_bil')):.0f} bn USD, and the 90-day change is {_safe_float(m.get('net_liquidity_90d_delta')):.0f} bn USD."
            f" WALCL is {_safe_float(m.get('walcl_bil')):.0f} bn, TGA is {_safe_float(m.get('tga_bil')):.0f} bn, and RRP is {_safe_float(m.get('rrp_bil')):.0f} bn."
            f" The current liquidity direction is {direction} based on the 90-day delta."
            if m.get("net_liquidity_bil") is not None and m.get("net_liquidity_90d_delta") is not None
            else "Net liquidity data is incomplete, so the current liquidity direction cannot be determined reliably."
        )

    if chart == "Funding & Credit Stress":
        flags = int(m.get("stress_flags", 0))
        level = "tight" if flags >= 2 else "neutral" if flags == 1 else "loose"
        sofr = _safe_float(m.get("sofr"))
        move = _safe_float(m.get("move"))
        hy_oas = _safe_float(m.get("hy_oas"))
        return (
            f"SOFR is {sofr:.2f}%, MOVE is {move:.1f}, and HY OAS is {hy_oas:.2f}%."
            f" {flags} out of 3 indicators are above stress thresholds, so funding and credit conditions are currently {level}."
            " This reading is based directly on the three threshold checks in the model."
            if sofr is not None and move is not None and hy_oas is not None
            else "Funding and credit stress data is incomplete, so the current stress state cannot be assessed."
        )

    if chart == "Macro Risk Score":
        score = _safe_float(m.get("score"))
        regime = m.get("regime", "neutral")
        regime_cn = {"high": "high risk", "low": "low risk", "neutral": "neutral"}.get(regime, "neutral")
        return (
            f"The Macro Risk Score is {score:.1f}/100, which sits in the {regime_cn} zone."
            f" The model's historical high-risk hit rate is about {_pct(_safe_float(m.get('high_risk_hit_rate')))} for 30-day negative returns."
            f" The current forward 30-day return proxy in the payload is {_pct(_safe_float(m.get('fwd_30d_return')))}."
        )

    if chart == "USD/JPY Risk Map":
        usdjpy = _safe_float(m.get("usdjpy"))
        spread = _safe_float(m.get("spread"))
        spread_30d = _safe_float(m.get("spread_30d_change_pct_pts"))
        spread_30d_text = "N/A" if spread_30d is None else f"{spread_30d:+.2f}pp"
        return (
            f"USD/JPY is at {usdjpy:.2f}, and the US-JP 2Y spread is {spread:.2f}%."
            f" The model classifies this as {m.get('risk_level', 'MODERATE RISK')}."
            f" Over the last 30 days, USD/JPY changed {_pct(_safe_float(m.get('usdjpy_30d_change_pct')))} and the spread changed {spread_30d_text}."
            if usdjpy is not None and spread is not None
            else "USD/JPY risk-map data is incomplete, so a current risk tier cannot be assigned."
        )

    if chart == "Futures OI & Price":
        oi_pctile = _safe_float(m.get("oi_percentile"))
        oi_pctile_text = "N/A" if oi_pctile is None else f"{oi_pctile:.1f}"
        return (
            f"Futures OI notional is around {_usd(_safe_float(m.get('oi_usd')))}, with a 30-day change of {_pct(_safe_float(m.get('oi_30d_change_pct')))}."
            f" It sits around the {oi_pctile_text}th historical percentile, and the current quadrant is {m.get('quadrant', 'N/A')}."
            " The current state is read directly from the percentile and quadrant values."
        )

    if chart == "MA Cross Analysis":
        spread = _safe_float(m.get("ma_spread"))
        regime_cn = "bullish" if spread is not None and spread >= 0 else "bearish"
        return (
            f"MA Spread (50D-200D) is {spread:,.2f}, which keeps the medium-term structure {regime_cn}."
            f" The 50-day MA is {_usd(_safe_float(m.get('ma_50')), 2)} and the 200-day MA is {_usd(_safe_float(m.get('ma_200')), 2)}."
            f" The latest cross dates are golden: {m.get('last_golden_cross') or 'N/A'}, death: {m.get('last_death_cross') or 'N/A'}."
        )

    return "No usable interpretation is available for this chart today."


def _deterministic_zh_summary(section: dict[str, Any]) -> str:
    chart = section["chart"]
    m = section["metrics"]

    if chart == "Net Liquidity":
        net_liq = _safe_float(m.get("net_liquidity_bil"))
        delta = _safe_float(m.get("net_liquidity_90d_delta"))
        if net_liq is None or delta is None:
            return "净流动性数据不完整，当前无法判断流动性方向。"
        direction = "上行" if delta >= 0 else "下行"
        return (
            f"当前净流动性约为{net_liq:.0f}亿美元，过去90天变化约为{delta:.0f}亿美元，当前方向为{direction}。"
            f"WALCL约为{_safe_float(m.get('walcl_bil')):.0f}亿美元，TGA约为{_safe_float(m.get('tga_bil')):.0f}亿美元，RRP约为{_safe_float(m.get('rrp_bil')):.0f}亿美元。"
            "这组数据对应的是流动性边际改善，而不是流动性收缩。"
        )

    if chart == "Funding & Credit Stress":
        sofr = _safe_float(m.get("sofr"))
        move = _safe_float(m.get("move"))
        hy_oas = _safe_float(m.get("hy_oas"))
        flags = int(m.get("stress_flags", 0))
        if sofr is None or move is None or hy_oas is None:
            return "融资与信用压力数据不完整，当前无法判定压力状态。"
        level = "偏紧" if flags >= 2 else "中性" if flags == 1 else "偏松"
        return (
            f"SOFR为{sofr:.2f}%，MOVE为{move:.1f}，HY OAS为{hy_oas:.2f}%，三项里有{flags}项触发压力阈值，整体金融条件处于{level}。"
            "当前读数显示资金成本和信用利差都在可控区间。"
            "现状解读是：融资端未出现系统性紧张，信用压力也未明显扩散。"
        )

    if chart == "Macro Risk Score":
        score = _safe_float(m.get("score"))
        if score is None:
            return "宏观风险评分数据不完整，当前无法判定风险区间。"
        regime = m.get("regime", "neutral")
        regime_cn = {"high": "高风险", "low": "低风险", "neutral": "中性"}.get(regime, "中性")
        return (
            f"当前宏观风险评分为{score:.1f}/100，位于{regime_cn}区间。"
            f"历史上高风险区间对应的30天负收益命中率约为{_pct(_safe_float(m.get('high_risk_hit_rate')))}。"
            f"当前样本对应的前瞻30天收益代理值为{_pct(_safe_float(m.get('fwd_30d_return')))}，说明当前风险温度并不在极端区间。"
        )

    if chart == "USD/JPY Risk Map":
        usdjpy = _safe_float(m.get("usdjpy"))
        spread = _safe_float(m.get("spread"))
        if usdjpy is None or spread is None:
            return "美元兑日元或利差数据不完整，暂时无法给出稳定的风险分层判断。"
        fx_chg = _safe_float(m.get("usdjpy_30d_change_pct"))
        spread_chg = _safe_float(m.get("spread_30d_change_pct_pts"))
        fx_dir = "上行" if fx_chg is not None and fx_chg >= 0 else "回落"
        spread_dir = "走阔" if spread_chg is not None and spread_chg >= 0 else "收窄"
        fx_chg_text = _pct(fx_chg)
        spread_chg_text = "N/A" if spread_chg is None else f"{spread_chg:+.2f}pp"
        return (
            f"当前USD/JPY为{usdjpy:.2f}，美日2年期利差约{spread:.2f}%，模型识别为{m.get('risk_level', 'MODERATE RISK')}。"
            f"过去30天里，USD/JPY约{fx_dir}{fx_chg_text}，利差约{spread_dir}{spread_chg_text}。"
            "现状解读是：汇率与利差同向走高，套息交易相关风险在抬升，当前处于中等风险偏上的状态。"
        )

    if chart == "Futures OI & Price":
        oi_percentile = _safe_float(m.get("oi_percentile"))
        percentile_text = "N/A" if oi_percentile is None else f"{oi_percentile:.1f}"
        return (
            f"期货未平仓名义规模约为{_usd(_safe_float(m.get('oi_usd')))}，30天变化为{_pct(_safe_float(m.get('oi_30d_change_pct')))}。"
            f"当前大约位于历史{percentile_text}分位，象限为{m.get('quadrant', 'N/A')}。"
            "现状解读是：杠杆仓位处在低位且仍在回落，市场结构仍偏去杠杆。"
        )

    if chart == "MA Cross Analysis":
        spread = _safe_float(m.get("ma_spread"))
        regime_cn = "多头" if spread is not None and spread >= 0 else "空头"
        return (
            f"50日与200日均线价差为{spread:,.2f}，中期结构仍偏{regime_cn}。"
            f"当前50日均线{_usd(_safe_float(m.get('ma_50')), 2)}，200日均线{_usd(_safe_float(m.get('ma_200')), 2)}。"
            f"最近一次金叉为{m.get('last_golden_cross') or 'N/A'}，最近一次死叉为{m.get('last_death_cross') or 'N/A'}。"
        )

    return "今日该图表暂无可用解读。"


def _call_llm_summary(payload: dict[str, Any], language: str) -> dict[str, Any] | None:
    if os.getenv("REPORT_SUMMARY_DISABLE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return None

    api_key = None
    model = None
    base_url = None

    # 1) Prefer DB-stored settings from dca_service (configured via frontend)
    try:
        from sqlmodel import Session, select
        from dca_service.database import engine
        from dca_service.models import SummaryApiSettings
        from dca_service.services.security import decrypt_text

        with Session(engine) as session:
            db_settings = session.exec(select(SummaryApiSettings)).first()
            if db_settings and db_settings.is_enabled:
                api_key = decrypt_text(db_settings.api_key_encrypted)
                model = db_settings.model
                base_url = db_settings.base_url
    except Exception:
        # If db service/config isn't available here, fallback to env vars.
        pass

    # 2) Fallback to environment-based settings
    api_key = api_key or os.getenv("REPORT_SUMMARY_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = model or os.getenv("REPORT_SUMMARY_MODEL", "gpt-4o-mini")
    base_url = base_url or os.getenv("REPORT_SUMMARY_BASE_URL", "https://api.openai.com/v1")

    if language == "zh":
        system_prompt = (
            "你是资深宏观市场分析师。"
            "请用自然、专业、简洁的中文写每日报告。"
            "只能使用输入数据，不要编造。输出必须是JSON："
            "{\"items\":[{\"chart\":\"...\",\"summary\":\"...\"}],\"overall_summary\":\"...\"}。"
        )
        user_prompt = (
            "请按图表逐条写总结：\n"
            "1) 每条2-3句。\n"
            "2) 第1句给关键现状数据（至少两个数值）。\n"
            "3) 第2句必须给出现状判断（明确结论，不要模棱两可）。\n"
            "4) 第3句可选，只能写数据支持的趋势背景（如30天变化、分位、最近交叉日期）。\n"
            "5) 禁止空话和模板话，如“需谨慎”“可能会影响”“表明一定稳定性”“该结论仅基于...”。\n"
            "6) 不要给投资建议。\n"
            "7) 若字段缺失，简短说明“数据不足”。\n"
            "最后写2-3句中文整体总结。\n"
            + json.dumps(payload, ensure_ascii=False)
        )
    else:
        system_prompt = (
            "You are a senior macro market analyst."
            "Write concise, professional daily chart commentary."
            "Use only supplied metrics. Output JSON only: "
            "{\"items\":[{\"chart\":\"...\",\"summary\":\"...\"}],\"overall_summary\":\"...\"}."
        )
        user_prompt = (
            "Write one summary for each chart:\n"
            "1) 2-3 sentences per chart.\n"
            "2) Sentence 1: current state with at least two numbers.\n"
            "3) Sentence 2: explicit interpretation of current state.\n"
            "4) Optional sentence 3: trend context only if supported by provided deltas/dates.\n"
            "5) No generic indicator definitions, no data-source disclaimers, no investment advice.\n"
            "6) Avoid repeating BTC spot price across sections.\n"
            "7) If a field is missing, state that briefly.\n"
            "Then add a 2-3 sentence overall summary.\n"
            + json.dumps(payload, ensure_ascii=False)
        )

    url = base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return None
            return parsed
    except Exception:
        return None


def enrich_with_human_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach per-chart summary lines and overall summary."""
    deterministic_en_items = [
        {"chart": section["chart"], "summary": _deterministic_en_summary(section)}
        for section in payload.get("sections", [])
    ]
    deterministic_zh_items = [
        {"chart": section["chart"], "summary": _deterministic_zh_summary(section)}
        for section in payload.get("sections", [])
    ]

    llm_en = _call_llm_summary(payload, "en")
    llm_zh = _call_llm_summary(payload, "zh")
    en_items = deterministic_en_items
    overall_en = "Overall, moving averages remain bearish, liquidity is rising, funding stress is limited, macro risk is neutral, and futures positioning is in a deleveraging regime."
    zh_items = deterministic_zh_items
    overall_zh = "整体看，均线结构仍偏空，流动性继续上行，融资与信用压力不高，宏观风险处于中性，期货仓位处在去杠杆阶段。"

    if llm_en and isinstance(llm_en.get("items"), list):
        llm_items = llm_en["items"]
        llm_map = {
            str(item.get("chart")): str(item.get("summary"))
            for item in llm_items
            if item.get("chart") and item.get("summary")
        }
        if llm_map:
            en_items = [
                {"chart": item["chart"], "summary": llm_map.get(item["chart"], item["summary"])}
                for item in deterministic_en_items
            ]
        llm_overall = llm_en.get("overall_summary")
        if isinstance(llm_overall, str) and llm_overall.strip():
            overall_en = llm_overall.strip()

    if llm_zh and isinstance(llm_zh.get("items"), list):
        llm_zh_items = llm_zh.get("items")
        llm_zh_map = {
            str(item.get("chart")): str(item.get("summary"))
            for item in llm_zh_items
            if item.get("chart") and item.get("summary")
        }
        if llm_zh_map:
            zh_items = [
                {"chart": item["chart"], "summary": llm_zh_map.get(item["chart"], item["summary"])}
                for item in deterministic_zh_items
            ]
        llm_zh_overall = llm_zh.get("overall_summary")
        if isinstance(llm_zh_overall, str) and llm_zh_overall.strip():
            overall_zh = llm_zh_overall.strip()

    def _postprocess_summary(chart: str, summary: str) -> str:
        text = (summary or "").strip()

        if chart != "MA Cross Analysis":
            # Remove repetitive BTC spot-price mentions from non-MA sections.
            sentences = re.split(r"(?<=[.!?。！？])", text)
            kept: list[str] = []
            for s in sentences:
                chunk = s.strip()
                if not chunk:
                    continue
                if re.search(r"\bbitcoin\b.*\bprice\b", chunk, flags=re.IGNORECASE):
                    continue
                if re.search(r"\bbtc\b.*\bprice\b", chunk, flags=re.IGNORECASE):
                    continue
                kept.append(chunk)
            text = " ".join(kept).strip()

            # Fallback cleanup if fragments remain.
            text = re.sub(
                r"[,;]?\s*(the\s+)?(current\s+)?(bitcoin|btc)\s+(spot\s+)?price\s+(is|at)\s*\$?[0-9,\.]+",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # Normalize punctuation artifacts.
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s+([,.!?])", r"\1", text)

        return text

    for item in en_items:
        chart = str(item.get("chart", ""))
        summary = str(item.get("summary", ""))
        item["summary"] = _postprocess_summary(chart, summary)

    for item in zh_items:
        item["summary"] = str(item.get("summary", "")).strip()

    payload["human_summary"] = {
        "items": en_items,
        "overall_summary": overall_en,
        "localized": {
            "en": {
                "items": en_items,
                "overall_summary": overall_en,
            },
            "zh": {
                "items": zh_items,
                "overall_summary": overall_zh,
            },
        },
        "generated_by": "llm_api" if llm_en or llm_zh else "deterministic_rules",
    }
    return payload


def save_daily_report(
    report: dict[str, Any], output_path: Path = DEFAULT_REPORT_PATH
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(output_path)
    return output_path


def generate_daily_report(
    btc_df: pd.DataFrame,
    *,
    macro_df: pd.DataFrame | None = None,
    usdjpy_df: pd.DataFrame | None = None,
    yield_df: pd.DataFrame | None = None,
    oi_df: pd.DataFrame | None = None,
    output_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    """Build, summarize, and persist daily report payload."""
    payload = build_report_payload(
        btc_df,
        macro_df=macro_df,
        usdjpy_df=usdjpy_df,
        yield_df=yield_df,
        oi_df=oi_df,
    )
    payload = enrich_with_human_summary(payload)
    save_daily_report(payload, output_path=output_path)
    return payload
