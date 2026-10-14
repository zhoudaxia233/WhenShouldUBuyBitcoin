// @vitest-environment happy-dom
// The home page polls the BTC price every few seconds and passes it to the
// reserve chart. A new price must update the "now" readout, but must not
// cancel a day the reader is scrubbing to.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadReserveChart() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "reserve_chart.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const PNL = {
    dates: ["2026-01-01T01:10:00", "2026-01-02T01:20:00", "2026-01-09T01:00:00"],
    purchase_btc: [0.1, 0.125, 0.05],
    purchase_usd: [10, 10, 6],
    btc_balance: [0.1, 0.225, 0.275],
    market_dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-08", "2026-01-09", "2026-01-10"],
    market_prices: [100, 80, 90, 110, 120, 125],
    avg_price_timeline: [100, 88.89, 88.89, 88.89, 91.2, 91.2],
};

// A 2D context that accepts every drawing call and does nothing
const noopContext = new Proxy({}, { get: () => () => {}, set: () => true });

let saved;
beforeEach(() => {
    saved = {
        raf: window.requestAnimationFrame,
        caf: window.cancelAnimationFrame,
        getContext: HTMLCanvasElement.prototype.getContext,
    };
    window.requestAnimationFrame = (cb) => { cb(); return 1; };
    window.cancelAnimationFrame = () => {};
    HTMLCanvasElement.prototype.getContext = () => noopContext;
    document.head.innerHTML = "<style>:root { --reserve-price: #e8891c; }</style>";
    document.body.innerHTML = "";
});

afterEach(() => {
    window.requestAnimationFrame = saved.raf;
    window.cancelAnimationFrame = saved.caf;
    HTMLCanvasElement.prototype.getContext = saved.getContext;
});

function mountChart() {
    const root = document.createElement("section");
    root.innerHTML = "<div data-reserve-readout></div><canvas></canvas>";
    document.body.appendChild(root);
    const canvas = root.querySelector("canvas");
    Object.defineProperty(canvas, "clientWidth", { value: 600 });
    Object.defineProperty(canvas, "clientHeight", { value: 300 });
    const chart = loadReserveChart().mount(root);
    return {
        chart,
        readout: () => root.querySelector("[data-reserve-readout]").textContent,
        key: (key) => root.querySelector("canvas").dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true })),
    };
}

describe("reserve chart with a polled price", () => {
    it("shows each new price in the live readout", () => {
        const { chart, readout } = mountChart();
        chart.setData(PNL, { currentBtc: 0.275, currentPrice: 130, currentAvg: 91.2 });
        expect(readout()).toContain("BTC $130");

        chart.setData(PNL, { currentBtc: 0.275, currentPrice: 140, currentAvg: 91.2 });
        expect(readout()).toContain("Bitcoin held");
        expect(readout()).toContain("BTC $140");
    });

    it("keeps the scrubbed day when a new price arrives", () => {
        const { chart, readout, key } = mountChart();
        chart.setData(PNL, { currentBtc: 0.275, currentPrice: 130, currentAvg: 91.2 });
        key("ArrowLeft");
        key("ArrowLeft");
        const scrubbed = readout();
        expect(scrubbed).toContain("Bought by Jan 8, 2026");

        chart.setData(PNL, { currentBtc: 0.275, currentPrice: 140, currentAvg: 91.2 });
        expect(readout()).toBe(scrubbed);

        // The next step continues from the scrubbed day, not from today
        key("ArrowLeft");
        expect(readout()).toContain("Bought by Jan 3, 2026");

        // Letting go shows today with the newest price
        key("Escape");
        expect(readout()).toContain("Bitcoin held");
        expect(readout()).toContain("BTC $140");
    });

    it("still starts over when the purchase history changes", () => {
        const { chart, readout, key } = mountChart();
        chart.setData(PNL, { currentPrice: 130 });
        key("ArrowLeft");
        expect(readout()).toContain("Bought by");

        const withNewBuy = {
            ...PNL,
            dates: [...PNL.dates, "2026-01-10T01:00:00"],
            purchase_btc: [...PNL.purchase_btc, 0.01],
            purchase_usd: [...PNL.purchase_usd, 1.25],
            btc_balance: [...PNL.btc_balance, 0.285],
        };
        chart.setData(withNewBuy, { currentPrice: 130 });
        expect(readout()).toContain("Bitcoin held");
    });
});
