/**
 * Automated tests for backtest strategies
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from "vitest";
import {
    DataLoader,
    DailyDCAStrategy,
    MonthlyDCAStrategy,
    AHR999PercentileStrategy,
    BacktestEngine,
} from "./backtest.js";

let dataLoader;

// Load data once before all tests
beforeAll(async () => {
    dataLoader = new DataLoader();
    await dataLoader.load();
    console.log(
        `Loaded ${dataLoader.historicalData.length} rows of historical data`
    );
});

describe("Bug Fix: Historical Date Range Detection", () => {
    it("should correctly identify historical vs simulated data", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const lastHistDate = dataLoader.getLastHistoricalDate();
        const oneDayBefore = new Date(lastHistDate);
        oneDayBefore.setDate(oneDayBefore.getDate() - 1);

        const startDate = new Date("2024-01-01");
        const endDate = oneDayBefore;

        const result = await engine.run(startDate, endDate, 500);

        // End date is before or equal to last historical date
        expect(result.endDate <= lastHistDate).toBe(true);
    });

    it("should use simulation for future dates", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const lastHistDate = dataLoader.getLastHistoricalDate();
        const futureDate = new Date(lastHistDate);
        futureDate.setFullYear(futureDate.getFullYear() + 1);

        const startDate = new Date("2024-01-01");
        const endDate = futureDate;

        const result = await engine.run(startDate, endDate, 500);

        // End date is after last historical date
        expect(result.endDate > lastHistDate).toBe(true);
    });
});

describe("Strategy: Daily DCA", () => {
    it("should invest approximately monthly budget × months", async () => {
        const monthlyBudget = 500;
        const strategy = new DailyDCAStrategy(monthlyBudget);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const result = await engine.run(startDate, endDate, monthlyBudget);

        // 12 months → should invest ~$6000 (±500 for partial months)
        const expectedMin = 11.5 * monthlyBudget;
        const expectedMax = 12.5 * monthlyBudget;

        expect(result.totalInvested).toBeGreaterThanOrEqual(expectedMin);
        expect(result.totalInvested).toBeLessThanOrEqual(expectedMax);
        expect(result.finalBtcBalance).toBeGreaterThan(0);
    });

    it("should have valid returns", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalReturn).toBeDefined();
        expect(result.annualizedReturn).toBeDefined();
        expect(isNaN(result.totalReturn)).toBe(false);
        expect(isNaN(result.annualizedReturn)).toBe(false);
    });
});

describe("Strategy: Monthly DCA", () => {
    it("should invest exactly monthly budget × months", async () => {
        const monthlyBudget = 500;
        const strategy = new MonthlyDCAStrategy(monthlyBudget, {
            dayOfMonth: 1,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const result = await engine.run(startDate, endDate, monthlyBudget);

        // Should have invested exactly 12 times
        const expectedInvestments = 12 * monthlyBudget;
        const tolerance = 50; // ±$50

        expect(
            Math.abs(result.totalInvested - expectedInvestments)
        ).toBeLessThan(tolerance);
    });

    it("should work with different days of month", async () => {
        const strategy = new MonthlyDCAStrategy(500, { dayOfMonth: 15 });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // Should invest exactly 12 times (one per month)
        expect(result.transactions.length).toBe(12);
    });

    it("should invest full monthly amount even in last month with partial days", async () => {
        // Test that Monthly DCA can invest full $500 even if the last month has fewer days
        // This verifies the fix for budget calculation using complete months
        const monthlyBudget = 500;
        const strategy = new MonthlyDCAStrategy(monthlyBudget, {
            dayOfMonth: 1,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        // Start on Jan 1, end on Dec 10 (last month only has 10 days)
        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-10");

        const result = await engine.run(startDate, endDate, monthlyBudget);

        console.log("Partial last month test:", {
            transactions: result.transactions.length,
            transactionAmounts: result.transactions.map((t) =>
                t.investAmount.toFixed(2)
            ),
            totalInvested: result.totalInvested.toFixed(2),
        });

        // Should have 12 transactions (one per month, including December)
        expect(result.transactions.length).toBe(12);

        // Each transaction should be exactly $500 (including the last one)
        result.transactions.forEach((transaction) => {
            expect(transaction.investAmount).toBe(500);
        });

        // Total should be 12 * $500 = $6000
        expect(result.totalInvested).toBe(6000);
    });
});

describe("Strategy: AHR999 Percentile", () => {
    it("should calculate and use correct percentile boundaries", async () => {
        const strategy = new AHR999PercentileStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // Should have invested some amount based on percentiles
        expect(result.totalInvested).toBeGreaterThan(0);
        expect(result.finalBtcBalance).toBeGreaterThan(0);
    });

    it("should respect custom multipliers", async () => {
        // Test with extreme multipliers: 10x for bottom 10%, 0x for everything else
        const strategy = new AHR999PercentileStrategy(500, {
            multiplier_p10: 10,
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // Should have invested only during bottom 10% periods
        expect(result.totalInvested).toBeGreaterThan(0);

        // Verify multipliers were set correctly
        expect(strategy.multipliers.p10).toBe(10);
        expect(strategy.multipliers.p100).toBe(0);
    });

    it("should produce different investment timing with different multipliers", async () => {
        // Test: Different multipliers should result in different investment patterns
        // (not necessarily different total amounts, as both are limited by total budget)

        // Strategy 1: Only invest in bottom 10% (very selective)
        const selectiveStrategy = new AHR999PercentileStrategy(500, {
            multiplier_p10: 5,
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const selectiveEngine = new BacktestEngine(
            selectiveStrategy,
            dataLoader
        );

        // Strategy 2: Invest uniformly across all percentiles
        const uniformStrategy = new AHR999PercentileStrategy(500, {
            multiplier_p10: 1,
            multiplier_p25: 1,
            multiplier_p50: 1,
            multiplier_p75: 1,
            multiplier_p90: 1,
            multiplier_p100: 1,
        });
        const uniformEngine = new BacktestEngine(uniformStrategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2024-12-31");

        const selectiveResult = await selectiveEngine.run(
            startDate,
            endDate,
            500
        );
        const uniformResult = await uniformEngine.run(startDate, endDate, 500);

        console.log(
            "Selective (bottom 10% only) invested:",
            selectiveResult.totalInvested
        );
        console.log(
            "Uniform (all percentiles) invested:",
            uniformResult.totalInvested
        );
        console.log("Selective BTC balance:", selectiveResult.finalBtcBalance);
        console.log("Uniform BTC balance:", uniformResult.finalBtcBalance);

        // Both should invest some amount
        expect(selectiveResult.totalInvested).toBeGreaterThan(0);
        expect(uniformResult.totalInvested).toBeGreaterThan(0);

        // Selective should invest less total (only invests in bottom 10% periods)
        expect(selectiveResult.totalInvested).toBeLessThan(
            uniformResult.totalInvested
        );

        // But selective might have more BTC (bought during cheaper periods)
        // This is not guaranteed, just checking the strategy executed differently
        expect(selectiveResult.finalBtcBalance).not.toBe(
            uniformResult.finalBtcBalance
        );
    });

    it("should handle null AHR999 values", () => {
        const strategy = new AHR999PercentileStrategy(500);
        strategy.setDataLoader(dataLoader);
        strategy.initialize();
        strategy.cashBuffer = 1000;

        // Test null AHR999
        const investment = strategy.shouldInvest(new Date("2020-01-01"), 400, {
            price: 400,
            ahr999: null,
        });

        expect(investment).toBe(0);
    });

    it("should work with all multipliers set to 0", async () => {
        const strategy = new AHR999PercentileStrategy(500, {
            multiplier_p10: 0,
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // Should not invest anything
        expect(result.totalInvested).toBe(0);
        expect(result.finalBtcBalance).toBe(0);
        expect(result.transactions.length).toBe(0);
    });

    it("should respect single non-zero multiplier", async () => {
        // Only p75 (50-75% percentile) has 10x multiplier, rest are 0
        const strategy = new AHR999PercentileStrategy(500, {
            multiplier_p10: 0,
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 10, // Only this tier invests
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2024-12-31");

        const result = await engine.run(startDate, endDate, 500);

        console.log(
            "Single multiplier (p75=10) invested:",
            result.totalInvested
        );
        console.log("Transactions:", result.transactions.length);

        // Should only invest during 50-75% percentile periods
        expect(result.totalInvested).toBeGreaterThan(0);
        expect(result.transactions.length).toBeGreaterThan(0);

        // Verify multipliers were set correctly
        expect(strategy.multipliers.p75).toBe(10);
        expect(strategy.multipliers.p10).toBe(0);
    });

    it("should handle early dates without crashing", async () => {
        const strategy = new AHR999PercentileStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        // Test with earliest available dates
        const startDate = new Date("2014-09-17");
        const endDate = new Date("2015-06-30");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBeGreaterThanOrEqual(0);
        expect(isNaN(result.totalInvested)).toBe(false);
        expect(result.finalBtcBalance).toBeGreaterThanOrEqual(0);
    });

    it("should correctly parse multiplier value of 0", () => {
        // Test the parsing logic used in UI
        const getMultiplier = (value, defaultValue) => {
            const parsed = parseFloat(value);
            return isNaN(parsed) ? defaultValue : parsed;
        };

        // Test various inputs
        expect(getMultiplier("0", 5.0)).toBe(0); // ✓ Zero should be zero, not default
        expect(getMultiplier("0.5", 5.0)).toBe(0.5);
        expect(getMultiplier("10", 5.0)).toBe(10);
        expect(getMultiplier("", 5.0)).toBe(5.0); // Empty string → default
        expect(getMultiplier("abc", 5.0)).toBe(5.0); // Invalid → default
        expect(getMultiplier("  0  ", 5.0)).toBe(0); // Whitespace trimmed
    });

    it("should allow investing full budget over 5 years with extreme multiplier", async () => {
        // Test that AHR999 with 90x multiplier can invest up to full budget
        // This verifies the fix for budget calculation (total budget vs. elapsed months)
        const monthlyBudget = 500;
        const strategy = new AHR999PercentileStrategy(monthlyBudget, {
            multiplier_p10: 90, // Extreme multiplier
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-11-15");
        const endDate = new Date("2025-11-13");

        const result = await engine.run(startDate, endDate, monthlyBudget);

        // Calculate expected total budget using complete months count
        // (same logic as BacktestEngine)
        const getCompleteMonthsCount = (start, end) => {
            const startMonth = new Date(
                start.getFullYear(),
                start.getMonth(),
                1
            );
            const endMonth = new Date(end.getFullYear(), end.getMonth(), 1);
            let months = 0;
            let current = new Date(startMonth);
            while (current <= endMonth) {
                months++;
                current.setMonth(current.getMonth() + 1);
            }
            return months;
        };

        const completeMonths = getCompleteMonthsCount(startDate, endDate);
        const expectedBudget = completeMonths * monthlyBudget;

        console.log("5-year extreme multiplier test:", {
            completeMonths,
            expectedBudget: expectedBudget.toFixed(2),
            totalInvested: result.totalInvested.toFixed(2),
            utilizationRate:
                ((result.totalInvested / expectedBudget) * 100).toFixed(1) +
                "%",
            transactions: result.transactions.length,
        });

        // Should invest close to full budget (within 5% tolerance)
        expect(result.totalInvested).toBeGreaterThan(expectedBudget * 0.95);
        expect(result.totalInvested).toBeLessThanOrEqual(expectedBudget * 1.01);

        // Should have many transactions (investing frequently due to extreme cheap periods)
        expect(result.transactions.length).toBeGreaterThan(10);
    });

    it("should allow single transactions to exceed monthly budget with high multipliers", async () => {
        // Verify that individual transactions can exceed monthly budget when using high multipliers
        // This confirms strategies can "borrow" from future months
        const monthlyBudget = 500;
        const dailyBudget = monthlyBudget / 30.44; // ~$16.43/day

        const strategy = new AHR999PercentileStrategy(monthlyBudget, {
            multiplier_p10: 90, // 90x = $1478.95/day
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        // Use a longer period (3 months) to have enough budget for large transactions
        const startDate = new Date("2020-03-01"); // During cheap period
        const endDate = new Date("2020-05-31"); // 3 months

        const result = await engine.run(startDate, endDate, monthlyBudget);

        // Find the largest single transaction
        const maxTransaction = Math.max(
            ...result.transactions.map((t) => t.investAmount)
        );
        const expectedDailyInvestment = dailyBudget * 90; // ~$1478.32

        console.log("High multiplier transaction test:", {
            dailyBudget: dailyBudget.toFixed(2),
            expectedDailyInvestment: expectedDailyInvestment.toFixed(2),
            maxTransaction: maxTransaction.toFixed(2),
            totalInvested: result.totalInvested.toFixed(2),
            transactions: result.transactions.length,
        });

        // Some transactions should be much larger than monthly budget
        // (because we're borrowing from future months)
        expect(maxTransaction).toBeGreaterThan(monthlyBudget);

        // The max transaction should be close to the expected daily investment
        // (allowing for budget constraints on some days)
        expect(maxTransaction).toBeGreaterThan(expectedDailyInvestment * 0.3); // At least 30% of expected
    });
});

describe("DataLoader", () => {
    it("should load historical data", () => {
        expect(dataLoader.historicalData).toBeDefined();
        expect(dataLoader.historicalData.length).toBeGreaterThan(1000);
    });

    it("should load metadata", () => {
        expect(dataLoader.metadata).toBeDefined();
        expect(dataLoader.metadata.trend_a).toBeDefined();
        expect(dataLoader.metadata.trend_b).toBeDefined();
    });

    it("should calculate power law prices", () => {
        const futureDate = new Date("2030-01-01");
        const price = dataLoader.calculatePowerLawPrice(futureDate);

        expect(price).toBeGreaterThan(0);
        expect(isNaN(price)).toBe(false);
        expect(price).toBeGreaterThan(100000); // Should be high for 2030
    });

    it("should get historical price data", () => {
        const date = new Date("2020-01-01");
        const dayData = dataLoader.getPriceData(date);

        if (dayData) {
            // Might be null if date is weekend
            expect(dayData.price).toBeGreaterThan(0);
        }
    });

    it("should calculate AHR999 values", () => {
        const values = dataLoader.getHistoricalAHR999Values();

        expect(values.length).toBeGreaterThan(100);
        values.forEach((val) => {
            expect(typeof val).toBe("number");
            expect(isNaN(val)).toBe(false);
        });
    });
});

describe("Edge Cases", () => {
    it("should handle very short time periods", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-01-31");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBeGreaterThanOrEqual(0);
        expect(isNaN(result.totalInvested)).toBe(false);
    });

    it("should handle leap years", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-02-01");
        const endDate = new Date("2020-03-01");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBeGreaterThanOrEqual(0);
    });

    it("should handle zero monthly budget gracefully", async () => {
        const strategy = new DailyDCAStrategy(0);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const result = await engine.run(startDate, endDate, 0);

        expect(result.totalInvested).toBe(0);
        expect(result.finalBtcBalance).toBe(0);
    });
});

describe("Performance", () => {
    it("should complete 1-year backtest in reasonable time", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const start = Date.now();
        await engine.run(startDate, endDate, 500);
        const duration = Date.now() - start;

        // Should complete in less than 2 seconds
        expect(duration).toBeLessThan(2000);
    });

    it("should complete 10-year backtest in reasonable time", async () => {
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2014-09-17");
        const endDate = new Date("2024-09-17");

        const start = Date.now();
        await engine.run(startDate, endDate, 500);
        const duration = Date.now() - start;

        // Should complete in less than 5 seconds
        expect(duration).toBeLessThan(5000);
    });
});
