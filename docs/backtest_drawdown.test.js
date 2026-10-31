/**
 * The largest fall of the investor's wealth during a backtest: BTC at that
 * day's price plus budget not spent yet, the same money as Final Wealth.
 */

import { describe, it, expect } from "vitest";
import {
    BacktestEngine,
    Strategy,
    maxDrawdownCard,
    rollingWindows,
} from "./backtest.js";

const DAY = 864e5;
const START = Date.UTC(2020, 0, 10);

class BuyOnFirstDay extends Strategy {
    getName() {
        return "Buy on the first day";
    }

    initialize() {
        super.initialize();
        this.bought = false;
    }

    shouldInvest() {
        if (this.bought) return 0;
        this.bought = true;
        return this.config.amount;
    }
}

function backtest(prices, amount) {
    const loader = {
        getPriceData: (date) => {
            const price = prices[Math.round((date.getTime() - START) / DAY)];
            return price ? { price } : null;
        },
    };
    const engine = new BacktestEngine(new BuyOnFirstDay(500, { amount }), loader);
    return engine.run(new Date(START), new Date(START + (prices.length - 1) * DAY), 500);
}

describe("max drawdown", () => {
    it("is the fall from the highest wealth to the lowest after it", async () => {
        const { maxDrawdown } = await backtest([100, 200, 150, 50, 120], 500);

        expect(maxDrawdown.percent).toBeCloseTo(-75);
        expect(maxDrawdown.peak).toBeCloseTo(1000);
        expect(maxDrawdown.trough).toBeCloseTo(250);
        expect(maxDrawdown.peakDate).toEqual(new Date(START + DAY));
        expect(maxDrawdown.troughDate).toEqual(new Date(START + 3 * DAY));
    });

    it("counts unspent budget at face value, like Final Wealth", async () => {
        const { maxDrawdown } = await backtest([100, 200, 150, 50, 120], 250);

        expect(maxDrawdown.peak).toBeCloseTo(750);
        expect(maxDrawdown.trough).toBeCloseTo(375);
        expect(maxDrawdown.percent).toBeCloseTo(-50);
    });

    it("ignores an earlier, smaller fall", async () => {
        const { maxDrawdown } = await backtest([100, 80, 300, 150], 500);

        expect(maxDrawdown.percent).toBeCloseTo(-50);
        expect(maxDrawdown.peakDate).toEqual(new Date(START + 2 * DAY));
    });

    it("is empty when wealth never fell", async () => {
        const { maxDrawdown } = await backtest([100, 110, 120], 500);

        expect(maxDrawdown).toBeNull();
    });
});

describe("maxDrawdownCard", () => {
    it("shows the fall with the amounts and dates behind it", () => {
        const html = maxDrawdownCard({
            maxDrawdown: {
                percent: -75,
                peak: 1000,
                trough: 250,
                peakDate: new Date("2020-01-11"),
                troughDate: new Date("2020-01-13"),
            },
        });

        expect(html).toContain("Max Drawdown");
        expect(html).toContain("−75.0%");
        expect(html).toContain("$1,000");
        expect(html).toContain("$250");
        expect(html).toContain(new Date("2020-01-11").toLocaleDateString());
        expect(html).toContain(new Date("2020-01-13").toLocaleDateString());
        expect(html).toContain("Deposits made during the fall are included");
    });

    it("says so when wealth never fell", () => {
        const html = maxDrawdownCard({ maxDrawdown: null });

        expect(html).toContain("None");
        expect(html).not.toContain("NaN");
    });
});

describe("rollingWindows", () => {
    const start = new Date("2017-09-14");

    it("keeps only windows that end inside the data", () => {
        const windows = rollingWindows(start, new Date("2019-01-01"), 365, 182);

        expect(windows).toEqual([{ start, end: new Date("2018-09-13") }]);
    });

    it("starts a new window every step", () => {
        const windows = rollingWindows(start, new Date("2019-03-14"), 365, 182);

        expect(windows.map((w) => w.start)).toEqual([start, new Date("2018-03-15")]);
    });
});
