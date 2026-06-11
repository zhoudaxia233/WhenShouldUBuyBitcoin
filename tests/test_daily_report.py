from pathlib import Path

import numpy as np
import pandas as pd
from unittest.mock import patch

from whenshouldubuybitcoin.daily_report import (
    build_report_payload,
    enrich_with_human_summary,
    generate_daily_report,
)


def _sample_btc_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    prices = pd.Series(50000 + (pd.Series(range(260)) * 20))
    ma50 = prices.rolling(50).mean()
    ma200 = prices.rolling(200).mean()
    spread = ma50 - ma200

    df = pd.DataFrame(
        {
            "date": dates,
            "close_price": prices,
            "ma_50": ma50,
            "ma_200": ma200,
            "ma_spread": spread,
            "golden_cross": False,
            "death_cross": False,
        }
    )
    # Force one signal so report includes last cross fields.
    df.loc[df.index[220], "golden_cross"] = True
    return df


def _sample_macro_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "net_liquidity_bil": 6000 + pd.Series(range(260)) * 2,
            "walcl_bil": 7000 + pd.Series(range(260)) * 1,
            "tga_bil": 800 + pd.Series(range(260)) * 0.2,
            "rrp_bil": 200 - pd.Series(range(260)) * 0.1,
            "sofr": 5.0,
            "move": 110.0,
            "hy_oas": 4.2,
        }
    )


def _sample_usdjpy_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    return pd.DataFrame({"date": dates, "close_price": 150 + pd.Series(range(260)) * 0.01})


def _sample_yield_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "us_2y": 4.3,
            "jp_2y": 0.8,
            "spread": 3.5,
        }
    )


def _sample_oi_df() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=260, freq="D")
    return pd.DataFrame({"timestamp": dates, "oi_usd": 15_000_000_000 + pd.Series(range(260)) * 10_000_000})


def test_build_report_payload_includes_non_excluded_sections():
    payload = build_report_payload(
        _sample_btc_df(),
        macro_df=_sample_macro_df(),
        usdjpy_df=_sample_usdjpy_df(),
        yield_df=_sample_yield_df(),
        oi_df=_sample_oi_df(),
    )

    charts = [section["chart"] for section in payload["sections"]]
    assert "Valuation Ratios" not in charts
    assert "Price Comparison" not in charts
    assert "MA Cross Analysis" in charts
    assert "Macro Risk Score" in charts
    assert "Net Liquidity" in charts
    assert "Funding & Credit Stress" in charts
    assert "USD/JPY Risk Map" in charts
    assert "Futures OI & Price" in charts


