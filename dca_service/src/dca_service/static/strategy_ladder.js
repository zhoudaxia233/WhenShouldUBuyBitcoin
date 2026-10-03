/*
 * Strategy tier ladder for the home page's "Next buy" card.
 *
 * Given the band the DCA engine reported (decision.ahr_band) and the saved
 * strategy, returns every tier of that strategy with its multiplier and marks
 * the current one. Tiers, labels and default multipliers mirror
 * services/dca_engine.py, so the ladder never disagrees with the engine.
 *
 * Classic script: in the browser it defines window.StrategyLadder; under tests
 * it exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.StrategyLadder = api;
    }
})(typeof window !== "undefined" ? window : this, function () {
    "use strict";

    // [key, label, range, field, legacy field, default multiplier]
    var PERCENTILE = [
        ["p10", "Extreme cheap", "Bottom 10%", "ahr999_multiplier_p10", "ahr999_multiplier_low", 5],
        ["p25", "Very cheap", "10–25%", "ahr999_multiplier_p25", "ahr999_multiplier_mid", 2],
        ["p50", "Cheap", "25–50%", "ahr999_multiplier_p50", null, 1],
        ["p75", "Fair", "50–75%", "ahr999_multiplier_p75", null, 0],
        ["p90", "Expensive", "75–90%", "ahr999_multiplier_p90", null, 0],
        ["p100", "Very expensive", "Top 10%", "ahr999_multiplier_p100", "ahr999_multiplier_high", 0]
    ];

    var FIXED_RANGE = [
        ["r045", "Extremely cheap", "< 0.45", "ahr999_multiplier_r045", null, 5],
        ["r050", "Very cheap", "0.45–0.50", "ahr999_multiplier_r050", null, 3],
        ["r060", "Cheap", "0.50–0.60", "ahr999_multiplier_r060", null, 2],
        ["r070", "Fair", "0.60–0.70", "ahr999_multiplier_r070", null, 1],
        ["r080", "Getting expensive", "0.70–0.80", "ahr999_multiplier_r080", null, 0.5],
        ["r090", "Expensive", "0.80–0.90", "ahr999_multiplier_r090", null, 0],
        ["r100", "Very expensive", "0.90–1.00", "ahr999_multiplier_r100", null, 0],
        ["r999", "Extremely expensive", "≥ 1.00", "ahr999_multiplier_r999", null, 0]
    ];

    // The dynamic strategy reports a coarse band; its multiplier is a curve, not a table.
    var DYNAMIC = [
        ["low", "Low", "Below a_low", null, null, null],
        ["mid", "Mid", "Between", null, null, null],
        ["high", "High", "Above a_high", null, null, null]
    ];

    function savedNumber(strategy, field) {
        if (!field || !strategy) return null;
        var value = strategy[field];
        if (value === null || value === undefined || value === "") return null;
        var number = Number(value);
        return isFinite(number) ? number : null;
    }

    function tableFor(band) {
        if (/^p\d+$/.test(band)) return PERCENTILE;
        if (/^r\d+$/.test(band)) return FIXED_RANGE;
        if (band === "low" || band === "mid" || band === "high") return DYNAMIC;
        return null;
    }

    function buildLadder(band, strategy) {
        var key = typeof band === "string" ? band.trim().toLowerCase() : "";
        var table = tableFor(key);
        if (!table) return null;
        var tiers = table.map(function (row) {
            var multiplier = row[5];
            if (row[3]) {
                var saved = savedNumber(strategy, row[3]);
                if (saved === null) saved = savedNumber(strategy, row[4]);
                if (saved !== null) multiplier = saved;
            }
            return { key: row[0], label: row[1], range: row[2], multiplier: multiplier, current: row[0] === key };
        });
        var current = null;
        tiers.forEach(function (tier) { if (tier.current) current = tier; });
        if (!current) return null;
        return { tiers: tiers, current: current };
    }

    function formatMultiplier(value) {
        if (value === null || value === undefined || !isFinite(value)) return "";
        return String(Number(value.toFixed(2))) + "×";
    }

    return {
        buildLadder: buildLadder,
        formatMultiplier: formatMultiplier
    };
});
