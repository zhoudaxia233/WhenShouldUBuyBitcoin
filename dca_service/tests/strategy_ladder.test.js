// Tests for the strategy tier ladder in the home page's "Next buy" card.
// The tiers and multipliers must match services/dca_engine.py, including its
// defaults and its fallback from the percentile fields to the legacy ones.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadLadder() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "strategy_ladder.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const { buildLadder, formatMultiplier } = loadLadder();

describe("buildLadder", () => {
    it("lists the six percentile tiers with the engine's default multipliers", () => {
        const ladder = buildLadder("p50", {});
        expect(ladder.tiers.map((t) => t.key)).toEqual(["p10", "p25", "p50", "p75", "p90", "p100"]);
        expect(ladder.tiers.map((t) => t.multiplier)).toEqual([5, 2, 1, 0, 0, 0]);
        expect(ladder.tiers.filter((t) => t.current).map((t) => t.key)).toEqual(["p50"]);
        expect(ladder.current.label).toBe("Cheap");
    });

    it("uses saved percentile multipliers, then the legacy fields, then defaults", () => {
        const ladder = buildLadder("p10", {
            ahr999_multiplier_p10: 2,
            ahr999_multiplier_p25: null,
            ahr999_multiplier_mid: 1.5,
            ahr999_multiplier_p50: 1,
            ahr999_multiplier_p100: null,
            ahr999_multiplier_high: 0.25,
        });
        expect(ladder.tiers.map((t) => t.multiplier)).toEqual([2, 1.5, 1, 0, 0, 0.25]);
        expect(ladder.current.label).toBe("Extreme cheap");
    });

    it("lists the eight fixed AHR999 ranges for the fixed-range strategy", () => {
        const ladder = buildLadder("r070", { ahr999_multiplier_r070: 1.25 });
        expect(ladder.tiers).toHaveLength(8);
        expect(ladder.tiers.map((t) => t.multiplier)).toEqual([5, 3, 2, 1.25, 0.5, 0, 0, 0]);
        expect(ladder.current.key).toBe("r070");
        expect(ladder.current.range).toBe("0.60–0.70");
    });

    it("shows three bands without multipliers for the dynamic strategy", () => {
        const ladder = buildLadder("mid", { strategy_type: "dynamic_ahr999" });
        expect(ladder.tiers.map((t) => t.label)).toEqual(["Low", "Mid", "High"]);
        expect(ladder.tiers.every((t) => t.multiplier === null)).toBe(true);
        expect(ladder.current.key).toBe("mid");
    });

    it("returns null when the strategy has no tiers", () => {
        expect(buildLadder("fixed", { strategy_type: "fixed_dca" })).toBeNull();
        expect(buildLadder("DYNAMIC", {})).toBeNull();
        expect(buildLadder(undefined, {})).toBeNull();
    });

    it("accepts band names in any case", () => {
        expect(buildLadder("P25", {}).current.key).toBe("p25");
    });
});

describe("formatMultiplier", () => {
    it("prints whole and fractional multipliers compactly", () => {
        expect(formatMultiplier(2)).toBe("2×");
        expect(formatMultiplier(0.5)).toBe("0.5×");
        expect(formatMultiplier(1.25)).toBe("1.25×");
        expect(formatMultiplier(null)).toBe("");
    });
});
