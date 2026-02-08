/**
 * Tests for chart navigation information architecture.
 * Ensures Core/Advanced grouping and chart source wiring remain stable.
 */

import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("Chart Navigation Architecture", () => {
    let htmlContent;

    beforeAll(() => {
        const htmlPath = join(process.cwd(), "docs", "index.html");
        htmlContent = readFileSync(htmlPath, "utf-8");
    });

    it("should have Core and Advanced section tabs", () => {
        expect(htmlContent).toContain("switchChartSection('core'");
        expect(htmlContent).toContain("switchChartSection('advanced'");
    });

    it("should group chart tabs by section using data-section", () => {
        expect(htmlContent).toContain('data-section="core"');
        expect(htmlContent).toContain('data-section="advanced"');
    });

    it("should include USD/JPY risk map iframe and not legacy usdjpy iframe", () => {
        expect(htmlContent).toContain('src="charts/usdjpy_risk_map.html"');
        expect(htmlContent).not.toContain('src="charts/usdjpy.html"');
    });

    it("should include robust chart navigation helpers", () => {
        expect(htmlContent).toContain("function setActiveChart(");
        expect(htmlContent).toContain("function switchChartSection(");
        expect(htmlContent).toContain("function loadChartIframes(");
        expect(htmlContent).toContain("dataset.chart");
    });

    it("should lazy-load chart iframes via data-src", () => {
        expect(htmlContent).toContain('class="chart-iframe"');
        expect(htmlContent).toContain('data-src="charts/valuation_ratios.html"');
        expect(htmlContent).toContain("loadChartIframes(initialChart)");
    });
});
