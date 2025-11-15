/**
 * Automated tests for backtest strategies
 * Run with: npm test
 */

import { describe, it, expect, beforeAll } from "vitest";
import {
    DataLoader,
    DailyDCAStrategy,
    MonthlyDCAStrategy,
    AHR999ThresholdStrategy,
    ValuationAwareDCAStrategy,
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

describe("Bug Fix: AHR999 Threshold = 0", () => {
    it("should not invest when threshold is 0", async () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 0 });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBe(0);
        expect(result.finalBtcBalance).toBe(0);
    });

    it("should correctly set threshold to 0 (not default to 0.45)", () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 0 });
        expect(strategy.threshold).toBe(0);
        expect(strategy.threshold).not.toBe(0.45);
    });

    it("should handle threshold parsing from string '0' (UI simulation)", () => {
        // Simulate UI input: parseFloat("0") should return 0, not default to 0.45
        const thresholdInput = "0";
        const threshold = thresholdInput !== "" && !isNaN(parseFloat(thresholdInput))
            ? parseFloat(thresholdInput)
            : 0.45;
        
        expect(threshold).toBe(0);
        expect(threshold).not.toBe(0.45);
        
        // Verify strategy works with this threshold
        const strategy = new AHR999ThresholdStrategy(500, { threshold });
        expect(strategy.threshold).toBe(0);
    });

    it("should handle null AHR999 values", () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 0.45 });
        strategy.setDataLoader(dataLoader);
        strategy.initialize();
        strategy.cashBuffer = 1000; // Add cash for testing

        // Test null
        const investment1 = strategy.shouldInvest(new Date("2020-01-01"), 400, {
            price: 400,
            ahr999: null,
        });
        expect(investment1).toBe(0);

        // Test undefined
        const investment2 = strategy.shouldInvest(new Date("2020-01-01"), 400, {
            price: 400,
            ahr999: undefined,
        });
        expect(investment2).toBe(0);

        // Test NaN
        const investment3 = strategy.shouldInvest(new Date("2020-01-01"), 400, {
            price: 400,
            ahr999: NaN,
        });
        expect(investment3).toBe(0);
    });
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

describe("Strategy: AHR999 Threshold", () => {
    it("should invest when AHR999 < threshold", async () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 10 }); // Very high threshold
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // With very high threshold, should invest frequently
        expect(result.totalInvested).toBeGreaterThan(500 * 20); // At least 20 months worth
    });

    it("should not invest when AHR999 > threshold", async () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 0.01 }); // Very low threshold
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // With very low threshold, should rarely invest
        expect(result.totalInvested).toBeLessThan(500 * 24); // Less than full period
    });

    it("should accumulate cash when not investing", async () => {
        const strategy = new AHR999ThresholdStrategy(500, { threshold: 0.01 });
        strategy.setDataLoader(dataLoader);
        strategy.initialize();

        // Simulate months passing
        strategy.onMonthStart(new Date("2020-01-01"));
        strategy.onMonthStart(new Date("2020-02-01"));
        strategy.onMonthStart(new Date("2020-03-01"));

        // Should have accumulated 3 months of budget
        expect(strategy.cashBuffer).toBe(1500);
    });
});

describe("Strategy: Valuation-Aware DCA", () => {
    it("should handle early dates without crashing", async () => {
        const strategy = new ValuationAwareDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        // Test with earliest available dates
        const startDate = new Date("2014-09-17");
        const endDate = new Date("2015-06-30");

        const result = await engine.run(startDate, endDate, 500);

        expect(result.totalInvested).toBeGreaterThanOrEqual(0);
        expect(isNaN(result.totalInvested)).toBe(false);
        expect(result.finalBtcBalance).toBeGreaterThanOrEqual(0);
    });

    it("should invest variable amounts based on AHR999", async () => {
        const strategy = new ValuationAwareDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-12-31");

        const result = await engine.run(startDate, endDate, 500);

        // Should have invested some amount
        expect(result.totalInvested).toBeGreaterThan(0);
        expect(result.finalBtcBalance).toBeGreaterThan(0);
    });

    it("should handle null AHR999 in valuation-aware", () => {
        const strategy = new ValuationAwareDCAStrategy(500);
        strategy.setDataLoader(dataLoader);
        strategy.initialize();
        strategy.cashBuffer = 1000;

        const investment = strategy.shouldInvest(new Date("2020-01-01"), 400, {
            price: 400,
            ahr999: null,
        });

        expect(investment).toBe(0);
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

