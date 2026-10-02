/*
 * Charts view: "Where the trend points". Projects the power-law trend 1, 2
 * and 4 years ahead and shows how far each projection moved since the fit
 * of a year ago.
 *
 * Classic script: in the browser it defines window.TrendOutlook; under tests
 * it exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.TrendOutlook = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var GENESIS = Date.UTC(2009, 0, 3);
    var DAY_MS = 864e5;
    var HORIZONS = [[1, "In 1 year"], [2, "In 2 years"], [4, "In 4 years"]];

    function isoDay(date) {
        return date.toISOString().slice(0, 10);
    }

    function trendAt(a, b, isoDate) {
        var age = Math.floor((Date.parse(isoDate + "T00:00:00Z") - GENESIS) / DAY_MS);
        return a * Math.pow(age, b);
    }

    function usable(a, b) {
        return typeof a === "number" && typeof b === "number" && isFinite(a) && isFinite(b) && a > 0;
    }

    function buildOutlook(meta, now) {
        if (!meta || !usable(meta.trend_a, meta.trend_b)) return null;
        var old = meta.trend_year_ago;
        var hasOld = !!old && usable(old.a, old.b);
        var today = isoDay(now);
        var rows = HORIZONS.map(function (h) {
            var target = new Date(Date.UTC(now.getUTCFullYear() + h[0], now.getUTCMonth(), now.getUTCDate()));
            var date = isoDay(target);
            var value = trendAt(meta.trend_a, meta.trend_b, date);
            var oldValue = hasOld ? trendAt(old.a, old.b, date) : null;
            return {
                label: h[1],
                date: date,
                value: value,
                yearAgoValue: oldValue,
                changePct: hasOld ? (value / oldValue - 1) * 100 : null
            };
        });
        return {
            today: trendAt(meta.trend_a, meta.trend_b, today),
            rows: rows,
            yearAgoAsOf: hasOld ? old.as_of : null
        };
    }

    function money(value) {
        return "$" + Math.round(value).toLocaleString("en-US");
    }

    function longDate(isoDate) {
        return new Date(isoDate + "T00:00:00Z").toLocaleDateString("en-US", {
            month: "short", day: "numeric", year: "numeric", timeZone: "UTC"
        });
    }

    function renderOutlook(outlook) {
        if (!outlook) {
            return '<p class="outlook-empty">Trend projections are unavailable right now.</p>';
        }
        var rows = outlook.rows.map(function (row) {
            var drift = "";
            if (row.changePct !== null) {
                var direction = row.changePct >= 0 ? "higher" : "lower";
                drift = '<span class="outlook-drift">A year ago the fit said ' + money(row.yearAgoValue) +
                    '. Now ' + Math.abs(row.changePct).toFixed(0) + '% ' + direction + '.</span>';
            }
            return '<li class="outlook-row">' +
                '<span class="outlook-when"><span class="outlook-label">' + row.label + '</span>' +
                '<span class="outlook-date">' + longDate(row.date) + '</span></span>' +
                '<span class="outlook-value">' + money(row.value) + '</span>' +
                drift +
                '</li>';
        }).join("");
        var note = outlook.yearAgoAsOf
            ? "Each line compares today's fit with the fit as of " + longDate(outlook.yearAgoAsOf) + ". The gap shows how much one more year of prices moved the projection."
            : "";
        return '<p class="outlook-today">Trend value today: <strong>' + money(outlook.today) + '</strong></p>' +
            '<ul class="outlook-rows">' + rows + '</ul>' +
            (note ? '<p class="outlook-note">' + note + '</p>' : "");
    }

    return { buildOutlook: buildOutlook, renderOutlook: renderOutlook, trendAt: trendAt };
});
