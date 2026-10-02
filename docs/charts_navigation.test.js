/**
 * Tests for the homepage chart area:
 * two core charts in tabs, six reference charts in a collapsed card section,
 * and a full-screen viewer for interacting with any chart.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

const REFERENCE_CHARTS = {
    "macro-score": "charts/macro_risk_score.html",
    "net-liquidity": "charts/net_liquidity.html",
    "funding-stress": "charts/funding_credit_stress.html",
    "futures-oi": "charts/futures_oi.html",
    "usdjpy": "charts/usdjpy_risk_map.html",
    "ma-cross": "charts/ma_cross_analysis.html",
};

describe("Chart area", () => {
    let html;

    beforeAll(() => {
        html = readFileSync(join(process.cwd(), "docs", "index.html"), "utf-8");
    });

    describe("core charts", () => {
        it("shows only the two valuation charts as tabs", () => {
            const tabs = [...html.matchAll(/<button class="chart-tab[^"]*"[^>]*data-chart="([^"]+)"/g)].map(m => m[1]);
            // Price vs fair value leads; the ahr999 chart is secondary
            expect(tabs).toEqual(["prices", "ratios"]);
        });

        it("marks the tabs up as a tab list", () => {
            expect(html).toContain('role="tablist"');
            expect(html).toMatch(/class="chart-tab active"[^>]*role="tab"[^>]*aria-selected="true"/);
        });

        it("lazy-loads the core chart iframes", () => {
            expect(html).toContain('data-src="charts/valuation_ratios.html"');
            expect(html).toContain('data-src="charts/price_comparison.html"');
        });

        it("no longer has Core/Advanced sections", () => {
            expect(html).not.toContain("switchChartSection");
            expect(html).not.toContain("data-section=");
        });
    });

    describe("reference charts", () => {
        it("has a collapsed toggle that controls the reference panel", () => {
            expect(html).toMatch(/id="referenceToggle"[^>]*aria-expanded="false"[^>]*aria-controls="referencePanel"/);
            expect(html).toMatch(/id="referencePanel"[^>]*hidden/);
        });

        it("has a card and a lazy chart for each reference chart", () => {
            for (const [id, src] of Object.entries(REFERENCE_CHARTS)) {
                expect(html).toContain(`data-ref="${id}"`);
                expect(html).toContain(`data-src="${src}"`);
            }
            const cards = html.match(/class="reference-card"/g) || [];
            expect(cards.length).toBe(Object.keys(REFERENCE_CHARTS).length);
        });

        it("keeps the OI quadrant chart and its legend with the futures chart", () => {
            expect(html).toContain('data-src="charts/oi_quadrant.html"');
            expect(html).toContain('id="q1-legend"');
        });

        it("remembers whether the section is open without depending on storage", () => {
            const storageCalls = html.match(/localStorage\.(getItem|setItem)\([^)]*\)/g) || [];
            expect(storageCalls.length).toBeGreaterThan(0);
            expect(html).toMatch(/try\s*{\s*[^}]*localStorage\.getItem/);
            expect(html).toMatch(/try\s*{\s*[^}]*localStorage\.setItem/);
        });
    });

    describe("full-screen viewer", () => {
        it("is an accessible modal dialog", () => {
            expect(html).toMatch(/id="chartFullscreen"[^>]*role="dialog"[^>]*aria-modal="true"/);
            expect(html).toContain("function openChartFullscreen(");
            expect(html).toContain("function closeChartFullscreen(");
        });

        it("closes with Escape and the back button", () => {
            expect(html).toContain("'Escape'");
            expect(html).toContain("addEventListener('popstate'");
            expect(html).toContain("history.pushState");
        });

        it("loads charts in full mode", () => {
            expect(html).toContain("chartFrameSrc(src, 'full')");
        });
    });

    describe("chart frames", () => {
        it("lets CSS size every chart frame instead of inline iframe heights", () => {
            expect(html).not.toMatch(/<iframe[^>]*class="chart-iframe"[^>]*style=/);
            expect(html).toContain("--frame-h:");
            expect(html).toContain("--frame-h-mobile:");
        });

        it("passes the page theme to every chart", () => {
            expect(html).toContain("`${src}${src.includes('?') ? '&' : '?'}mode=${mode}&theme=${currentTheme()}`");
        });

        it("picks preview mode on touch devices and interactive mode otherwise", () => {
            expect(html).toContain("matchMedia('(pointer: coarse)')");
            expect(html).toContain("'preview'");
            expect(html).toContain("'interactive'");
        });
    });
});