def test_enrich_with_human_summary_produces_items_and_overall(monkeypatch):
    payload = build_report_payload(_sample_btc_df(), macro_df=_sample_macro_df())

    # Force deterministic path (no API call).
    monkeypatch.setenv("REPORT_SUMMARY_DISABLE_LLM", "1")
    monkeypatch.delenv("REPORT_SUMMARY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    enriched = enrich_with_human_summary(payload)
    summary = enriched["human_summary"]

    assert summary["generated_by"] == "deterministic_rules"
    assert len(summary["items"]) >= 2
    assert isinstance(summary["overall_summary"], str)
    assert len(summary["overall_summary"]) > 0
    assert "localized" in summary
    assert "en" in summary["localized"]
    assert "zh" in summary["localized"]
    assert len(summary["localized"]["en"]["items"]) == len(summary["items"])
    assert len(summary["localized"]["zh"]["items"]) == len(summary["items"])


def test_generate_daily_report_writes_json(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "daily_report.json"
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("REPORT_SUMMARY_DISABLE_LLM", "1")
    monkeypatch.delenv("REPORT_SUMMARY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = generate_daily_report(
        _sample_btc_df(),
        macro_df=_sample_macro_df(),
        usdjpy_df=_sample_usdjpy_df(),
        yield_df=_sample_yield_df(),
        oi_df=_sample_oi_df(),
        output_path=output_path,
    )

    assert output_path.exists()
    assert report["human_summary"]["items"]


def test_generate_daily_report_skips_llm_when_source_unchanged(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "daily_report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPORT_SUMMARY_DISABLE_LLM", raising=False)
    monkeypatch.delenv("REPORT_SUMMARY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    calls = {"n": 0}

    def fake_llm(_payload, language):
        calls["n"] += 1
        if language == "zh":
            return {
                "items": [{"chart": "MA Cross Analysis", "summary": "中文摘要"}],
                "overall_summary": "中文总览",
            }
        return {
            "items": [{"chart": "MA Cross Analysis", "summary": "English summary"}],
            "overall_summary": "English overview",
        }

    with patch("whenshouldubuybitcoin.daily_report._call_llm_summary", side_effect=fake_llm):
        first = generate_daily_report(
            _sample_btc_df(),
            macro_df=_sample_macro_df(),
            output_path=output_path,
        )
        first_calls = calls["n"]
        second = generate_daily_report(
            _sample_btc_df(),
            macro_df=_sample_macro_df(),
            output_path=output_path,
        )

    assert first_calls == 2  # en + zh
    assert calls["n"] == 2  # unchanged source: no extra LLM calls
    assert first["summary_generation"]["api_call_skipped"] is False
    assert second["summary_generation"]["api_call_skipped"] is True
    assert second["summary_generation"]["skip_reason"] == "source_unchanged"
    assert second["summary_generation"]["reused_from_existing"] is True
    assert second["human_summary"] == first["human_summary"]


def test_generate_daily_report_calls_llm_when_source_changes(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "daily_report.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPORT_SUMMARY_DISABLE_LLM", raising=False)
    monkeypatch.delenv("REPORT_SUMMARY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    calls = {"n": 0}

    def fake_llm(_payload, language):
        calls["n"] += 1
        marker = f"v{calls['n']}"
        return {
            "items": [{"chart": "MA Cross Analysis", "summary": f"{language}-{marker}"}],
            "overall_summary": f"{language}-overall-{marker}",
        }

    btc_df_1 = _sample_btc_df()
    btc_df_2 = _sample_btc_df().copy()
    btc_df_2.loc[btc_df_2.index[-1], "close_price"] += 999  # force signature change

    with patch("whenshouldubuybitcoin.daily_report._call_llm_summary", side_effect=fake_llm):
        first = generate_daily_report(
            btc_df_1,
            macro_df=_sample_macro_df(),
            output_path=output_path,
        )
        second = generate_daily_report(
            btc_df_2,
            macro_df=_sample_macro_df(),
            output_path=output_path,
        )

    assert calls["n"] == 4  # en + zh for each run
    assert first["summary_generation"]["api_call_skipped"] is False
    assert second["summary_generation"]["api_call_skipped"] is False
    assert first["summary_source_signature"] != second["summary_source_signature"]


def _bottom_signals_snapshot():
    return {
        "date": "2026-06-08",
        "composite": 55.0,
        "zone": "Watch",
        "advice": "Not cheap yet — keep watching.",
        "signals": [
            {"key": "s1", "label": "Holder cost", "score": 4.2, "status": "Rich side"},
            {"key": "s2", "label": "MVRV", "score": 14.2, "status": "Leaning cheap"},
            {"key": "s3", "label": "Supply in loss", "score": 7.1, "status": "Neutral"},
            {"key": "s4", "label": "Capital flow", "score": 10.0, "status": "Leaning cheap"},
            {"key": "s5", "label": "Fear & Greed", "score": 20.0, "status": "Bottom zone"},
        ],
        "mvrv": 1.18,
        "supply_loss_pct": 20.6,
        "realized_cap_change_30d_usd": -2.09e10,
        "fear_greed": 10.0,
    }


def _minimal_btc_df():
    # build_report_payload needs at least date, close_price, and the MA columns.
    n = 250
    prices = pd.Series(np.linspace(60_000.0, 63_000.0, n))
    ma50 = prices.rolling(50).mean()
    ma200 = prices.rolling(200).mean()
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-10-01", periods=n),
            "close_price": prices,
            "ma_50": ma50,
            "ma_200": ma200,
            "ma_spread": ma50 - ma200,
            "golden_cross": False,
            "death_cross": False,
        }
    )


def test_report_includes_bottom_signals_section():
    payload = build_report_payload(
        _minimal_btc_df(), bottom_signals_snapshot=_bottom_signals_snapshot()
    )
    sections = {s["chart"]: s for s in payload["sections"]}
    assert "On-Chain Bottom Signals" in sections
    metrics = sections["On-Chain Bottom Signals"]["metrics"]
    assert metrics["composite_score"] == 55.0
    assert metrics["zone"] == "Watch"
    assert metrics["s5"] == 20.0
    # the section carries an honest caveat (look-ahead / warmer proxy / not advice)
    assert "caveat" in metrics
    caveat = metrics["caveat"].lower()
    assert "look-ahead" in caveat and "not investment advice" in caveat


def test_bottom_signals_deterministic_summaries():
    from whenshouldubuybitcoin.daily_report import (
        _deterministic_en_summary,
        _deterministic_zh_summary,
    )

    snapshot = _bottom_signals_snapshot()
    section = {
        "chart": "On-Chain Bottom Signals",
        "metrics": {
            "composite_score": snapshot["composite"],
            "zone": snapshot["zone"],
            "s1": 4.2, "s2": 14.2, "s3": 7.1, "s4": 10.0, "s5": 20.0,
            "mvrv": 1.18,
            "supply_loss_pct": 20.6,
        },
    }
    en = _deterministic_en_summary(section)
    assert "55" in en and "Watch" in en
    zh = _deterministic_zh_summary(section)
    assert "55" in zh and "观望" in zh


def test_bottom_signals_section_summary_bakes_in_advice_and_caveat():
    # the advice + caveat must land in the rendered summary text (not just in
    # metrics fields the frontend never shows)
    from whenshouldubuybitcoin.daily_report import (
        _deterministic_en_summary,
        _deterministic_zh_summary,
    )

    section = {
        "chart": "On-Chain Bottom Signals",
        "metrics": {
            "composite_score": 81.0,
            "zone": "Extremely Undervalued",
            "s1": 8, "s2": 17, "s3": 18, "s4": 19, "s5": 20,
            "mvrv": 1.16,
            "supply_loss_pct": 51.1,
            "advice": (
                "Rare reading on a two-cycle sample — if accumulating, scale in "
                "gradually; not a signal to go all-in."
            ),
            "caveat": (
                "Composite uses full-sample statistics (look-ahead) over a "
                "two-cycle backtest. Treat as one sentiment input, not "
                "investment advice."
            ),
        },
    }
    en = _deterministic_en_summary(section)
    assert "not a signal to go all-in" in en
    assert "Caveat:" in en and "look-ahead" in en.lower()
    zh = _deterministic_zh_summary(section)
    assert "情绪参考" in zh and "并非买入信号" in zh


def test_overall_summary_mentions_bottom_signal_with_caveat(monkeypatch):
    monkeypatch.setenv("REPORT_SUMMARY_DISABLE_LLM", "1")
    monkeypatch.delenv("REPORT_SUMMARY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = build_report_payload(
        _minimal_btc_df(), bottom_signals_snapshot=_bottom_signals_snapshot()
    )
    enriched = enrich_with_human_summary(payload)
    overall_en = enriched["human_summary"]["localized"]["en"]["overall_summary"].lower()
    assert "on-chain bottom composite" in overall_en
    assert "sentiment" in overall_en and "not a buy trigger" in overall_en
    overall_zh = enriched["human_summary"]["localized"]["zh"]["overall_summary"]
    assert "链上底部" in overall_zh and "并非买入信号" in overall_zh
