#!/usr/bin/env node
/**
 * The site's backtest engine over rolling 4-year windows, for the findings
 * card on the Backtest view ($500 a month).
 *
 * Usage (from the repository root, with docs/data present):
 *     node scripts/backtest_rolling_windows.mjs
 */

import {
    AHR999PercentileStrategy,
    BacktestEngine,
    DailyDCAStrategy,
    DataLoader,
    rollingWindows,
} from "../docs/backtest.js";

const MONTHLY_BUDGET = 500;
const FIRST_START = new Date("2017-09-14"); // First day the ahr999 tiers apply

const loader = new DataLoader();
await loader.load();

async function wealth(strategy, { start, end }) {
    const engine = new BacktestEngine(strategy, loader);
    return (await engine.run(start, end, MONTHLY_BUDGET)).totalWealth;
}

function gain(value, plain) {
    return ((value / plain - 1) * 100).toFixed(1);
}

function summary(label, gains) {
    const sorted = [...gains].map(Number).sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    const wins = sorted.filter((value) => value > 0).length;
    console.log(
        `${label}: beat plain DCA in ${wins} of ${sorted.length}, ` +
            `median ${median}%, from ${sorted[0]}% to ${sorted.at(-1)}%`
    );
}

const saved = [];
const limited = [];
for (const window of rollingWindows(FIRST_START, loader.getLastHistoricalDate())) {
    const plain = await wealth(new DailyDCAStrategy(MONTHLY_BUDGET), window);
    const tilts = [true, false].map((unlimitedBudget) =>
        wealth(new AHR999PercentileStrategy(MONTHLY_BUDGET, { unlimitedBudget }), window)
    );
    const [savedWealth, limitedWealth] = await Promise.all(tilts);
    saved.push(gain(savedWealth, plain));
    limited.push(gain(limitedWealth, plain));
    console.log(
        window.start.toISOString().slice(0, 10),
        `saved ${saved.at(-1)}%`,
        `monthly limit ${limited.at(-1)}%`
    );
}

summary("Unspent money saved for later", saved);
summary("Monthly limit", limited);
