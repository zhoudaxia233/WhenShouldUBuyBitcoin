/**
 * The Today view checks the price on load and on Refresh. Coming back to the
 * tab after a while checks again, so the price shown is not left hours old.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { join } from "path";
import { Window } from "happy-dom";

const source = readFileSync(join(process.cwd(), "docs", "realtime.js"), "utf-8");

afterEach(() => {
    vi.restoreAllMocks();
});

// Runs realtime.js in a fresh window. `respond` decides what each fetch does;
// every fetch of the price history counts as one check.
function openPage({ respond = () => Promise.reject(new Error("offline")) } = {}) {
    const win = new Window();
    const doc = win.document;
    doc.body.innerHTML = '<div id="results"></div><button id="todayRefresh">Refresh</button>';
    let visibility = "visible";
    Object.defineProperty(doc, "visibilityState", { configurable: true, get: () => visibility });

    const checks = [];
    const fetch = (url) => {
        if (String(url).startsWith("data/btc_metrics.csv")) checks.push(url);
        return respond(url);
    };
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    new Function("window", "document", "fetch", source)(win, doc, fetch);
    doc.dispatchEvent(new win.Event("DOMContentLoaded"));

    return {
        checks,
        leave() {
            visibility = "hidden";
            doc.dispatchEvent(new win.Event("visibilitychange"));
        },
        comeBack() {
            visibility = "visible";
            doc.dispatchEvent(new win.Event("visibilitychange"));
        },
    };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function clockAt(start) {
    let now = start;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    return (ms) => { now += ms; };
}

describe("Today view: check again on return to the tab", () => {
    it("checks again when the last check is over a minute old", async () => {
        const advance = clockAt(1_000_000);
        const page = openPage();
        await settle();
        expect(page.checks).toHaveLength(1);

        page.leave();
        advance(61_000);
        page.comeBack();
        await settle();

        expect(page.checks).toHaveLength(2);
    });

    it("keeps the result when coming back within a minute", async () => {
        const advance = clockAt(1_000_000);
        const page = openPage();
        await settle();

        page.leave();
        advance(30_000);
        page.comeBack();
        await settle();

        expect(page.checks).toHaveLength(1);
    });

    it("does nothing when the tab is hidden", async () => {
        const advance = clockAt(1_000_000);
        const page = openPage();
        await settle();

        advance(61_000);
        page.leave();
        await settle();

        expect(page.checks).toHaveLength(1);
    });

    it("does not start a second check while one is still loading", async () => {
        const advance = clockAt(1_000_000);
        const page = openPage({ respond: () => new Promise(() => {}) });
        await settle();

        page.leave();
        advance(61_000);
        page.comeBack();
        await settle();

        expect(page.checks).toHaveLength(1);
    });
});
