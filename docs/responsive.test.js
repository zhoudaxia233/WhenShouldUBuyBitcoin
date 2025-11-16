/**
 * Basic tests for responsive layout
 * Ensures mobile-friendly styles are not broken
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";

describe("Responsive Layout Tests", () => {
    let htmlContent;
    let cssContent;

    beforeAll(() => {
        const htmlPath = join(process.cwd(), "docs", "index.html");
        htmlContent = readFileSync(htmlPath, "utf-8");
        // Extract CSS from style tag
        const styleMatch = htmlContent.match(/<style>([\s\S]*?)<\/style>/);
        cssContent = styleMatch ? styleMatch[1] : "";
    });

    it("should have mobile media query for small screens", () => {
        expect(cssContent).toContain("@media");
        expect(cssContent).toContain("max-width");
        // Check for common mobile breakpoints
        const hasMobileQuery =
            cssContent.includes("max-width: 768px") ||
            cssContent.includes("max-width: 768") ||
            cssContent.includes("@media (max-width");
        expect(hasMobileQuery).toBe(true);
    });

    it("should have box-sizing border-box for metric cards", () => {
        expect(cssContent).toContain(".metric-card");
        expect(cssContent).toContain("box-sizing: border-box");
    });

    it("should have word-wrap for metric cards to prevent overflow", () => {
        expect(cssContent).toContain("word-wrap");
        expect(cssContent).toContain("overflow-wrap");
    });

    it("should reset grid-column for metric cards on mobile", () => {
        expect(cssContent).toContain('metric-card[style*="grid-column"]');
        expect(cssContent).toContain("grid-column: 1 !important");
    });

    it("should have width 100% for form inputs on mobile", () => {
        expect(cssContent).toContain('input[type="date"]');
        expect(cssContent).toContain("width: 100%");
    });

    it("should have box-sizing for form inputs", () => {
        expect(cssContent).toContain(".form-group input");
        expect(cssContent).toContain("box-sizing: border-box");
    });

    it("should have overflow-x hidden for result section", () => {
        expect(cssContent).toContain(".result-section");
        expect(cssContent).toContain("overflow-x: hidden");
    });

    it("should have max-width 100% for metric cards on mobile", () => {
        expect(cssContent).toContain("max-width: 100%");
    });
});

