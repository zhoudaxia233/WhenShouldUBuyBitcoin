"""Regression cases for fact-grounded bilingual daily commentary."""

import pytest

from whenshouldubuybitcoin.daily_report import enrich_with_human_summary


@pytest.fixture(autouse=True)
def disable_summary_api(monkeypatch):
    monkeypatch.setenv("REPORT_SUMMARY_DISABLE_LLM", "1")


def summaries(chart, metrics):
    report = enrich_with_human_summary(
        {"sections": [{"chart": chart, "metrics": metrics}]}
    )
    return report["human_summary"]["localized"]


@pytest.mark.parametrize(
    "chart,metrics,en_state,zh_state,wrong_en,wrong_zh",
    [
        (
            "MA Cross Analysis",
            {"ma_spread": 2704.37, "ma_50": 73208.69, "ma_200": 70504.32},
            "bullish",
            "多头",
            "bearish",
            "空头",
        ),
        (
            "MA Cross Analysis",
            {"ma_spread": -100, "ma_50": 69000, "ma_200": 69100},
            "bearish",
            "空头",
            "bullish",
            "多头",
        ),
        (
            "Net Liquidity",
            {
                "net_liquidity_bil": 6000,
                "net_liquidity_90d_delta": -500,
                "walcl_bil": 7000,
                "tga_bil": 800,
                "rrp_bil": 200,
            },
            "falling",
            "下行",
            "rising",
            "边际改善",
        ),
        (
            "Funding & Credit Stress",
            {"sofr": 6, "move": 150, "hy_oas": 7, "stress_flags": 3},
            "tight",
            "偏紧",
            "loose",
            "可控区间",
        ),
        (
            "Macro Risk Score",
            {"score": 95, "regime": "high", "high_risk_hit_rate": 60},
            "high risk",
            "高风险",
            "neutral",
            "不在极端区间",
        ),
        (
            "Macro Risk Score",
            {"score": 20, "regime": "low", "high_risk_hit_rate": None},
            "low risk",
            "低风险",
            "neutral",
            "不在极端区间",
        ),
        (
            "Futures OI & Price",
            {
                "oi_usd": 1700000000,
                "oi_30d_change_pct": 16.65,
                "oi_percentile": 100,
                "quadrant": "Risky Up (leveraged)",
            },
            "Risky Up (leveraged)",
            "杠杆推动上涨",
            "deleveraging",
            "去杠杆",
        ),
        (
            "Futures OI & Price",
            {
                "oi_usd": 1700000000,
                "oi_30d_change_pct": -10,
                "oi_percentile": 10,
                "quadrant": "Flush-Out (deleveraging)",
            },
            "Flush-Out (deleveraging)",
            "去杠杆",
            "Risky Up",
            "杠杆推动上涨",
        ),
    ],
)
def test_section_and_overall_follow_the_same_market_state(
    chart, metrics, en_state, zh_state, wrong_en, wrong_zh
):
    localized = summaries(chart, metrics)
    for lang, expected, rejected in [
        ("en", en_state, wrong_en),
        ("zh", zh_state, wrong_zh),
    ]:
        section = localized[lang]["items"][0]["summary"]
        overall = localized[lang]["overall_summary"]
        assert expected in section
        assert expected in overall
        assert rejected not in section
        assert rejected not in overall


def test_chinese_liquidity_values_use_the_same_dollar_scale_as_english():
    localized = summaries(
        "Net Liquidity",
        {
            "net_liquidity_bil": 6000,
            "net_liquidity_90d_delta": -500,
            "walcl_bil": 7000,
            "tga_bil": 800,
            "rrp_bil": 200,
        },
    )
    en = localized["en"]["items"][0]["summary"]
    zh = localized["zh"]["items"][0]["summary"]
    assert "6000 bn USD" in en
    for amount in (60000, -5000, 70000, 8000, 2000):
        assert f"{amount}亿美元" in zh


@pytest.mark.parametrize(
    "chart",
    [
        "MA Cross Analysis",
        "Net Liquidity",
        "Funding & Credit Stress",
        "Macro Risk Score",
        "USD/JPY Risk Map",
        "Futures OI & Price",
    ],
)
def test_missing_metrics_do_not_create_a_market_direction(chart):
    localized = summaries(chart, {})
    for lang in ("en", "zh"):
        text = (
            localized[lang]["items"][0]["summary"] + localized[lang]["overall_summary"]
        )
        assert "unavailable" in text if lang == "en" else "不足" in text
        assert not any(
            word in text
            for word in (
                "bullish",
                "bearish",
                "rising",
                "falling",
                "多头",
                "空头",
                "上行",
                "下行",
            )
        )


def test_missing_liquidity_components_do_not_crash_or_hide_known_direction():
    localized = summaries(
        "Net Liquidity", {"net_liquidity_bil": 6000, "net_liquidity_90d_delta": -500}
    )
    assert "falling" in localized["en"]["items"][0]["summary"]
    assert "下行" in localized["zh"]["items"][0]["summary"]


def test_missing_fx_changes_do_not_claim_a_rising_carry_trade_risk():
    localized = summaries(
        "USD/JPY Risk Map", {"usdjpy": 140, "spread": 1, "risk_level": "LOW RISK"}
    )
    zh = localized["zh"]["items"][0]["summary"]
    assert "LOW RISK" in zh
    assert "数据不足" in zh
    assert all(
        word not in zh
        for word in ("同向走高", "风险在抬升", "回落", "收窄", "中等风险偏上")
    )


@pytest.mark.parametrize(
    "chart,metrics,en_state,zh_state",
    [
        ("MA Cross Analysis", {"ma_spread": 0}, "neutral", "持平"),
        (
            "Net Liquidity",
            {"net_liquidity_bil": 6000, "net_liquidity_90d_delta": 0},
            "unchanged",
            "持平",
        ),
    ],
)
def test_unchanged_values_are_not_described_as_a_direction(
    chart, metrics, en_state, zh_state
):
    localized = summaries(chart, metrics)
    assert en_state in localized["en"]["overall_summary"]
    assert zh_state in localized["zh"]["overall_summary"]


def test_empty_report_does_not_invent_missing_sections():
    localized = enrich_with_human_summary({"sections": []})["human_summary"][
        "localized"
    ]
    assert "insufficient" in localized["en"]["overall_summary"]
    assert "不足" in localized["zh"]["overall_summary"]


def test_onchain_date_remains_independent_in_the_overall_summary():
    payload = {
        "report_date": "2026-09-20",
        "sections": [
            {"chart": "MA Cross Analysis", "metrics": {"ma_spread": 100}},
            {
                "chart": "On-Chain Bottom Signals",
                "metrics": {
                    "data_date": "2026-09-15",
                    "composite_score": 36,
                    "zone": "Watch",
                },
            },
        ],
    }
    report = enrich_with_human_summary(payload)
    assert report["report_date"] == "2026-09-20"
    for lang in ("en", "zh"):
        summary = report["human_summary"]["localized"][lang]
        assert "2026-09-15" in summary["items"][1]["summary"]
        assert "2026-09-15" in summary["overall_summary"]
