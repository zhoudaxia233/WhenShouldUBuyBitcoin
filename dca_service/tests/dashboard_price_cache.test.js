// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const dashboardHtml = readFileSync(
    join(
        process.cwd(),
        "dca_service",
        "src",
        "dca_service",
        "templates",
        "index.html",
    ),
    "utf8",
);

function dashboardCacheHydrationScript() {
    const marker = "Hydrate wallet and DCA preview from cache";
    const start = dashboardHtml.indexOf("(function () {", dashboardHtml.indexOf(marker));
    const end = dashboardHtml.indexOf("})();", start);

    return dashboardHtml.slice(start, end + 5);
}

function dashboardLoadPreviewFunction() {
    const start = dashboardHtml.indexOf("async function loadPreview()");
    const end = dashboardHtml.indexOf("// Helper to update global refresh timestamp", start);

    return dashboardHtml.slice(start, end);
}

function dashboardInitializeFunction() {
    const start = dashboardHtml.indexOf("async function initializeDashboard()");
    const end = dashboardHtml.indexOf("// Load on start", start);

    return dashboardHtml.slice(start, end);
}

describe("dashboard preview cache hydration", () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <div id="previewPrice">--</div>
            <div id="remainingBudget">--</div>
        `;
        localStorage.clear();
    });

    it("restores cached preview context without showing its stale BTC price", () => {
        localStorage.setItem(
            "dca_preview",
            JSON.stringify({
                timestamp: Date.now() - 60_000,
                data: {
                    price_usd: 64_762.98,
                    remaining_budget: 305,
                },
            }),
        );

        new Function(
            "window",
            "document",
            "localStorage",
            dashboardCacheHydrationScript(),
        )(window, document, localStorage);

        expect(document.getElementById("remainingBudget").textContent).toBe("$305.00");
        expect(document.getElementById("previewPrice").textContent).toBe("--");
    });

    it("keeps the price placeholder while a fresh preview is pending", async () => {
        let resolvePreviewResponse;
        let markPreviewRequested;
        const previewRequested = new Promise((resolve) => {
            markPreviewRequested = resolve;
        });
        const previewResponse = new Promise((resolve) => {
            resolvePreviewResponse = resolve;
        });
        const stalePreview = { price_usd: 64_762.98 };
        const freshPreview = { price_usd: 64_172.35 };
        const updatePreviewUI = vi.fn((decision) => {
            document.getElementById("previewPrice").textContent = `$${decision.price_usd.toLocaleString()}`;
        });
        const fetch = vi.fn(async (url) => {
            if (url === "/api/strategy") {
                return { json: async () => ({}) };
            }
            markPreviewRequested();
            return previewResponse;
        });
        const runLoadPreview = new Function(
            "loadFromCache",
            "updateStrategyUI",
            "fetch",
            "saveToCache",
            "updatePreviewUI",
            "document",
            "notyf",
            `${dashboardLoadPreviewFunction()}; return loadPreview();`,
        );

        const loading = runLoadPreview(
            (key) => (key === "dca_preview" ? stalePreview : null),
            () => {},
            fetch,
            () => {},
            updatePreviewUI,
            document,
            { error: () => {} },
        );
        await previewRequested;

        expect(document.getElementById("previewPrice").textContent).toBe("--");

        resolvePreviewResponse({ json: async () => freshPreview });
        await loading;

        expect(document.getElementById("previewPrice").textContent).toBe("$64,172.35");
        expect(updatePreviewUI).toHaveBeenCalledTimes(1);
    });

    it("requests fresh preview and wallet data without waiting for transactions", async () => {
        const calls = [];
        let markTransactionsStarted;
        let resolveTransactions;
        const transactionsStarted = new Promise((resolve) => {
            markTransactionsStarted = resolve;
        });
        const transactionsFinished = new Promise((resolve) => {
            resolveTransactions = resolve;
        });
        const runInitializeDashboard = new Function(
            "applyRefreshFlag",
            "loadExecutionMode",
            "loadTransactions",
            "loadPreview",
            "loadWalletSummary",
            "fetchRealtimePriceForDashboard",
            "startDashboardPricePolling",
            "connectSSE",
            `${dashboardInitializeFunction()}; return initializeDashboard();`,
        );
        const loading = runInitializeDashboard(
            () => calls.push("refresh-flag"),
            async () => calls.push("execution-mode"),
            async () => {
                calls.push("transactions");
                markTransactionsStarted();
                await transactionsFinished;
            },
            async () => calls.push("preview"),
            async () => calls.push("wallet"),
            async () => calls.push("realtime-price"),
            () => calls.push("polling"),
            () => calls.push("sse"),
        );
        await transactionsStarted;

        expect(calls).toContain("preview");
        expect(calls).toContain("wallet");

        resolveTransactions();
        await loading;
    });
});
