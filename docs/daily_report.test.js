import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("Daily Report UI", () => {
    let htmlContent;

    beforeAll(() => {
        const htmlPath = join(process.cwd(), "docs", "index.html");
        htmlContent = readFileSync(htmlPath, "utf-8");
    });

    it("renders a dedicated daily report section in charts tab", () => {
        expect(htmlContent).toContain("Daily Summary");
        expect(htmlContent).toContain('id="dailyReportLangEn"');
        expect(htmlContent).toContain('id="dailyReportLangZh"');
        expect(htmlContent).toContain('id="dailyReportItems"');
        expect(htmlContent).toContain('id="dailyReportOverall"');
    });

    it("loads daily report JSON from docs/data", () => {
        expect(htmlContent).toContain("data/daily_report.json?t=${Date.now()}");
        expect(htmlContent).toContain('cache: "no-store"');
        expect(htmlContent).toContain("hour12: false");
        expect(htmlContent).toContain('month: "short"');
        expect(htmlContent).toContain('timeZoneName: "short"');
        expect(htmlContent).toContain("function loadDailyReport()");
        expect(htmlContent).toContain("function setDailyReportLanguage(language)");
        expect(htmlContent).toContain("function getDailySummaryByLanguage(report, language)");
        expect(htmlContent).toContain("loadDailyReport();");
    });

    it("keeps Valuation Ratios and Price Comparison out of summary scope", () => {
        expect(htmlContent).toContain("Valuation Ratios");
        expect(htmlContent).toContain("Price Comparison");
        expect(htmlContent).toContain("Daily Summary");
    });
});
