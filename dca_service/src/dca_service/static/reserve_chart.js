/*
 * Reserve chart: BTC price, your average cost and the BTC you bought each
 * week, with a readout above the chart that follows the pointer.
 *
 * No zoom or pan. Moving the mouse, or dragging a finger sideways, moves a
 * crosshair and the readout shows that day; vertical swipes still scroll the
 * page. The range buttons pick the time span.
 *
 * Classic script: in the browser it defines window.ReserveChart; under tests
 * it exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.ReserveChart = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var DAY = 864e5;
    var WEEK = 7 * DAY;
    var RANGE_DAYS = { "3m": 91, "6m": 182, "1y": 365 };

    // ---- Pure helpers (unit tested) ----

    function parseUtc(value) {
        var text = String(value);
        if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return Date.parse(text + "T00:00:00Z");
        if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += "Z";
        return Date.parse(text);
    }

    function list(value) {
        return Array.isArray(value) ? value : [];
    }

    function buildSeries(data) {
        if (!data) return null;
        var txDates = list(data.dates);
        var marketDates = list(data.market_dates).length ? data.market_dates : txDates;
        var marketPrices = list(data.market_prices).length ? data.market_prices : list(data.prices);
        var avgs = list(data.avg_price_timeline).length ? data.avg_price_timeline : list(data.avg_price);
        var buysBtc = list(data.purchase_btc);
        var buysUsd = list(data.purchase_usd);
        if (!txDates.length || !marketDates.length) return null;

        var txs = txDates.map(function (d, i) {
            return { t: parseUtc(d), btc: Number(buysBtc[i]) || 0, usd: Number(buysUsd[i]) || 0 };
        }).sort(function (a, b) { return a.t - b.t; });

        var days = [];
        var held = 0;
        var next = 0;
        marketDates.forEach(function (d, i) {
            var t = parseUtc(d);
            while (next < txs.length && txs[next].t < t + DAY) {
                held += txs[next].btc;
                next += 1;
            }
            days.push({ t: t, price: Number(marketPrices[i]) || 0, avg: Number(avgs[i]) || 0, btc: round(held) });
        });

        var firstDay = Math.floor(txs[0].t / DAY) * DAY;
        var weeks = [];
        txs.forEach(function (tx) {
            if (tx.btc <= 0) return;
            var k = Math.floor((tx.t - firstDay) / WEEK);
            var week = weeks[k] || (weeks[k] = { start: firstDay + k * WEEK, btc: 0, usd: 0, count: 0 });
            week.btc += tx.btc;
            week.usd += tx.usd;
            week.count += 1;
        });
        return { days: days, weeks: weeks.filter(Boolean) };
    }

    function round(value) {
        return Math.round(value * 1e12) / 1e12;
    }

    function visibleDays(series, range, now) {
        if (!series || !series.days.length) return [];
        var span = RANGE_DAYS[range];
        if (!span) return series.days.slice();
        var end = typeof now === "number" ? now : series.days[series.days.length - 1].t;
        var start = end - span * DAY;
        return series.days.filter(function (d) { return d.t >= start; });
    }

    function yDomain(days) {
        var lo = Infinity;
        var hi = -Infinity;
        days.forEach(function (d) {
            [d.price, d.avg].forEach(function (v) {
                if (v > 0) {
                    lo = Math.min(lo, v);
                    hi = Math.max(hi, v);
                }
            });
        });
        if (!isFinite(lo)) return [0, 1];
        var pad = (hi - lo) * 0.08 || hi * 0.05 || 1;
        return [lo - pad, hi + pad];
    }

    function weekOf(series, t) {
        for (var i = 0; i < series.weeks.length; i++) {
            var w = series.weeks[i];
            if (t >= w.start && t < w.start + WEEK) return w;
        }
        return null;
    }

    function finite(value) {
        return typeof value === "number" && isFinite(value);
    }

    function readoutAt(series, day, current) {
        current = current || {};
        var live = !day;
        var at = day || series.days[series.days.length - 1];
        var btc = at.btc;
        var price = at.price;
        var avg = at.avg;
        if (live) {
            if (finite(current.currentBtc)) btc = current.currentBtc;
            if (finite(current.currentPrice) && current.currentPrice > 0) price = current.currentPrice;
            if (finite(current.currentAvg) && current.currentAvg > 0) avg = current.currentAvg;
        }
        return {
            live: live,
            t: at.t,
            btc: btc,
            price: price,
            avg: avg,
            valueUsd: btc * price,
            pnlPct: avg > 0 ? (price / avg - 1) * 100 : null,
            week: weekOf(series, at.t)
        };
    }

    function formatBtc(value) {
        return Number(value || 0).toFixed(Math.abs(value) >= 1 ? 4 : 8);
    }

    function money(value) {
        return "$" + Math.round(value || 0).toLocaleString("en-US");
    }

    function shortDate(t, withYear) {
        var opts = { month: "short", day: "numeric", timeZone: "UTC" };
        if (withYear) opts.year = "numeric";
        return new Date(t).toLocaleDateString("en-US", opts);
    }

    function niceStep(raw) {
        var mag = Math.pow(10, Math.floor(Math.log10(raw)));
        var steps = [1, 2, 2.5, 5, 10];
        for (var i = 0; i < steps.length; i++) {
            if (steps[i] * mag >= raw) return steps[i] * mag;
        }
        return 10 * mag;
    }

    function escapeHtml(text) {
        return String(text).replace(/[&<>"]/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
        });
    }

    function readoutHtml(r) {
        var label = r.live ? "Bitcoin held" : "Bought by " + shortDate(r.t, true);
        var pnl = "";
        if (r.pnlPct !== null) {
            var up = r.pnlPct >= 0;
            pnl = '<span class="reserve-pnl ' + (up ? "is-up" : "is-down") + '">' +
                (up ? "+" : "−") + Math.abs(r.pnlPct).toFixed(1) + "% vs avg cost</span>";
        }
        var week = r.week
            ? '<span>' + (r.live ? "This week" : "That week") + ' <b>₿' + formatBtc(r.week.btc) + "</b> · " +
                r.week.count + (r.week.count === 1 ? " buy" : " buys") + "</span>"
            : "";
        return '<span class="reserve-readout-label">' + escapeHtml(label) + "</span>" +
            '<span class="reserve-readout-btc"><span class="reserve-btc-symbol">₿</span>' + formatBtc(r.btc) + "</span>" +
            '<span class="reserve-readout-sub">≈ ' + money(r.valueUsd) + " " + pnl + "</span>" +
            '<span class="reserve-readout-row"><span>BTC <b>' + money(r.price) + "</b></span>" +
            "<span>Avg cost <b>" + money(r.avg) + "</b></span>" + week + "</span>";
    }

    // ---- Browser rendering ----

    function token(el, name, fallback) {
        var value = getComputedStyle(el).getPropertyValue(name).trim();
        return value || fallback;
    }

    function mount(rootEl) {
        var canvas = rootEl.querySelector("canvas");
        var readout = rootEl.querySelector("[data-reserve-readout]");
        var rangeGroup = rootEl.querySelector("[data-reserve-range]");
        var state = { series: null, current: {}, range: "1y", hover: null, view: [], geom: null, signature: "" };
        var frame = 0;

        function schedule() {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(draw);
        }

        function setRange(range) {
            state.range = range;
            state.hover = null;
            if (rangeGroup) {
                rangeGroup.querySelectorAll("[data-range]").forEach(function (btn) {
                    btn.setAttribute("aria-pressed", btn.dataset.range === range ? "true" : "false");
                });
            }
            schedule();
        }

        function draw() {
            if (!state.series) return;
            var width = canvas.clientWidth;
            var height = canvas.clientHeight;
            if (!width || !height) return;
            var dpr = window.devicePixelRatio || 1;
            if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
                canvas.width = Math.round(width * dpr);
                canvas.height = Math.round(height * dpr);
            }
            var ctx = canvas.getContext("2d");
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, width, height);

            var colors = {
                price: token(rootEl, "--reserve-price", "#f2a33a"),
                avg: token(rootEl, "--reserve-avg", "#16a37a"),
                bar: token(rootEl, "--reserve-bar", "#f97316"),
                grid: token(rootEl, "--reserve-grid", "rgba(120,120,120,0.18)"),
                axis: token(rootEl, "--reserve-axis", "#6b7280"),
                surface: token(rootEl, "--reserve-surface", "#ffffff")
            };
            var font = getComputedStyle(rootEl).fontFamily;
            var compact = width < 520;
            var view = visibleDays(state.series, state.range);
            if (!view.length) view = state.series.days.slice(-1);
            state.view = view;

            var axisW = compact ? 46 : 58;
            var stripH = Math.round(height * 0.2);
            var g = {
                left: 2,
                right: width - axisW,
                top: 8,
                bottom: height - 22 - stripH - 12,
                stripTop: height - 22 - stripH,
                stripBottom: height - 22
            };
            var t0 = view[0].t;
            var t1 = Math.max(view[view.length - 1].t, t0 + DAY);
            var domain = yDomain(view);
            var lo = domain[0];
            var hi = domain[1];
            function X(t) { return g.left + (t - t0) / (t1 - t0) * (g.right - g.left); }
            function Y(v) { return g.bottom - (v - lo) / (hi - lo) * (g.bottom - g.top); }
            state.geom = { g: g, t0: t0, t1: t1 };

            ctx.font = (compact ? 11 : 12) + "px " + font;
            ctx.lineWidth = 1;
            var step = niceStep((hi - lo) / 4);
            for (var y = Math.ceil(lo / step) * step; y <= hi; y += step) {
                var py = Math.round(Y(y)) + 0.5;
                ctx.strokeStyle = colors.grid;
                ctx.beginPath();
                ctx.moveTo(g.left, py);
                ctx.lineTo(g.right, py);
                ctx.stroke();
                ctx.fillStyle = colors.axis;
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                ctx.fillText(y >= 10000 ? "$" + Math.round(y / 1000) + "k" : money(y), g.right + 8, py);
            }

            var ticks = compact ? 3 : 6;
            var longSpan = t1 - t0 > 200 * DAY;
            ctx.textBaseline = "alphabetic";
            for (var i = 0; i <= ticks; i++) {
                var tt = t0 + (t1 - t0) * i / ticks;
                var label = longSpan
                    ? new Date(tt).toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" })
                    : shortDate(tt, false);
                ctx.textAlign = i === 0 ? "left" : i === ticks ? "right" : "center";
                ctx.fillText(label, X(tt), height - 5);
            }

            // Weekly buys, in BTC, along the bottom strip
            var weeks = state.series.weeks.filter(function (w) { return w.start + WEEK > t0; });
            var maxBtc = 0;
            weeks.forEach(function (w) { maxBtc = Math.max(maxBtc, w.btc); });
            var barW = Math.max(1.5, (g.right - g.left) / ((t1 - t0) / WEEK) - (compact ? 1.5 : 2));
            var hoverWeek = state.hover ? weekOf(state.series, state.hover.t) : null;
            weeks.forEach(function (w) {
                var mid = X(w.start + WEEK / 2);
                var h = maxBtc > 0 ? (g.stripBottom - g.stripTop) * w.btc / maxBtc : 0;
                var x = Math.max(g.left, mid - barW / 2);
                var right = Math.min(g.right, mid + barW / 2);
                if (right <= x) return;
                ctx.globalAlpha = hoverWeek && hoverWeek !== w ? 0.45 : 0.9;
                ctx.fillStyle = colors.bar;
                ctx.fillRect(x, g.stripBottom - h, right - x, Math.max(h, 1));
            });
            ctx.globalAlpha = 1;
            ctx.fillStyle = colors.axis;
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
            ctx.fillText("Buys", g.right + 8, g.stripTop);

            line(ctx, view, X, function (d) { return Y(d.avg); }, colors.avg, 2, [6, 5]);
            line(ctx, view, X, function (d) { return Y(d.price); }, colors.price, compact ? 2.2 : 2, []);

            var at = state.hover || view[view.length - 1];
            if (state.hover) {
                var cx = Math.round(X(at.t)) + 0.5;
                ctx.strokeStyle = colors.axis;
                ctx.globalAlpha = 0.6;
                ctx.beginPath();
                ctx.moveTo(cx, g.top);
                ctx.lineTo(cx, g.stripBottom);
                ctx.stroke();
                ctx.globalAlpha = 1;
            }
            [[at.avg, colors.avg], [at.price, colors.price]].forEach(function (pair) {
                if (!(pair[0] > 0)) return;
                ctx.beginPath();
                ctx.arc(X(at.t), Y(pair[0]), 4, 0, Math.PI * 2);
                ctx.fillStyle = pair[1];
                ctx.fill();
                ctx.strokeStyle = colors.surface;
                ctx.lineWidth = 2;
                ctx.stroke();
            });

            if (readout) readout.innerHTML = readoutHtml(readoutAt(state.series, state.hover, state.current));
        }

        function pick(clientX) {
            if (!state.geom || !state.view.length) return null;
            var rect = canvas.getBoundingClientRect();
            var g = state.geom.g;
            var t = state.geom.t0 + (clientX - rect.left - g.left) / (g.right - g.left) * (state.geom.t1 - state.geom.t0);
            var best = state.view[0];
            for (var i = 1; i < state.view.length; i++) {
                if (Math.abs(state.view[i].t - t) < Math.abs(best.t - t)) best = state.view[i];
            }
            return best;
        }

        function onMove(event) {
            var day = pick(event.clientX);
            if (!day || day === state.hover) return;
            state.hover = day;
            schedule();
        }

        function onLeave() {
            if (!state.hover) return;
            state.hover = null;
            schedule();
        }

        function onKey(event) {
            if (!state.view.length) return;
            var index = state.hover ? state.view.indexOf(state.hover) : state.view.length - 1;
            if (event.key === "ArrowLeft") index = Math.max(0, index - 1);
            else if (event.key === "ArrowRight") index = Math.min(state.view.length - 1, index + 1);
            else if (event.key === "Escape") { onLeave(); return; }
            else return;
            event.preventDefault();
            state.hover = state.view[index];
            schedule();
        }

        canvas.addEventListener("pointermove", onMove);
        canvas.addEventListener("pointerdown", onMove);
        canvas.addEventListener("pointerleave", onLeave);
        canvas.addEventListener("pointercancel", onLeave);
        canvas.addEventListener("pointerup", function (event) {
            if (event.pointerType !== "mouse") onLeave();
        });
        canvas.addEventListener("keydown", onKey);
        canvas.addEventListener("blur", onLeave);
        if (rangeGroup) {
            rangeGroup.addEventListener("click", function (event) {
                var btn = event.target.closest("[data-range]");
                if (btn) setRange(btn.dataset.range);
            });
        }
        if (typeof ResizeObserver === "function") new ResizeObserver(schedule).observe(canvas);
        if (typeof MutationObserver === "function") {
            new MutationObserver(schedule).observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
        }

        return {
            setData: function (data, current) {
                var signature = JSON.stringify([data && data.dates && data.dates.length, data && data.market_dates && data.market_dates.length,
                    data && data.btc_balance && data.btc_balance[data.btc_balance.length - 1], current]);
                state.current = current || {};
                if (signature !== state.signature) {
                    state.signature = signature;
                    state.series = buildSeries(data);
                    state.hover = null;
                }
                rootEl.classList.toggle("is-empty", !state.series);
                schedule();
            },
            setRange: setRange,
            redraw: schedule
        };
    }

    function line(ctx, days, X, Y, color, width, dash) {
        ctx.save();
        ctx.setLineDash(dash);
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineJoin = "round";
        ctx.beginPath();
        var started = false;
        days.forEach(function (d) {
            var y = Y(d);
            if (!isFinite(y)) return;
            if (started) ctx.lineTo(X(d.t), y);
            else { ctx.moveTo(X(d.t), y); started = true; }
        });
        ctx.stroke();
        ctx.restore();
    }

    return {
        buildSeries: buildSeries,
        visibleDays: visibleDays,
        yDomain: yDomain,
        readoutAt: readoutAt,
        readoutHtml: readoutHtml,
        formatBtc: formatBtc,
        mount: mount
    };
});
