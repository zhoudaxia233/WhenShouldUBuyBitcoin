/**
 * Tests for the chart runtime injected into every generated chart page.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

// The runtime is a classic script; evaluate it with a CommonJS-style module
// object so it exports its helpers instead of starting in a browser.
function loadRuntime() {
    const source = readFileSync(
        join(process.cwd(), "src", "whenshouldubuybitcoin", "templates", "chart_runtime.js"),
        "utf-8"
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const runtime = loadRuntime();

const DAY = 864e5;

describe("parseMode", () => {
    it("uses an explicit mode from the query string", () => {
        expect(runtime.parseMode("?mode=preview", false, false)).toBe("preview");
        expect(runtime.parseMode("?a=1&mode=full", false, true)).toBe("full");
        expect(runtime.parseMode("?mode=interactive", false, true)).toBe("interactive");
    });

    it("ignores unknown modes", () => {
        expect(runtime.parseMode("?mode=evil", false, false)).toBe("interactive");
    });

    it("treats a chart opened on its own as full screen", () => {
        expect(runtime.parseMode("", true, true)).toBe("full");
        expect(runtime.parseMode("", true, false)).toBe("full");
    });

    it("falls back by pointer type when embedded without a mode", () => {
        expect(runtime.parseMode("", false, true)).toBe("preview");
        expect(runtime.parseMode("", false, false)).toBe("interactive");
    });
});

describe("dataExtent", () => {
    const xs = [0, 1, 2, 3, 4];
    const ys = [10, 50, 20, null, 30];

    it("only uses points inside the visible x window", () => {
        expect(runtime.dataExtent(xs, ys, 2, 4, false)).toEqual([20, 30]);
    });

    it("skips missing and non-numeric values", () => {
        expect(runtime.dataExtent([0, 1, 2], [null, "x", 5], 0, 2, false)).toEqual([5, 5]);
    });

    it("works in log10 units and skips non-positive values on log axes", () => {
        expect(runtime.dataExtent([0, 1, 2], [0, 10, 1000], 0, 2, true)).toEqual([1, 3]);
    });

    it("returns null when no point is visible", () => {
        expect(runtime.dataExtent(xs, ys, 10, 20, false)).toBeNull();
    });
});

describe("mergeExtents and padExtent", () => {
    it("merges extents and ignores nulls", () => {
        expect(runtime.mergeExtents([[1, 3], null, [0, 2]])).toEqual([0, 3]);
        expect(runtime.mergeExtents([null])).toBeNull();
    });

    it("pads by a fraction of the span", () => {
        expect(runtime.padExtent([0, 100], 0.05)).toEqual([-5, 105]);
    });

    it("pads a flat line so it is not drawn on the edge", () => {
        const [lo, hi] = runtime.padExtent([2, 2], 0.05);
        expect(lo).toBeLessThan(2);
        expect(hi).toBeGreaterThan(2);
    });
});

describe("presetRange", () => {
    const end = Date.UTC(2026, 8, 30);
    const start = Date.UTC(2015, 0, 1);

    it("shows the last year", () => {
        expect(runtime.presetRange("1y", start, end)).toEqual([end - 365 * DAY, end]);
    });

    it("shows the last three years", () => {
        expect(runtime.presetRange("3y", start, end)).toEqual([end - 3 * 365 * DAY, end]);
    });

    it("never starts before the data", () => {
        expect(runtime.presetRange("3y", end - 100 * DAY, end)).toEqual([end - 100 * DAY, end]);
    });

    it("shows everything for all", () => {
        expect(runtime.presetRange("all", start, end)).toEqual([start, end]);
    });
});

describe("availablePresets", () => {
    it("offers only presets shorter than the data", () => {
        expect(runtime.availablePresets(10 * 365 * DAY)).toEqual(["1y", "3y", "all"]);
        expect(runtime.availablePresets(2 * 365 * DAY)).toEqual(["1y", "all"]);
        expect(runtime.availablePresets(30 * DAY)).toEqual([]);
    });
});

describe("zoomRange", () => {
    const bounds = [0, 1000];

    it("zooms in around the pinch centre", () => {
        expect(runtime.zoomRange([0, 1000], 0.5, 2, 10, bounds)).toEqual([250, 750]);
        expect(runtime.zoomRange([0, 1000], 0, 2, 10, bounds)).toEqual([0, 500]);
    });

    it("does not zoom in past the minimum span", () => {
        expect(runtime.zoomRange([400, 600], 0.5, 100, 50, bounds)).toEqual([475, 525]);
    });

    it("does not zoom out past the data", () => {
        expect(runtime.zoomRange([200, 800], 0.5, 0.1, 10, bounds)).toEqual([0, 1000]);
    });

    it("shifts the window back inside the data", () => {
        // Zooming out around 900 would give [700, 1100]; it is moved left instead
        expect(runtime.zoomRange([800, 1000], 0.5, 0.5, 10, bounds)).toEqual([600, 1000]);
    });
});

describe("logTickStep", () => {
    it("labels one tick per decade on wide log ranges", () => {
        expect(runtime.logTickStep("log", "auto", [2, 5])).toBe(1);
    });

    it("lets Plotly choose ticks on narrow log ranges", () => {
        expect(runtime.logTickStep("log", "auto", [4.6, 5.1])).toBeNull();
    });

    it("leaves linear axes and explicit tick lists alone", () => {
        expect(runtime.logTickStep("linear", "auto", [0, 100])).toBeUndefined();
        expect(runtime.logTickStep("log", "array", [0, 3])).toBeUndefined();
    });
});
