/**
 * Tests for the Today view: verdict, action rows, meter and market backdrop.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

// today.js is a classic browser script; evaluate it with a CommonJS-style
// module object so it exports its helpers instead of touching the DOM.
function loadToday() {
    const source = readFileSync(join(process.cwd(), "docs", "today.js"), "utf-8");
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const today = loadToday();

function status(overrides = {}) {
    return {
        price: 86550.68,
        dcaCost: 70566.24,
        ratioDCA: 1.227,
        dcaDistance: { inZone: false, percentage: 18.5 },
        trendValue: 142849.86,
        ratioTrend: 0.606,
        trendDistance: { inZone: true, percentage: 39.4 },
        isDoubleUndervalued: false,
        ahr999: 0.743,
        ahr999Zone: { zone: "dca" },
        ahr999Percentile: 33.0,
        ...overrides,
    };
}

const onchain = { score: 77.2, zone: "Undervalued", date: "2026-09-30" };
const TODAY = new Date("2026-10-02T10:00:00Z");

describe("buildVerdict", () => {
    it("keeps regular buying and says the buy zone is not reached", () => {
        const verdict = today.buildVerdict(status(), onchain, TODAY);
        expect(verdict.headline).toBe("Keep buying steadily. Not in the buy zone yet.");
        expect(verdict.actions.map(a => a.title)).toEqual([
            "Regular DCA: keep going",
            "Extra buy: not yet",
            "On-chain signals: undervalued (77/100)",
        ]);
        expect(verdict.actions[1].detail).toBe("Price must fall 18.5% to the 200-day DCA cost");
        expect(verdict.actions[1].tone).toBe("warn");
    });

    it("calls the buy zone when price is below both the DCA cost and the trend", () => {
        const verdict = today.buildVerdict(
            status({
                isDoubleUndervalued: true,
                dcaDistance: { inZone: true, percentage: 5 },
            }),
            onchain,
            TODAY
        );
        expect(verdict.headline).toBe("In the buy zone. A good time to add extra.");
        expect(verdict.actions[1].title).toBe("Extra buy: yes");
        expect(verdict.actions[1].tone).toBe("good");
    });

    it("does not let ahr999 alone change the verdict", () => {
        // ahr999 is a weak signal: bottom or watch zones no longer override the buy-zone verdict
        const bottom = today.buildVerdict(status({ ahr999: 0.4, ahr999Zone: { zone: "bottom" } }), onchain, TODAY);
        const watch = today.buildVerdict(status({ ahr999: 1.5, ahr999Zone: { zone: "watch" } }), onchain, TODAY);
        for (const verdict of [bottom, watch]) {
            expect(verdict.headline).toBe("Keep buying steadily. Not in the buy zone yet.");
            expect(verdict.actions[0].title).toBe("Regular DCA: keep going");
        }
    });

    it("explains why regular buying continues and links to the backtest", () => {
        const first = today.buildVerdict(status(), onchain, TODAY).actions[0];
        expect(first.detail).toBe("Steady buying is the baseline; signals only tilt it");
        expect(first.target).toEqual({ tab: "backtest", title: "Backtest" });
    });

    it("names the larger drop when both conditions are missing", () => {
        const verdict = today.buildVerdict(
            status({ trendDistance: { inZone: false, percentage: 25.2 } }),
            onchain,
            TODAY
        );
        expect(verdict.actions[1].detail).toBe("Price must fall 25.2% to enter the buy zone");
    });

    it("names the trend when only the trend condition is missing", () => {
        const verdict = today.buildVerdict(
            status({ dcaDistance: { inZone: true, percentage: 3 }, trendDistance: { inZone: false, percentage: 7.25 } }),
            onchain,
            TODAY
        );
        expect(verdict.actions[1].detail).toBe("Price must fall 7.3% to the long-term trend");
    });

    it("says when on-chain signals are not cheap yet", () => {
        const verdict = today.buildVerdict(status(), { score: 45, zone: "Watch", date: "2026-09-30" }, TODAY);
        expect(verdict.actions[2].title).toBe("On-chain signals: not cheap yet (45/100)");
        expect(verdict.actions[2].tone).toBe("warn");
    });

    it("flags an old on-chain reading instead of presenting it as current", () => {
        const verdict = today.buildVerdict(status(), { score: 77.2, zone: "Undervalued", date: "2026-07-02" }, TODAY);
        expect(verdict.actions[2].tone).toBe("stale");
        expect(verdict.actions[2].detail).toBe("Last reading Jul 2, 92 days old");
    });

    it("links every action to the chart or page behind it", () => {
        const targets = today.buildVerdict(status(), onchain, TODAY).actions.map(a => a.target);
        expect(targets).toEqual([
            { tab: "backtest", title: "Backtest" },
            { src: "charts/price_comparison.html", title: "Price Comparison" },
            // The date busts a cached copy of the self-contained detail page
            { src: "charts/bottom_signals.html?v=2026-09-30", title: "On-chain bottom signals" },
        ]);
    });

    it("omits the on-chain row when there is no on-chain data", () => {
        expect(today.buildVerdict(status(), null, TODAY).actions).toHaveLength(2);
    });

    it("explains and dates a current on-chain reading", () => {
        expect(today.buildVerdict(status(), onchain, TODAY).actions[2].detail).toBe("Sentiment gauge, not a buy signal · Sep 30");
    });
});

describe("cheapness and meter", () => {
    it("turns the ahr999 percentile into share of cheaper-than days", () => {
        expect(today.cheaperThanShare(33.0)).toBe(67);
        expect(today.cheaperThanShare(0)).toBe(100);
        expect(today.cheaperThanShare(100)).toBe(0);
    });

    it("points the needle left for expensive and right for cheap", () => {
        const left = today.needlePoint(0);
        const right = today.needlePoint(100);
        const middle = today.needlePoint(50);
        expect(left.x).toBeCloseTo(70, 5);
        expect(left.y).toBeCloseTo(200, 5);
        expect(right.x).toBeCloseTo(330, 5);
        expect(middle.x).toBeCloseTo(200, 5);
        expect(middle.y).toBeCloseTo(70, 5);
    });

    it("clamps the needle to the dial", () => {
        expect(today.needlePoint(140)).toEqual(today.needlePoint(100));
        expect(today.needlePoint(-5)).toEqual(today.needlePoint(0));
    });
});

describe("buildBackdrop", () => {
    const report = {
        sections: [
            { chart: "MA Cross Analysis", metrics: { regime: "bullish", last_golden_cross: "2026-09-08", last_death_cross: "2025-11-16" } },
            { chart: "Supplemental Bottoming Signals", metrics: { fear_greed_value: 74, fear_greed_classification: "Greed" } },
            { chart: "Net Liquidity", metrics: { net_liquidity_90d_delta: -60.5 } },
            { chart: "Funding & Credit Stress", metrics: { stress_flags: 0 } },
            { chart: "On-Chain Bottom Signals", metrics: { composite_score: 77.2, zone: "Undervalued", data_date: "2026-07-02" } },
        ],
    };

    it("summarises the four backdrop signals", () => {
        expect(today.buildBackdrop(report)).toEqual([
            { label: "Moving averages", value: "Bullish", detail: "Golden cross Sep 8", target: { src: "charts/ma_cross_analysis.html", title: "MA Cross Analysis" } },
            { label: "Fear & Greed", value: "74 · Greed", detail: "Crowd sentiment index", target: null },
            { label: "Net liquidity", value: "Falling", detail: "−61 bn in 90 days", target: { src: "charts/net_liquidity.html", title: "Net Liquidity" } },
            { label: "Funding & credit", value: "Calm", detail: "0 of 3 stress signs", target: { src: "charts/funding_credit_stress.html", title: "Funding & Credit Stress" } },
        ]);
    });

    it("skips signals the report does not have", () => {
        expect(today.buildBackdrop({ sections: [report.sections[3]] })).toEqual([
            { label: "Funding & credit", value: "Calm", detail: "0 of 3 stress signs", target: { src: "charts/funding_credit_stress.html", title: "Funding & Credit Stress" } },
        ]);
        expect(today.buildBackdrop(null)).toEqual([]);
    });

    it("describes rising liquidity and stress", () => {
        const cards = today.buildBackdrop({
            sections: [
                { chart: "MA Cross Analysis", metrics: { regime: "bearish", last_golden_cross: "2026-01-02", last_death_cross: "2026-05-04" } },
                { chart: "Net Liquidity", metrics: { net_liquidity_90d_delta: 120.4 } },
                { chart: "Funding & Credit Stress", metrics: { stress_flags: 2 } },
            ],
        });
        expect(cards).toEqual([
            { label: "Moving averages", value: "Bearish", detail: "Death cross May 4", target: { src: "charts/ma_cross_analysis.html", title: "MA Cross Analysis" } },
            { label: "Net liquidity", value: "Rising", detail: "+120 bn in 90 days", target: { src: "charts/net_liquidity.html", title: "Net Liquidity" } },
            { label: "Funding & credit", value: "Stressed", detail: "2 of 3 stress signs", target: { src: "charts/funding_credit_stress.html", title: "Funding & Credit Stress" } },
        ]);
    });

    it("reads the on-chain reading from the report", () => {
        expect(today.onchainFromReport(report)).toEqual({ score: 77.2, zone: "Undervalued", date: "2026-07-02" });
        expect(today.onchainFromReport({ sections: [] })).toBeNull();
    });
});

describe("buildCrossChecks", () => {
    const input = { price: 83553.85, ma200w: 65896, mvrv: { value: 1.5897, date: "2026-09-29" } };

    it("shows both cross-checks with their readings", () => {
        const checks = today.buildCrossChecks(input, TODAY);
        expect(checks.cards.map(c => [c.label, c.value, c.chip.text])).toEqual([
            ["Price vs 200-week average", "1.27×", "Above"],
            ["MVRV", "1.59", "Above 1"],
        ]);
        expect(checks.cards[0].detail).toBe("200-week average $65,896");
        expect(checks.cards[1].detail).toBe("Market value ÷ what holders paid · Sep 29");
        expect(checks.summary).toBe("Independent of ahr999. 0 of 2 at a cycle-low reading.");
    });

    it("marks cycle-low readings", () => {
        const checks = today.buildCrossChecks({ price: 60000, ma200w: 65000, mvrv: { value: 0.9, date: "2026-09-30" } }, TODAY);
        expect(checks.cards.map(c => c.chip)).toEqual([
            { text: "Below: cycle-low reading", tone: "good" },
            { text: "Below 1: cycle-low reading", tone: "good" },
        ]);
        expect(checks.summary).toBe("Independent of ahr999. 2 of 2 at a cycle-low reading.");
    });

    it("flags an old MVRV reading", () => {
        const checks = today.buildCrossChecks({ ...input, mvrv: { value: 1.17, date: "2026-07-02" } }, TODAY);
        expect(checks.cards[1].tone).toBe("stale");
        expect(checks.cards[1].detail).toBe("Last reading Jul 2, 92 days old");
    });

    it("links each cross-check to its evidence", () => {
        expect(today.buildCrossChecks(input, TODAY).cards.map(c => c.target.src)).toEqual([
            "charts/ma_cross_analysis.html",
            "charts/bottom_signals.html?v=2026-09-29",
        ]);
    });

    it("leaves out a cross-check without data", () => {
        const checks = today.buildCrossChecks({ price: 83553, ma200w: null, mvrv: null }, TODAY);
        expect(checks.cards).toEqual([]);
        expect(checks.summary).toBe("");
    });
});
