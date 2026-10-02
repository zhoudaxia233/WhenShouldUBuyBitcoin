/*
 * Today view: turns the live valuation check and the daily report into the
 * verdict, the three action rows, the ahr999 meter and the market backdrop.
 *
 * Classic script: in the browser it defines window.TodayView; under tests it
 * exports the same helpers through a CommonJS-style module object.
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module && module.exports) {
        module.exports = api;
    } else {
        root.TodayView = api;
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    // ---- Pure helpers (unit tested) ----

    function shortDate(isoDate) {
        if (!isoDate) return "";
        var date = new Date(String(isoDate).slice(0, 10) + "T00:00:00Z");
        if (isNaN(date.getTime())) return "";
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
    }

    function onePlace(value) {
        return (Math.round(value * 10) / 10).toFixed(1);
    }

    function extraBuyDetail(status) {
        var dca = status.dcaDistance;
        var trend = status.trendDistance;
        if (!dca.inZone && !trend.inZone) {
            return "Price must fall " + onePlace(Math.max(dca.percentage, trend.percentage)) + "% to enter the buy zone";
        }
        if (!dca.inZone) {
            return "Price must fall " + onePlace(dca.percentage) + "% to the 200-day DCA cost";
        }
        return "Price must fall " + onePlace(trend.percentage) + "% to the long-term trend";
    }

    var STALE_AFTER_DAYS = 7;

    var PRICE_CHART = { src: "charts/price_comparison.html", title: "Price Comparison" };

    function daysBetween(isoDate, now) {
        var then = new Date(String(isoDate).slice(0, 10) + "T00:00:00Z");
        var today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
        return Math.round((today - then.getTime()) / 86400000);
    }

    function onchainAction(onchain, now) {
        var score = Math.round(onchain.score);
        var notCheap = onchain.zone === "Watch";
        var action = {
            tone: notCheap ? "warn" : "good",
            title: "On-chain signals: " + (notCheap ? "not cheap yet" : onchain.zone.toLowerCase()) + " (" + score + "/100)",
            detail: "Sentiment gauge, not a buy signal · " + shortDate(onchain.date),
            target: {
                src: "charts/bottom_signals.html?v=" + encodeURIComponent(onchain.date),
                title: "On-chain bottom signals",
            },
        };
        var age = daysBetween(onchain.date, now);
        if (age > STALE_AFTER_DAYS) {
            action.tone = "stale";
            action.detail = "Last reading " + shortDate(onchain.date) + ", " + age + " days old";
        }
        return action;
    }

    // Plain DCA is the baseline. In a backtest without look-ahead the ahr999
    // tilt beat it by only a few percent, so ahr999 informs but never sets
    // the verdict; the verdict follows the double-undervaluation buy zone.
    var BACKTEST_VIEW = { tab: "backtest", title: "Backtest" };

    function buildVerdict(status, onchain, now) {
        now = now || new Date();
        var headline = status.isDoubleUndervalued
            ? "In the buy zone. A good time to add extra."
            : "Keep buying steadily. Not in the buy zone yet.";

        var actions = [{
            tone: "good",
            title: "Regular DCA: keep going",
            detail: "Signals barely beat it in our backtest · See results",
            target: BACKTEST_VIEW,
        }];

        if (status.isDoubleUndervalued) {
            actions.push({ tone: "good", title: "Extra buy: yes", detail: "Price is below both the 200-day DCA cost and the trend", target: PRICE_CHART });
        } else {
            actions.push({ tone: "warn", title: "Extra buy: not yet", detail: extraBuyDetail(status), target: PRICE_CHART });
        }

        if (onchain) {
            actions.push(onchainAction(onchain, now));
        }

        return { headline: headline, actions: actions };
    }

    // MVRV and the 200-week average are shown next to ahr999, never blended
    // into it, so a reader can see whether they agree.
    function buildCrossChecks(input, now) {
        now = now || new Date();
        var cards = [];
        if (input.ma200w && input.price) {
            var ratio = input.price / input.ma200w;
            cards.push({
                key: "ma200w",
                label: "Price vs 200-week average",
                value: ratio.toFixed(2) + "\u00d7",
                chip: ratio < 1 ? { text: "Below: cycle-low reading", tone: "good" } : { text: "Above", tone: "neutral" },
                low: ratio < 1,
                tone: "fresh",
                detail: "200-week average $" + Math.round(input.ma200w).toLocaleString("en-US"),
                target: { src: "charts/ma_cross_analysis.html", title: "MA Cross Analysis" },
            });
        }
        if (input.mvrv && input.mvrv.value != null) {
            var mvrv = input.mvrv.value;
            var age = daysBetween(input.mvrv.date, now);
            var stale = age > STALE_AFTER_DAYS;
            cards.push({
                key: "mvrv",
                label: "MVRV",
                value: mvrv.toFixed(2),
                chip: mvrv < 1 ? { text: "Below 1: cycle-low reading", tone: "good" } : { text: "Above 1", tone: "neutral" },
                low: mvrv < 1,
                tone: stale ? "stale" : "fresh",
                detail: stale
                    ? "Last reading " + shortDate(input.mvrv.date) + ", " + age + " days old"
                    : "Market value \u00f7 what holders paid \u00b7 " + shortDate(input.mvrv.date),
                target: {
                    src: "charts/bottom_signals.html?v=" + encodeURIComponent(input.mvrv.date),
                    title: "On-chain bottom signals",
                },
            });
        }
        var lows = cards.filter(function (card) { return card.low; }).length;
        return {
            cards: cards,
            summary: cards.length ? "Independent of ahr999. " + lows + " of " + cards.length + " at a cycle-low reading." : "",
        };
    }

    function cheaperThanShare(percentile) {
        return Math.round(100 - Math.min(100, Math.max(0, percentile)));
    }

    // Dial centre (200, 200), needle length 130; 0 points left, 100 right.
    function needlePoint(share) {
        var clamped = Math.min(100, Math.max(0, share));
        var angle = Math.PI * (1 - clamped / 100);
        return { x: 200 + 130 * Math.cos(angle), y: 200 - 130 * Math.sin(angle) };
    }

    function sectionMetrics(report, chart) {
        var sections = (report && report.sections) || [];
        for (var i = 0; i < sections.length; i++) {
            if (sections[i].chart === chart) return sections[i].metrics || null;
        }
        return null;
    }

    function signedBillions(value) {
        var rounded = Math.round(Math.abs(value));
        return (value < 0 ? "−" : "+") + rounded + " bn";
    }

    function buildBackdrop(report) {
        var cards = [];
        var ma = sectionMetrics(report, "MA Cross Analysis");
        if (ma && ma.regime) {
            var bullish = ma.regime === "bullish";
            cards.push({
                label: "Moving averages",
                value: bullish ? "Bullish" : "Bearish",
                detail: bullish ? "Golden cross " + shortDate(ma.last_golden_cross) : "Death cross " + shortDate(ma.last_death_cross),
                target: { src: "charts/ma_cross_analysis.html", title: "MA Cross Analysis" },
            });
        }
        var sentiment = sectionMetrics(report, "Supplemental Bottoming Signals");
        if (sentiment && sentiment.fear_greed_value != null) {
            cards.push({
                label: "Fear & Greed",
                value: Math.round(sentiment.fear_greed_value) + " · " + sentiment.fear_greed_classification,
                detail: "Crowd sentiment index",
                target: null,
            });
        }
        var liquidity = sectionMetrics(report, "Net Liquidity");
        if (liquidity && liquidity.net_liquidity_90d_delta != null) {
            var delta = liquidity.net_liquidity_90d_delta;
            cards.push({
                label: "Net liquidity",
                value: delta < 0 ? "Falling" : "Rising",
                detail: signedBillions(delta) + " in 90 days",
                target: { src: "charts/net_liquidity.html", title: "Net Liquidity" },
            });
        }
        var stress = sectionMetrics(report, "Funding & Credit Stress");
        if (stress && stress.stress_flags != null) {
            cards.push({
                label: "Funding & credit",
                value: stress.stress_flags === 0 ? "Calm" : "Stressed",
                detail: stress.stress_flags + " of 3 stress signs",
                target: { src: "charts/funding_credit_stress.html", title: "Funding & Credit Stress" },
            });
        }
        return cards;
    }

    function onchainFromReport(report) {
        var metrics = sectionMetrics(report, "On-Chain Bottom Signals");
        if (!metrics || metrics.composite_score == null) return null;
        return { score: metrics.composite_score, zone: metrics.zone, date: metrics.data_date };
    }

    // ---- Browser rendering ----

    var CHECK_ICON = '<path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>';
    var WAIT_ICON = '<circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.8"></circle><path d="M8 5.5V8l1.8 1.2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>';

    function byId(id) {
        return document.getElementById(id);
    }

    function setText(id, text) {
        var el = byId(id);
        if (el) el.textContent = text;
    }

    function usd(value) {
        return "$" + Math.round(value).toLocaleString("en-US");
    }

    function setChip(id, text, tone) {
        var el = byId(id);
        if (!el) return;
        el.textContent = text;
        el.className = "chip chip--" + tone;
    }

    var CHEVRON = '<svg class="link-chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
    var ACTION_ICONS = { good: CHECK_ICON, warn: WAIT_ICON, stale: WAIT_ICON };

    function textSpan(className, text) {
        var span = document.createElement("span");
        span.className = className;
        span.textContent = text;
        return span;
    }

    // Opens the chart or page that backs a summary item in the full-screen viewer
    function linkTo(control, target, label) {
        control.type = "button";
        control.setAttribute("aria-label", label + ". Open " + target.title);
        control.addEventListener("click", function () {
            if (target.tab) {
                window.switchMainTab(target.tab);
            } else {
                window.openChartFullscreen(target.src, target.title, control);
            }
        });
        control.insertAdjacentHTML("beforeend", CHEVRON);
    }

    function renderActions(actions) {
        var list = byId("todayActions");
        if (!list) return;
        list.innerHTML = "";
        actions.forEach(function (action) {
            var item = document.createElement("li");
            var control = document.createElement(action.target ? "button" : "div");
            control.className = "today-action today-action--" + action.tone + (action.target ? " today-action--link" : "");
            var dot = document.createElement("span");
            dot.className = "today-action-dot today-action-dot--" + action.tone;
            dot.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' + ACTION_ICONS[action.tone] + "</svg>";
            var text = document.createElement("span");
            text.className = "today-action-text";
            text.appendChild(textSpan("today-action-title", action.title));
            text.appendChild(textSpan("today-action-detail", action.detail));
            control.appendChild(dot);
            control.appendChild(text);
            if (action.target) {
                linkTo(control, action.target, action.title + ", " + action.detail);
            }
            item.appendChild(control);
            list.appendChild(item);
        });
    }

    function renderHeadline(headline) {
        var el = byId("todayHeadline");
        if (!el) return;
        el.innerHTML = "";
        // One sentence per line
        headline.split(/(?<=\.)\s+/).forEach(function (sentence) {
            var line = document.createElement("span");
            line.className = "today-headline-line";
            // Non-breaking hyphen keeps "deep-value" on one line on phones
            line.textContent = sentence.replace(/-/g, "\u2011");
            el.appendChild(line);
        });
    }

    function priceTime(fetchedAt) {
        var date = new Date(fetchedAt);
        if (isNaN(date.getTime())) return "";
        return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" });
    }

    function renderStatus(status, onchain) {
        var verdict = buildVerdict(status, onchain);
        renderHeadline(verdict.headline);
        renderActions(verdict.actions);

        setText("todayPrice", "$" + status.price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
        setText("todayPriceMeta", [status.priceSource, priceTime(status.fetchedAt)].filter(Boolean).join(" · "));

        var share = cheaperThanShare(status.ahr999Percentile);
        var tip = needlePoint(share);
        var needle = byId("todayNeedle");
        if (needle) {
            needle.setAttribute("x2", tip.x.toFixed(1));
            needle.setAttribute("y2", tip.y.toFixed(1));
        }
        var meter = byId("todayMeter");
        if (meter) meter.setAttribute("aria-label", "ahr999 meter: cheaper than " + share + "% of days");
        setText("todayAhr999", status.ahr999.toFixed(3));
        setText("todayCheaper", "cheaper than " + share + "% of days");
        var zone = status.ahr999Zone.zone;
        // Neutral colour: ahr999 informs the reader but no longer drives the verdict
        setChip("todayAhrChip", zone === "bottom" ? "Bottom zone" : zone === "watch" ? "Watch zone" : "DCA zone", "neutral");

        setText("todayDcaCost", usd(status.dcaCost));
        setChip("todayDcaChip", status.dcaDistance.inZone ? "Met" : "−" + onePlace(status.dcaDistance.percentage) + "% to go", status.dcaDistance.inZone ? "good" : "warn");
        byId("todayDcaBar").style.width = Math.min(100, 100 / status.ratioDCA) + "%";
        byId("todayDcaBar").className = "meter-bar-fill meter-bar-fill--" + (status.dcaDistance.inZone ? "good" : "warn");
        setText("todayDcaDetail", "Price is " + status.ratioDCA.toFixed(2) + "× what steady buyers paid over 200 days");

        setText("todayTrend", usd(status.trendValue));
        setChip("todayTrendChip", status.trendDistance.inZone ? "Below trend" : "−" + onePlace(status.trendDistance.percentage) + "% to go", status.trendDistance.inZone ? "good" : "warn");
        byId("todayTrendBar").style.width = Math.min(100, 100 / status.ratioTrend) + "%";
        byId("todayTrendBar").className = "meter-bar-fill meter-bar-fill--" + (status.trendDistance.inZone ? "good" : "warn");
        setText("todayTrendDetail", "Price is " + status.ratioTrend.toFixed(2) + "× the long-term trend");

        var today = byId("today-tab");
        if (today) today.setAttribute("data-state", "ready");
    }

    function renderStatusError() {
        var today = byId("today-tab");
        if (today) today.setAttribute("data-state", "error");
        setText("todayHeadline", "The live price could not be loaded.");
    }

    function renderCrossChecks(input) {
        var grid = byId("todayCrossChecks");
        if (!grid) return;
        var checks = buildCrossChecks(input);
        grid.innerHTML = "";
        checks.cards.forEach(function (card) {
            var item = document.createElement("button");
            item.className = "card crosscheck-card crosscheck-card--" + card.tone;
            item.appendChild(textSpan("crosscheck-label", card.label));
            var row = document.createElement("span");
            row.className = "crosscheck-row";
            row.appendChild(textSpan("crosscheck-value mono", card.value));
            row.appendChild(textSpan("chip chip--" + card.chip.tone, card.chip.text));
            item.appendChild(row);
            item.appendChild(textSpan("crosscheck-detail", card.detail));
            linkTo(item, card.target, card.label + " " + card.value + ", " + card.chip.text + ", " + card.detail);
            grid.appendChild(item);
        });
        setText("todayCrossSummary", checks.summary);
        var section = byId("todayCrossSection");
        if (section) section.hidden = checks.cards.length === 0;
    }

    function renderBackdrop(report) {
        var grid = byId("todayBackdrop");
        if (!grid) return;
        grid.innerHTML = "";
        buildBackdrop(report).forEach(function (card) {
            var item = document.createElement(card.target ? "button" : "div");
            item.className = "backdrop-card" + (card.target ? " backdrop-card--link" : "");
            item.appendChild(textSpan("backdrop-label", card.label));
            item.appendChild(textSpan("backdrop-value", card.value));
            item.appendChild(textSpan("backdrop-detail", card.detail));
            if (card.target) {
                linkTo(item, card.target, card.label + ": " + card.value + ", " + card.detail);
            }
            grid.appendChild(item);
        });
    }

    return {
        buildVerdict: buildVerdict,
        cheaperThanShare: cheaperThanShare,
        needlePoint: needlePoint,
        buildBackdrop: buildBackdrop,
        buildCrossChecks: buildCrossChecks,
        renderCrossChecks: renderCrossChecks,
        onchainFromReport: onchainFromReport,
        renderStatus: renderStatus,
        renderStatusError: renderStatusError,
        renderBackdrop: renderBackdrop,
    };
});
