/**
 * The backtest may only use what was known on each simulated day:
 * ahr999 percentile tiers rank against earlier values only, and historical
 * days are never back-filled with a trend fitted on later prices.
 */

import { describe, it, expect } from "vitest";
import {
    AHR999PercentileStrategy,
    AHR999FixedRangeStrategy,
    KnownHistoryQuantiles,
    getPercentileValue,
    AHR999_DEFAULT_MULTIPLIERS,
} from "./backtest.js";

const DAY = 864e5;
const START = Date.UTC(2020, 0, 1);

function history(values) {
    return values.map((value, i) => ({ time: START + i * DAY, value }));
}

describe("KnownHistoryQuantiles", () => {
    const values = [5, 3, 8, 1, 9, 2, 7, 4, 6, 10];

    it("only includes values up to the given day", () => {
        const q = new KnownHistoryQuantiles(history(values), 1);
        q.advanceTo(new Date(START + 3 * DAY));
        expect(q.count).toBe(4);
        expect(q.quantile(50)).toBe(getPercentileValue([5, 3, 8, 1], 50));
    });

    it("matches the site's percentile formula on the known prefix", () => {
        const q = new KnownHistoryQuantiles(history(values), 1);
        q.advanceTo(new Date(START + 9 * DAY));
        for (const p of [10, 25, 50, 75, 90]) {
            expect(q.quantile(p)).toBe(getPercentileValue(values, p));
        }
    });

    it("is not ready until enough history is known", () => {
        const q = new KnownHistoryQuantiles(history(values), 5);
        q.advanceTo(new Date(START + 3 * DAY));
        expect(q.ready()).toBe(false);
        q.advanceTo(new Date(START + 4 * DAY));
        expect(q.ready()).toBe(true);
    });

    it("ignores missing values", () => {
        const q = new KnownHistoryQuantiles(history([1, null, NaN, 2]), 1);
        q.advanceTo(new Date(START + 3 * DAY));
        expect(q.count).toBe(2);
    });
});

function fakeLoader(ahrByDay, lastHistoricalDay) {
    return {
        getAHR999History: () => history(ahrByDay),
        getLastHistoricalDate: () => new Date(START + lastHistoricalDay * DAY),
        calculateAHR999: () => 0.1, // what today's trend would say: must not be used for history
    };
}

describe("AHR999PercentileStrategy without look-ahead", () => {
    function strategy(loader, minHistory) {
        const s = new AHR999PercentileStrategy(30.44 * 10, { minKnownHistory: minHistory });
        s.dataLoader = loader;
        s.initialize();
        return s;
    }

    it("ranks today's ahr999 only against values known so far", () => {
        // Rising then falling: a later crash must not change early decisions
        const early = Array.from({ length: 20 }, (_, i) => 1 + i * 0.1);
        const later = Array.from({ length: 20 }, () => 0.1);
        const withFuture = strategy(fakeLoader([...early, ...later], 39), 10);
        const withoutFuture = strategy(fakeLoader(early, 19), 10);
        for (let day = 0; day < 20; day += 1) {
            const date = new Date(START + day * DAY);
            const dayData = { ahr999: early[day] };
            expect(withFuture.shouldInvest(date, 100, dayData)).toBe(withoutFuture.shouldInvest(date, 100, dayData));
        }
    });

    it("does not buy until enough history is known to rank today's value", () => {
        const s = strategy(fakeLoader([0.3, 0.4, 0.5], 2), 10);
        expect(s.shouldInvest(new Date(START + 2 * DAY), 100, { ahr999: 0.5 })).toBe(0);
    });

    it("uses the default tiers once history is known", () => {
        const values = Array.from({ length: 100 }, (_, i) => (i + 1) / 100);
        const s = strategy(fakeLoader(values, 99), 10);
        const date = new Date(START + 99 * DAY);
        expect(s.shouldInvest(date, 100, { ahr999: 0.05 })).toBeCloseTo(10 * AHR999_DEFAULT_MULTIPLIERS.p10);
        expect(s.shouldInvest(date, 100, { ahr999: 0.95 })).toBeCloseTo(10 * AHR999_DEFAULT_MULTIPLIERS.p100);
    });

    it("never back-fills a historical day with today's trend", () => {
        const s = strategy(fakeLoader([0.5, 0.6], 400), 1);
        expect(s.getCurrentAHR999(new Date(START + 300 * DAY))).toBeNull();
        // Days after the data ends are projections; today's trend is all that is known
        expect(s.getCurrentAHR999(new Date(START + 401 * DAY))).toBe(0.1);
    });

    it("does not buy on a historical day without an ahr999 value", () => {
        const s = strategy(fakeLoader([0.5, 0.6], 400), 1);
        expect(s.shouldInvest(new Date(START + 300 * DAY), 100, { ahr999: null })).toBe(0);
    });
});

describe("AHR999FixedRangeStrategy without look-ahead", () => {
    it("does not estimate a missing historical ahr999 with today's trend", () => {
        const s = new AHR999FixedRangeStrategy(30.44 * 10, {});
        s.dataLoader = fakeLoader([0.5], 400);
        s.initialize();
        // Today's trend would give 0.1 (the cheapest tier); the day has no value, so no buy
        expect(s.shouldInvest(new Date(START + 300 * DAY), 100, {})).toBe(0);
    });
});
