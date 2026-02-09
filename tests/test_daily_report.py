from pathlib import Path

import pandas as pd

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
