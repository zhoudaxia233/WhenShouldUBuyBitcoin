// Tests for the reserve chart helpers: the series built from /api/stats/pnl,
// the visible range, the y-axis domain and the readout above the chart.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadReserveChart() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "reserve_chart.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const { buildSeries, visibleDays, yDomain, readoutAt, formatBtc } = loadReserveChart();

const DAY = 864e5;
const PNL = {
    dates: ["2026-01-01T01:10:00", "2026-01-02T01:20:00", "2026-01-02T03:00:00", "2026-01-09T01:00:00"],
    prices: [100, 80, 82, 120],
    purchase_btc: [0.1, 0.125, 0.1, 0.05],
    purchase_usd: [10, 10, 8.2, 6],
    btc_balance: [0.1, 0.225, 0.325, 0.375],
    market_dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-08", "2026-01-09", "2026-01-10"],
    market_prices: [100, 80, 90, 110, 120, 125],
    avg_price_timeline: [100, 88.89, 88.89, 88.89, 91.2, 91.2],
};

describe("buildSeries", () => {
    it("gives every market day the BTC bought up to the end of that day", () => {
        const { days } = buildSeries(PNL);
        expect(days.map((d) => d.btc)).toEqual([0.1, 0.325, 0.325, 0.325, 0.375, 0.375]);
        expect(days.map((d) => d.price)).toEqual(PNL.market_prices);
        expect(days.map((d) => d.avg)).toEqual(PNL.avg_price_timeline);
    });

    it("sums buys into weeks starting on the first buy", () => {
        const { weeks } = buildSeries(PNL);
        expect(weeks).toHaveLength(2);
        expect(weeks[0].btc).toBeCloseTo(0.325, 10);
        expect(weeks[0].count).toBe(3);
        expect(weeks[1].btc).toBeCloseTo(0.05, 10);
        expect(weeks[1].start).toBe(Date.parse("2026-01-08T00:00:00Z"));
    });

    it("returns nothing to draw without purchases", () => {
        expect(buildSeries({ dates: [], market_dates: [] })).toBeNull();
        expect(buildSeries({})).toBeNull();
    });
});

describe("visibleDays", () => {
    const series = buildSeries(PNL);

    it("keeps the days inside the selected range", () => {
        expect(visibleDays(series, "all")).toHaveLength(6);
        const last = series.days[series.days.length - 1].t;
        const recent = visibleDays(series, "3m", last + 1 * DAY);
        expect(recent[0].t).toBe(series.days[0].t);
    });

    it("drops days older than the range", () => {
        const now = Date.parse("2026-05-01T00:00:00Z");
        expect(visibleDays(series, "3m", now)).toEqual([]);
    });
});

describe("yDomain", () => {
    it("fits price and average cost with 8% headroom, not from zero", () => {
        const days = [{ price: 100, avg: 90 }, { price: 120, avg: 95 }];
        const [lo, hi] = yDomain(days);
        expect(lo).toBeCloseTo(90 - 30 * 0.08, 10);
        expect(hi).toBeCloseTo(120 + 30 * 0.08, 10);
    });

    it("still spans a range when the line is flat", () => {
        const [lo, hi] = yDomain([{ price: 100, avg: 100 }]);
        expect(hi).toBeGreaterThan(lo);
    });
});

describe("readoutAt", () => {
    const series = buildSeries(PNL);

    it("describes the last day as what you hold now", () => {
        const r = readoutAt(series, null, { currentBtc: 0.4, currentPrice: 130, currentAvg: 91.2 });
        expect(r.live).toBe(true);
        expect(r.btc).toBe(0.4);
        expect(r.valueUsd).toBeCloseTo(52, 10);
        expect(r.pnlPct).toBeCloseTo((130 / 91.2 - 1) * 100, 10);
    });

    it("falls back to the purchase history without a wallet summary", () => {
        const r = readoutAt(series, null, {});
        expect(r.btc).toBeCloseTo(0.375, 10);
        expect(r.price).toBe(125);
    });

    it("describes a scrubbed day with BTC bought by then and that week's buys", () => {
        const day = series.days[1];
        const r = readoutAt(series, day, {});
        expect(r.live).toBe(false);
        expect(r.btc).toBeCloseTo(0.325, 10);
        expect(r.price).toBe(80);
        expect(r.week.count).toBe(3);
    });
});

describe("formatBtc", () => {
    it("shows 8 decimals for amounts under 1 BTC and 4 above", () => {
        expect(formatBtc(0.10895)).toBe("0.10895000");
        expect(formatBtc(1.234567)).toBe("1.2346");
    });
});

describe("targetEta", () => {
    const { targetEta } = loadReserveChart();
    const day = (iso, btc) => ({ t: Date.parse(iso + "T00:00:00Z"), btc, price: 1, avg: 1 });
    const series = {
        days: [day("2026-08-01", 0.1), day("2026-08-31", 0.13), day("2026-09-30", 0.16)],
        weeks: [],
    };

    it("projects the date the target is reached at the last 30 days' pace", () => {
        const eta = targetEta(series, 0.16, 0.25);
        // 0.03 BTC in 30 days = 0.001 BTC a day; 0.09 BTC to go = 90 days
        expect(eta.reached).toBe(false);
        expect(eta.btcPerDay).toBeCloseTo(0.001, 10);
        expect(eta.t).toBe(Date.parse("2026-09-30T00:00:00Z") + 90 * DAY);
    });

    it("says the target is reached once holdings cover it", () => {
        expect(targetEta(series, 0.3, 0.25)).toEqual({ reached: true, t: null, btcPerDay: null });
    });

    it("gives no date without recent buys or a target", () => {
        const flat = { days: [day("2026-08-01", 0.1), day("2026-09-30", 0.1)], weeks: [] };
        expect(targetEta(flat, 0.1, 0.25).t).toBeNull();
        expect(targetEta(series, 0.16, 0)).toBeNull();
        expect(targetEta(null, 0.16, 0.25)).toBeNull();
    });
});
