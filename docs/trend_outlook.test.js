/**
 * Tests for the "Where the trend points" block in the Charts view.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

// trend_outlook.js is a classic browser script; evaluate it with a
// CommonJS-style module object so it exports its helpers.
function loadOutlook() {
    const source = readFileSync(join(process.cwd(), "docs", "trend_outlook.js"), "utf-8");
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const { buildOutlook, renderOutlook } = loadOutlook();

const META = {
    trend_a: 1.2101138518898882e-17,
    trend_b: 5.790694260310858,
    trend_year_ago: { as_of: "2025-10-01", a: 1.5e-17, b: 5.76 },
    last_updated: "2026-10-02T17:19:46",
};
const NOW = new Date("2026-10-02T12:00:00Z");

function trendAt(a, b, isoDate) {
    const age = Math.floor((Date.parse(isoDate + "T00:00:00Z") - Date.parse("2009-01-03T00:00:00Z")) / 864e5);
    return a * Math.pow(age, b);
}

describe("buildOutlook", () => {
    it("projects today's fit 1, 2 and 4 years ahead", () => {
        const out = buildOutlook(META, NOW);
        expect(out.rows.map(r => r.date)).toEqual(["2027-10-02", "2028-10-02", "2030-10-02"]);
        expect(out.rows.map(r => r.label)).toEqual(["In 1 year", "In 2 years", "In 4 years"]);
        expect(out.rows[0].value).toBeCloseTo(trendAt(META.trend_a, META.trend_b, "2027-10-02"), 6);
        expect(out.today).toBeCloseTo(trendAt(META.trend_a, META.trend_b, "2026-10-02"), 6);
    });

    it("compares each target date with what the fit said a year ago", () => {
        const out = buildOutlook(META, NOW);
        const y = META.trend_year_ago;
        const old = trendAt(y.a, y.b, "2027-10-02");
        expect(out.yearAgoAsOf).toBe("2025-10-01");
        expect(out.rows[0].yearAgoValue).toBeCloseTo(old, 6);
        expect(out.rows[0].changePct).toBeCloseTo((out.rows[0].value / old - 1) * 100, 6);
    });

    it("leaves out the comparison when the old fit is missing", () => {
        const out = buildOutlook({ ...META, trend_year_ago: null }, NOW);
        expect(out.yearAgoAsOf).toBeNull();
        expect(out.rows.every(r => r.yearAgoValue === null && r.changePct === null)).toBe(true);
    });

    it("returns null without usable parameters", () => {
        expect(buildOutlook({}, NOW)).toBeNull();
        expect(buildOutlook(null, NOW)).toBeNull();
    });
});

describe("renderOutlook", () => {
    it("shows each projection with the change since a year ago", () => {
        const html = renderOutlook(buildOutlook(META, NOW));
        expect(html).toContain("In 1 year");
        expect(html).toContain("Oct 2, 2027");
        expect(html).toMatch(/A year ago the fit said \$[\d,]+\. Now \d+% (higher|lower)\./);
        expect(html).toContain("fit as of Oct 1, 2025");
    });

    it("explains the block is unavailable without data", () => {
        expect(renderOutlook(null)).toContain("Trend projections are unavailable right now.");
    });
});
