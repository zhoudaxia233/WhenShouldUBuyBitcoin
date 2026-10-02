/**
 * Tests for the homepage layout: Today view first, section navigation,
 * and light/dark themes.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("Site layout", () => {
    let html;
    let css;

    beforeAll(() => {
        html = readFileSync(join(process.cwd(), "docs", "index.html"), "utf-8");
        css = html.slice(html.indexOf("<style>"), html.indexOf("</style>"));
    });

    describe("navigation", () => {
        it("has one section button per view, Today first and active", () => {
            const tabs = [...html.matchAll(/<button class="main-tab[^"]*" type="button" data-tab="([a-z]+)"/g)].map(m => m[1]);
            expect(tabs).toEqual(["today", "charts", "backtest", "forecast", "resources"]);
            expect(html).toMatch(/class="main-tab active" type="button" data-tab="today" aria-current="page"/);
        });

        it("has a panel for every view", () => {
            for (const tab of ["today", "charts", "backtest", "forecast", "resources"]) {
                expect(html).toContain(`id="${tab}-tab"`);
            }
            expect(html).not.toContain('id="analysis-tab"');
            expect(html).not.toContain('id="tools-tab"');
        });

        it("opens the view named in the address", () => {
            expect(html).toContain("const linkedTab = location.hash.slice(1);");
            expect(html).toContain("history.replaceState");
        });

        it("loads charts only when the charts view opens", () => {
            const init = html.slice(html.indexOf("document.addEventListener('DOMContentLoaded', () => {\n            document.getElementById('todayDate')"));
            expect(init.slice(0, 600)).not.toContain("setActiveChart(");
            expect(html).toContain("if (tabName === 'charts') {");
        });
    });

    describe("Today view", () => {
        it("answers without a button press", () => {
            expect(html).not.toContain('id="checkButton"');
            expect(html).toContain('id="todayHeadline"');
            expect(html).toContain('id="todayActions"');
            expect(html).toContain('id="todayRefresh"');
        });

        it("shows the three measures, with the ahr999 meter", () => {
            for (const id of ["todayMeter", "todayNeedle", "todayAhr999", "todayDcaCost", "todayDcaBar", "todayTrend", "todayTrendBar"]) {
                expect(html).toContain(`id="${id}"`);
            }
        });

        it("keeps the full daily summary and the detailed numbers behind disclosures", () => {
            expect(html).toMatch(/<details class="card disclosure">\s*<summary>Full daily summary/);
            expect(html).toMatch(/<summary>Detailed valuation numbers<\/summary>\s*<div id="results"/);
        });

        it("loads the Today view script before the real-time checker", () => {
            expect(html.indexOf('<script src="today.js"></script>')).toBeGreaterThan(-1);
            expect(html.indexOf('<script src="today.js"></script>')).toBeLessThan(html.indexOf('<script src="realtime.js"></script>'));
        });
    });

    describe("themes", () => {
        it("defines every colour token for light and both dark paths", () => {
            const light = css.match(/:root \{([\s\S]*?)\n        \}/)[1];
            const tokens = [...light.matchAll(/(--[a-z0-9-]+):/g)].map(m => m[1]).filter(t => !t.startsWith("--font") && t !== "--shadow");
            const mediaDark = css.slice(css.indexOf('@media (prefers-color-scheme: dark) {\n            :root:not([data-theme="light"]) {'));
            const explicitDark = css.slice(css.indexOf(':root[data-theme="dark"] {'));
            for (const token of tokens) {
                expect(mediaDark.slice(0, 2500)).toContain(`${token}:`);
                expect(explicitDark.slice(0, 2500)).toContain(`${token}:`);
            }
        });

        it("paints the body from tokens", () => {
            expect(css).toMatch(/body \{\s*font-family: var\(--font-body\);\s*background: var\(--bg\);\s*color: var\(--ink\);/);
        });

        it("applies a saved theme before the page renders, tolerating blocked storage", () => {
            const head = html.slice(0, html.indexOf("<style>"));
            expect(head).toMatch(/try \{\s*const savedTheme = localStorage\.getItem\('theme'\);/);
        });

        it("has a labelled theme toggle", () => {
            expect(html).toMatch(/id="themeToggle" class="theme-toggle" type="button" aria-label="Switch to dark mode"/);
            expect(html).toContain("function toggleTheme()");
        });
    });
});

describe("Cross-checks", () => {
    it("has its own section next to the ahr999 measures, hidden until there is data", () => {
        const html = readFileSync(join(process.cwd(), "docs", "index.html"), "utf-8");
        expect(html).toMatch(/<section id="todayCrossSection" class="today-crosschecks" aria-labelledby="crossTitle" hidden>/);
        expect(html).toContain('id="todayCrossChecks"');
        expect(html).toContain('id="todayCrossSummary"');
    });

    it("feeds MVRV and the 200-week average to the Today view", () => {
        const realtime = readFileSync(join(process.cwd(), "docs", "realtime.js"), "utf-8");
        expect(realtime).toContain("async function loadLatestMvrv()");
        expect(realtime).toContain("window.TodayView.renderCrossChecks({ price: realtimePrice, ma200w, mvrv: latestMvrv });");
    });
});
