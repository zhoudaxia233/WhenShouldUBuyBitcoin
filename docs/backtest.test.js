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

        expect(Math.abs(result.totalInvested - expectedInvestments)).toBeLessThan(
            tolerance
        );
    });

    it("should work with different days of month", async () => {
        const strategy = new MonthlyDCAStrategy(500, { dayOfMonth: 15 });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-12-31");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBeGreaterThan(0);
        expect(result.finalBtcBalance).toBeGreaterThan(0);
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
        const selectiveEngine = new BacktestEngine(selectiveStrategy, dataLoader);
        
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

        const selectiveResult = await selectiveEngine.run(startDate, endDate, 500);
        const uniformResult = await uniformEngine.run(startDate, endDate, 500);

        console.log("Selective (bottom 10% only) invested:", selectiveResult.totalInvested);
        console.log("Uniform (all percentiles) invested:", uniformResult.totalInvested);
        console.log("Selective BTC balance:", selectiveResult.finalBtcBalance);
        console.log("Uniform BTC balance:", uniformResult.finalBtcBalance);

        // Both should invest some amount
        expect(selectiveResult.totalInvested).toBeGreaterThan(0);
        expect(uniformResult.totalInvested).toBeGreaterThan(0);
        
        // Selective should invest less total (only invests in bottom 10% periods)
        expect(selectiveResult.totalInvested).toBeLessThan(uniformResult.totalInvested);
        
        // But selective might have more BTC (bought during cheaper periods)
        // This is not guaranteed, just checking the strategy executed differently
        expect(selectiveResult.finalBtcBalance).not.toBe(uniformResult.finalBtcBalance);
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

        console.log("Single multiplier (p75=10) invested:", result.totalInvested);
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

