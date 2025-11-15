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

    it("should use default multipliers when undefined is passed", async () => {
        // Test that strategy uses centralized AHR999_DEFAULT_MULTIPLIERS when config is empty
        const strategy = new AHR999PercentileStrategy(500, {
            // Pass undefined for all multipliers - should use defaults
        });

        // Verify defaults are applied (from AHR999_DEFAULT_MULTIPLIERS)
        expect(strategy.multipliers.p10).toBe(5.0);
        expect(strategy.multipliers.p25).toBe(2.0);
        expect(strategy.multipliers.p50).toBe(1.0);
        expect(strategy.multipliers.p75).toBe(0);
        expect(strategy.multipliers.p90).toBe(0);
        expect(strategy.multipliers.p100).toBe(0);
    });

    it("should work with unlimited budget mode", async () => {
        // Test that unlimited budget mode allows investing beyond total budget constraint
        const monthlyBudget = 500;
        const strategy = new AHR999PercentileStrategy(monthlyBudget, {
            multiplier_p10: 100, // Extremely high multiplier
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
            unlimitedBudget: true, // Enable unlimited budget mode
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-03-01");
        const endDate = new Date("2020-03-31"); // Only 1 month

        const result = await engine.run(startDate, endDate, monthlyBudget);

        console.log("Unlimited budget test:", {
            monthlyBudget,
            expectedLimitedBudget: monthlyBudget, // Should be limited to $500 if not unlimited
            totalInvested: result.totalInvested.toFixed(2),
            transactions: result.transactions.length,
        });

        // With unlimited budget, should be able to invest more than $500 in a single month
        expect(result.totalInvested).toBeGreaterThan(monthlyBudget);

        // Verify unlimited budget flag is set
        expect(strategy.unlimitedBudget).toBe(true);
    });

    it("should respect budget constraint when unlimited mode is disabled", async () => {
        // Test that budget constraint is enforced when unlimited budget is false
        const monthlyBudget = 500;
        const strategy = new AHR999PercentileStrategy(monthlyBudget, {
            multiplier_p10: 100, // Extremely high multiplier
            multiplier_p25: 0,
            multiplier_p50: 0,
            multiplier_p75: 0,
            multiplier_p90: 0,
            multiplier_p100: 0,
            unlimitedBudget: false, // Disable unlimited budget mode (default)
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-03-01");
        const endDate = new Date("2020-03-31"); // Only 1 month

        const result = await engine.run(startDate, endDate, monthlyBudget);

        console.log("Limited budget test:", {
            monthlyBudget,
            totalInvested: result.totalInvested.toFixed(2),
            transactions: result.transactions.length,
        });

        // Calculate expected max budget (1+ months worth)
        const daysInPeriod =
            Math.floor((endDate - startDate) / (1000 * 60 * 60 * 24)) + 1;
        const monthsInPeriod = daysInPeriod / 30.44;
        const maxBudget = monthsInPeriod * monthlyBudget;

        // Should not exceed the calculated total budget
        expect(result.totalInvested).toBeLessThanOrEqual(maxBudget * 1.01); // Allow 1% tolerance

        // Verify unlimited budget flag is false
        expect(strategy.unlimitedBudget).toBe(false);
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

describe("Return Calculation Edge Cases", () => {
    it("should show N/A for annualized return when period is less than 1 year", async () => {
        // Test that backtests less than 1 year show N/A for annualized return
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        // Short period: 6 months
        const startDate = new Date("2020-01-01");
        const endDate = new Date("2020-07-01"); // ~6 months

        const result = await engine.run(startDate, endDate, 500);

        console.log("Less than 1 year backtest:", {
            durationDays: result.durationDays,
            totalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
            annualizedReturn: result.annualizedReturn,
            isFinite: isFinite(result.annualizedReturn),
        });

        // Annualized return should be Infinity (marker for N/A) when period < 365 days
        expect(result.durationDays).toBeLessThan(365);
        expect(result.annualizedReturn).toBe(Infinity);
        expect(isFinite(result.annualizedReturn)).toBe(false);
    });

    it("should calculate annualized return when period is 1 year or more", async () => {
        // Test that backtests of 1 year or more calculate annualized return
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        // Exactly 1 year
        const startDate = new Date("2020-01-01");
        const endDate = new Date("2021-01-01"); // Exactly 1 year

        const result = await engine.run(startDate, endDate, 500);

        console.log("1 year backtest:", {
            durationDays: result.durationDays,
            totalReturn: result.totalReturn.toFixed(2),
            annualizedReturn: result.annualizedReturn,
            isFinite: isFinite(result.annualizedReturn),
        });

        // Annualized return should be calculated (finite) when period >= 365 days
        expect(result.durationDays).toBeGreaterThanOrEqual(365);
        expect(isFinite(result.annualizedReturn)).toBe(true);
        expect(Math.abs(result.annualizedReturn)).toBeLessThan(1000000);
    });

    it("should handle high return ratio without overflow", async () => {
        // Test that high return ratios don't cause overflow in annualized calculation
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        // Use a period where Bitcoin had significant gains
        const startDate = new Date("2020-03-01"); // COVID crash
        const endDate = new Date("2021-03-01"); // 1 year later (significant gains)

        const result = await engine.run(startDate, endDate, 500);

        console.log("High return backtest:", {
            durationDays: result.durationDays,
            totalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
            annualizedReturn: result.annualizedReturn,
            isFinite: isFinite(result.annualizedReturn),
        });

        // Annualized return should be finite
        expect(isFinite(result.annualizedReturn)).toBe(true);
        expect(Math.abs(result.annualizedReturn)).toBeLessThan(1000000);
    });

    it("should handle zero investment gracefully", async () => {
        // Test that zero investment doesn't cause division by zero
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
        const endDate = new Date("2020-12-31"); // 364 days (less than 1 year)

        const result = await engine.run(startDate, endDate, 500);

        // Should handle zero investment without errors
        expect(result.totalInvested).toBe(0);
        // When totalInvested is 0, annualizedReturn should be 0 (not calculated)
        // But if period < 365 days, it would be Infinity
        // Since totalInvested is 0, the calculation is skipped, so annualizedReturn should be 0
        expect(result.annualizedReturn).toBe(0);
    });

    it("should calculate annualized return correctly for multi-year periods", async () => {
        // Test that annualized return calculation is correct for 2-year period
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2020-01-01");
        const endDate = new Date("2022-01-01"); // Exactly 2 years

        const result = await engine.run(startDate, endDate, 500);

        console.log("2-year backtest:", {
            durationDays: result.durationDays,
            totalReturn: result.totalReturn.toFixed(2),
            annualizedReturn: result.annualizedReturn.toFixed(2),
        });

        // For 2 years, annualized return should be calculated and reasonable
        expect(result.durationDays).toBeGreaterThanOrEqual(365);
        expect(isFinite(result.annualizedReturn)).toBe(true);
        expect(Math.abs(result.annualizedReturn)).toBeLessThan(1000000);

        // Annualized return should be less than total return for multi-year periods
        // (because it's the geometric mean, not linear)
        expect(Math.abs(result.annualizedReturn)).toBeLessThan(
            Math.abs(result.totalReturn)
        );
    });
});

describe("Daily DCA Budget Calculation Fix", () => {
    it("should calculate budget correctly for partial month (13 days)", async () => {
        // Test case: Nov 1 to Nov 13, 2025 (13 days)
        // Monthly budget: $500
        // Expected daily amount: $500 / 30.44 ≈ $16.43
        // Expected total budget: 13 days × $16.43 ≈ $213.59
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-11-01");
        const endDate = new Date("2025-11-13"); // 13 days

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected values
        const expectedDailyAmount = 500 / 30.44; // BACKTEST_CONFIG.DAYS_PER_MONTH
        const expectedTotalBudget = 13 * expectedDailyAmount; // 13 days

        console.log("Partial month test:", {
            durationDays: result.durationDays,
            expectedTotalBudget: expectedTotalBudget.toFixed(2),
            actualTotalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
        });

        // Total invested should be close to expected budget (within 1% tolerance)
        // Note: May be slightly less if some days don't have price data
        expect(result.totalInvested).toBeGreaterThan(
            expectedTotalBudget * 0.95
        );
        expect(result.totalInvested).toBeLessThanOrEqual(
            expectedTotalBudget * 1.01
        );

        // Final portfolio value should be: cashBalance + btcBalance * finalPrice
        // Cash balance should be close to 0 (all budget invested)
        // So finalPortfolioValue should be approximately: btcBalance * finalPrice
        // And totalReturn should be: (finalPortfolioValue - totalInvested) / totalInvested
        expect(result.finalPortfolioValue).toBeGreaterThan(0);
        expect(isFinite(result.totalReturn)).toBe(true);

        // Verify that finalPortfolioValue calculation is correct
        // It should not include excess cashBalance from full month budget
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0) {
            // Calculate expected BTC balance
            const expectedBtcBalance = result.totalInvested / finalPrice; // Rough estimate
            // Final portfolio value should be reasonable (not inflated by excess cash)
            // It should be close to: btcBalance * finalPrice (if cashBalance is near 0)
            expect(result.finalPortfolioValue).toBeLessThan(
                result.totalInvested * 5
            ); // Sanity check
        }
    });

    it("should not include excess cashBalance in finalPortfolioValue for partial month", async () => {
        // This test ensures that for Daily DCA with partial month,
        // the cashBalance is proportional to days, not full month budget
        const strategy = new DailyDCAStrategy(500);
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-11-01");
        const endDate = new Date("2025-11-13"); // 13 days

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected proportional budget
        const expectedDailyAmount = 500 / 30.44;
        const expectedTotalBudget = 13 * expectedDailyAmount;

        // Final portfolio value should be calculated as: cashBalance + btcBalance * finalPrice
        // If cashBalance was incorrectly set to full month ($500), then:
        // cashBalance = $500 - $213.53 = $286.47 (excess)
        // finalPortfolioValue would be inflated by this excess

        // With the fix, cashBalance should be proportional:
        // cashBalance ≈ expectedTotalBudget - totalInvested ≈ 0 (if all invested)

        // Verify finalPortfolioValue is reasonable
        // It should not be significantly higher than totalInvested unless BTC price increased
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0 && result.totalInvested > 0) {
            // Calculate implied cashBalance from finalPortfolioValue
            // finalPortfolioValue = cashBalance + btcBalance * finalPrice
            // btcBalance = totalInvested / averagePrice (roughly)
            // If cashBalance was excess, finalPortfolioValue would be too high

            // The return should be based on BTC price movement, not excess cash
            // If BTC price didn't change much, return should be close to 0%
            // If BTC price doubled, return should be around 100%
            // But it shouldn't be inflated by excess cashBalance

            // Sanity check: finalPortfolioValue should be at least totalInvested
            // (unless BTC price dropped significantly)
            expect(result.finalPortfolioValue).toBeGreaterThan(
                result.totalInvested * 0.5
            );

            // If return is very high (>200%), it might indicate excess cashBalance issue
            // But we can't be too strict here as BTC price might have actually increased
            // Instead, we verify that totalInvested matches expected budget
            expect(result.totalInvested).toBeCloseTo(expectedTotalBudget, 1);
        }
    });

    it("should calculate budget correctly for AHR999 strategy with partial month (13 days)", async () => {
        // Test case: Nov 1 to Nov 13, 2025 (13 days)
        // Monthly budget: $500
        // Expected daily amount: $500 / 30.44 ≈ $16.43
        // Expected total budget: 13 days × $16.43 ≈ $213.59
        // AHR999 strategy (non-unlimited) should use days-based calculation like Daily DCA
        const strategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: false, // Explicitly disable unlimited budget
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-11-01");
        const endDate = new Date("2025-11-13"); // 13 days

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected values
        const expectedDailyAmount = 500 / 30.44; // BACKTEST_CONFIG.DAYS_PER_MONTH
        const expectedTotalBudget = 13 * expectedDailyAmount; // 13 days

        console.log("AHR999 Partial month test:", {
            durationDays: result.durationDays,
            expectedTotalBudget: expectedTotalBudget.toFixed(2),
            actualTotalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
        });

        // Total invested should be close to expected budget (within reasonable tolerance)
        // Note: AHR999 may invest less if multipliers are 0 for some days
        // But the budget constraint should still be based on days, not full month
        expect(result.totalInvested).toBeLessThanOrEqual(
            expectedTotalBudget * 1.01
        );

        // Final portfolio value should be reasonable (not inflated by excess cashBalance)
        expect(result.finalPortfolioValue).toBeGreaterThan(0);
        expect(isFinite(result.totalReturn)).toBe(true);

        // Verify that finalPortfolioValue calculation is correct
        // It should not include excess cashBalance from full month budget
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0) {
            // Final portfolio value should be reasonable (not inflated by excess cash)
            expect(result.finalPortfolioValue).toBeLessThan(
                result.totalInvested * 5
            ); // Sanity check
        }
    });

    it("should not include excess cashBalance in finalPortfolioValue for AHR999 partial month", async () => {
        // This test ensures that for AHR999 (non-unlimited) with partial month,
        // the cashBalance is proportional to days, not full month budget
        const strategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: false,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-11-01");
        const endDate = new Date("2025-11-13"); // 13 days

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected proportional budget
        const expectedDailyAmount = 500 / 30.44;
        const expectedTotalBudget = 13 * expectedDailyAmount;

        // Final portfolio value should be calculated as: cashBalance + btcBalance * finalPrice
        // If cashBalance was incorrectly set to full month ($500), then:
        // cashBalance = $500 - actualInvestment (excess)
        // finalPortfolioValue would be inflated by this excess

        // With the fix, cashBalance should be proportional:
        // cashBalance ≈ expectedTotalBudget - totalInvested ≈ 0 (if all invested)

        // Verify finalPortfolioValue is reasonable
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0 && result.totalInvested > 0) {
            // Sanity check: finalPortfolioValue should be at least totalInvested * 0.5
            // (unless BTC price dropped significantly)
            expect(result.finalPortfolioValue).toBeGreaterThan(
                result.totalInvested * 0.5
            );

            // Verify that totalInvested doesn't exceed expected budget
            // (AHR999 may invest less due to multipliers, but shouldn't exceed budget)
            expect(result.totalInvested).toBeLessThanOrEqual(
                expectedTotalBudget * 1.01
            );
        }
    });

    it("should calculate cashBalance correctly for AHR999 unlimited budget mode with partial month", async () => {
        // Test case: Nov 1 to Nov 13, 2025 (13 days) with unlimited budget
        // Monthly budget: $500
        // Expected proportional cashBalance: 13/30.44 × $500 ≈ $213.59
        // Even with unlimited budget, cashBalance should be proportional to avoid inflating finalPortfolioValue
        const strategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: true, // Enable unlimited budget
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-11-01");
        const endDate = new Date("2025-11-13"); // 13 days

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected proportional budget for cashBalance
        const expectedDailyAmount = 500 / 30.44;
        const expectedProportionalBudget = 13 * expectedDailyAmount; // ~$213.59

        console.log("AHR999 Unlimited budget partial month test:", {
            durationDays: result.durationDays,
            expectedProportionalBudget: expectedProportionalBudget.toFixed(2),
            actualTotalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
        });

        // With unlimited budget, investment can exceed proportional budget
        // But finalPortfolioValue should not be inflated by excess cashBalance
        // finalPortfolioValue = cashBalance + btcBalance * finalPrice
        // If cashBalance was incorrectly set to full month ($500), finalPortfolioValue would be inflated

        // Verify that finalPortfolioValue is reasonable
        // It should not be significantly higher than totalInvested unless BTC price increased substantially
        expect(result.finalPortfolioValue).toBeGreaterThan(0);
        expect(isFinite(result.totalReturn)).toBe(true);

        // The key test: if we invested more than proportional budget, cashBalance should be negative
        // but finalPortfolioValue should still be calculated correctly
        // If cashBalance was incorrectly set to $500 instead of $213.59, finalPortfolioValue would be inflated by $286.41
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0 && result.totalInvested > 0) {
            // Calculate implied cashBalance from finalPortfolioValue
            // finalPortfolioValue = cashBalance + btcBalance * finalPrice
            // btcBalance ≈ totalInvested / averagePrice
            // If cashBalance was incorrectly inflated, finalPortfolioValue would be too high

            // Sanity check: finalPortfolioValue should be reasonable
            // If return is extremely high (>200%), it might indicate cashBalance inflation
            // But we can't be too strict as BTC price might have actually increased
            // Instead, we verify that the calculation is consistent

            // For unlimited budget, totalInvested can exceed proportional budget
            // But the return calculation should still be correct
            expect(result.finalPortfolioValue).toBeGreaterThan(
                result.totalInvested * 0.5
            );
        }
    });

    it("should not inflate finalPortfolioValue with unused budget for AHR999 multi-month period", async () => {
        // Test case: March 3 to Nov 13, 2025 (multi-month period)
        // Monthly budget: $500
        // AHR999 strategy should not accumulate unused budget in finalPortfolioValue
        const strategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: false,
        });
        const engine = new BacktestEngine(strategy, dataLoader);

        const startDate = new Date("2025-03-03");
        const endDate = new Date("2025-11-13");

        const result = await engine.run(startDate, endDate, 500);

        // Calculate expected total budget
        const expectedDailyAmount = 500 / 30.44;
        const expectedTotalBudget = result.durationDays * expectedDailyAmount;

        console.log("AHR999 Multi-month test:", {
            durationDays: result.durationDays,
            expectedTotalBudget: expectedTotalBudget.toFixed(2),
            actualTotalInvested: result.totalInvested.toFixed(2),
            finalPortfolioValue: result.finalPortfolioValue.toFixed(2),
            totalReturn: result.totalReturn.toFixed(2),
        });

        // Key test: finalPortfolioValue should NOT include unused budget
        // finalPortfolioValue should only be: btcBalance * finalPrice
        // If it included unused budget, it would be inflated
        const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
        if (finalPrice > 0 && result.totalInvested > 0) {
            // Calculate expected BTC balance (rough estimate)
            const averagePrice =
                result.transactions.reduce((sum, t) => sum + t.price, 0) /
                result.transactions.length;
            const expectedBtcBalance = result.totalInvested / averagePrice;
            const expectedFinalValue = expectedBtcBalance * finalPrice;

            // finalPortfolioValue should be close to expectedFinalValue (within reasonable range)
            // It should NOT be inflated by unused budget
            // If unused budget was included, finalPortfolioValue would be much higher
            expect(result.finalPortfolioValue).toBeGreaterThan(0);
            expect(result.finalPortfolioValue).toBeLessThan(
                expectedTotalBudget * 2
            ); // Sanity check

            // The return should be based on BTC price movement, not unused budget
            // If return is extremely high (>200%), it might indicate unused budget inflation
            // But we can't be too strict as BTC price might have actually increased
        }
    });

    it("should produce different results for unlimited vs limited budget AHR999", async () => {
        // Test that unlimited budget mode produces different results than limited budget
        const limitedStrategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: false,
        });
        const unlimitedStrategy = new AHR999PercentileStrategy(500, {
            unlimitedBudget: true,
        });

        const limitedEngine = new BacktestEngine(limitedStrategy, dataLoader);
        const unlimitedEngine = new BacktestEngine(
            unlimitedStrategy,
            dataLoader
        );

        const startDate = new Date("2025-03-03");
        const endDate = new Date("2025-11-13");

        const limitedResult = await limitedEngine.run(startDate, endDate, 500);
        const unlimitedResult = await unlimitedEngine.run(
            startDate,
            endDate,
            500
        );

        console.log("AHR999 Limited vs Unlimited:", {
            limited: {
                totalInvested: limitedResult.totalInvested.toFixed(2),
                finalPortfolioValue:
                    limitedResult.finalPortfolioValue.toFixed(2),
                totalReturn: limitedResult.totalReturn.toFixed(2),
            },
            unlimited: {
                totalInvested: unlimitedResult.totalInvested.toFixed(2),
                finalPortfolioValue:
                    unlimitedResult.finalPortfolioValue.toFixed(2),
                totalReturn: unlimitedResult.totalReturn.toFixed(2),
            },
        });

        // With unlimited budget, investment should be able to exceed the limited budget
        // But if AHR999 values are high (expensive), both might invest similarly
        // The key is that finalPortfolioValue should not be inflated by unused budget in either case
        expect(limitedResult.finalPortfolioValue).toBeGreaterThan(0);
        expect(unlimitedResult.finalPortfolioValue).toBeGreaterThan(0);

        // Both should have reasonable returns (not inflated by unused budget)
        expect(isFinite(limitedResult.totalReturn)).toBe(true);
        expect(isFinite(unlimitedResult.totalReturn)).toBe(true);
    });

    describe("AHR999 Strategy Budget Logic - Comprehensive Tests", () => {
        it("should correctly calculate finalPortfolioValue for various time periods", async () => {
            // Test multiple time periods to ensure logic is correct for all scenarios
            const testCases = [
                {
                    name: "1 month (full month)",
                    start: "2025-01-01",
                    end: "2025-01-31",
                    expectedDays: 31,
                },
                {
                    name: "1 month (partial start)",
                    start: "2025-01-15",
                    end: "2025-01-31",
                    expectedDays: 17,
                },
                {
                    name: "1 month (partial end)",
                    start: "2025-01-01",
                    end: "2025-01-15",
                    expectedDays: 15,
                },
                {
                    name: "2 months (full months)",
                    start: "2025-01-01",
                    end: "2025-02-28",
                    expectedDays: 59,
                },
                {
                    name: "3 months (cross quarter)",
                    start: "2025-01-15",
                    end: "2025-04-15",
                    expectedDays: 91,
                },
                {
                    name: "6 months (half year)",
                    start: "2025-01-01",
                    end: "2025-06-30",
                    expectedDays: 181,
                },
                {
                    name: "1 year (full year)",
                    start: "2025-01-01",
                    end: "2025-12-31",
                    expectedDays: 365,
                },
            ];

            for (const testCase of testCases) {
                const strategy = new AHR999PercentileStrategy(500, {
                    unlimitedBudget: false,
                });
                const engine = new BacktestEngine(strategy, dataLoader);

                const startDate = new Date(testCase.start);
                const endDate = new Date(testCase.end);

                const result = await engine.run(startDate, endDate, 500);

                // Calculate expected total budget
                const expectedDailyAmount = 500 / 30.44;
                const expectedTotalBudget =
                    result.durationDays * expectedDailyAmount;

                // Key assertions:
                // 1. totalInvested should not exceed totalBudget
                expect(result.totalInvested).toBeLessThanOrEqual(
                    expectedTotalBudget * 1.01
                );

                // 2. finalPortfolioValue should only include BTC value, not unused budget
                // If unused budget was included, finalPortfolioValue would be inflated
                const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
                if (finalPrice > 0) {
                    // finalPortfolioValue should be: btcBalance * finalPrice
                    // It should NOT include unused budget
                    const expectedBtcValue =
                        result.finalBtcBalance * finalPrice;
                    expect(result.finalPortfolioValue).toBeCloseTo(
                        expectedBtcValue,
                        2
                    );

                    // If unused budget was included, finalPortfolioValue would be much higher
                    // Sanity check: finalPortfolioValue should not exceed totalBudget significantly
                    // (unless BTC price increased dramatically)
                    expect(result.finalPortfolioValue).toBeLessThan(
                        expectedTotalBudget * 3
                    );
                }

                // 3. Return should be based on BTC price movement, not unused budget
                if (result.totalInvested > 0) {
                    const impliedReturn =
                        (result.finalPortfolioValue - result.totalInvested) /
                        result.totalInvested;
                    expect(result.totalReturn).toBeCloseTo(
                        impliedReturn * 100,
                        1
                    );
                }
            }
        });

        it("should correctly handle budget constraint for AHR999 with different multipliers", async () => {
            // Test that budget constraint works correctly regardless of multiplier values
            const testCases = [
                {
                    name: "All multipliers 0 (no investment)",
                    multipliers: {
                        multiplier_p10: 0,
                        multiplier_p25: 0,
                        multiplier_p50: 0,
                        multiplier_p75: 0,
                        multiplier_p90: 0,
                        multiplier_p100: 0,
                    },
                    expectedInvested: 0,
                },
                {
                    name: "Only p10 multiplier (extreme cheap)",
                    multipliers: {
                        multiplier_p10: 10,
                        multiplier_p25: 0,
                        multiplier_p50: 0,
                        multiplier_p75: 0,
                        multiplier_p90: 0,
                        multiplier_p100: 0,
                    },
                },
                {
                    name: "High multipliers (aggressive investment)",
                    multipliers: {
                        multiplier_p10: 20,
                        multiplier_p25: 10,
                        multiplier_p50: 5,
                        multiplier_p75: 2,
                        multiplier_p90: 1,
                        multiplier_p100: 0,
                    },
                },
            ];

            const startDate = new Date("2025-01-01");
            const endDate = new Date("2025-03-31"); // 3 months

            for (const testCase of testCases) {
                const strategy = new AHR999PercentileStrategy(500, {
                    unlimitedBudget: false,
                    ...testCase.multipliers,
                });
                const engine = new BacktestEngine(strategy, dataLoader);

                const result = await engine.run(startDate, endDate, 500);

                // Calculate expected total budget
                const expectedDailyAmount = 500 / 30.44;
                const expectedTotalBudget =
                    result.durationDays * expectedDailyAmount;

                // Key assertions:
                // 1. totalInvested should not exceed totalBudget
                expect(result.totalInvested).toBeLessThanOrEqual(
                    expectedTotalBudget * 1.01
                );

                // 2. finalPortfolioValue should only include BTC value
                const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
                if (finalPrice > 0 && result.totalInvested > 0) {
                    const expectedBtcValue =
                        result.finalBtcBalance * finalPrice;
                    expect(result.finalPortfolioValue).toBeCloseTo(
                        expectedBtcValue,
                        2
                    );
                }

                // 3. If expectedInvested is specified, verify it
                if (testCase.expectedInvested !== undefined) {
                    expect(result.totalInvested).toBe(
                        testCase.expectedInvested
                    );
                }
            }
        });

        it("should correctly calculate finalPortfolioValue for unlimited budget mode", async () => {
            // Test that unlimited budget mode also correctly calculates finalPortfolioValue
            const strategy = new AHR999PercentileStrategy(500, {
                unlimitedBudget: true,
            });
            const engine = new BacktestEngine(strategy, dataLoader);

            const startDate = new Date("2025-01-01");
            const endDate = new Date("2025-06-30"); // 6 months

            const result = await engine.run(startDate, endDate, 500);

            // For unlimited budget, totalInvested can exceed the proportional budget
            // But finalPortfolioValue should still only include BTC value, not unused budget
            const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
            if (finalPrice > 0 && result.totalInvested > 0) {
                const expectedBtcValue = result.finalBtcBalance * finalPrice;
                expect(result.finalPortfolioValue).toBeCloseTo(
                    expectedBtcValue,
                    2
                );

                // Return should be based on BTC price movement
                const impliedReturn =
                    (result.finalPortfolioValue - result.totalInvested) /
                    result.totalInvested;
                expect(result.totalReturn).toBeCloseTo(impliedReturn * 100, 1);
            }
        });

        it("should maintain consistency: finalPortfolioValue = btcBalance * finalPrice for AHR999", async () => {
            // This is the core invariant: for AHR999 strategies, finalPortfolioValue should always equal btcBalance * finalPrice
            const testPeriods = [
                { start: "2025-01-01", end: "2025-01-31" },
                { start: "2025-01-15", end: "2025-02-15" },
                { start: "2025-03-03", end: "2025-11-13" },
                { start: "2025-01-01", end: "2025-12-31" },
            ];

            for (const period of testPeriods) {
                const strategy = new AHR999PercentileStrategy(500, {
                    unlimitedBudget: false,
                });
                const engine = new BacktestEngine(strategy, dataLoader);

                const startDate = new Date(period.start);
                const endDate = new Date(period.end);

                const result = await engine.run(startDate, endDate, 500);

                const finalPrice = dataLoader.getPriceData(endDate)?.price || 0;
                if (finalPrice > 0) {
                    const expectedValue = result.finalBtcBalance * finalPrice;
                    expect(result.finalPortfolioValue).toBeCloseTo(
                        expectedValue,
                        2
                    );
                }
            }
        });
    });

    describe("Zero Investment Edge Cases", () => {
        it("should have finalPortfolioValue = 0 when totalInvested = 0 for AHR999 strategy", async () => {
            // Test core invariant: if totalInvested = 0, finalPortfolioValue must be 0
            // This ensures unused budget is not counted in finalPortfolioValue
            const strategy = new AHR999PercentileStrategy(500, {
                multiplier_p10: 0,
                multiplier_p25: 0,
                multiplier_p50: 0,
                multiplier_p75: 0,
                multiplier_p90: 0,
                multiplier_p100: 0,
            });
            const engine = new BacktestEngine(strategy, dataLoader);

            const startDate = new Date("2025-01-01");
            const endDate = new Date("2025-01-31");

            const result = await engine.run(startDate, endDate, 500);

            // With all multipliers = 0, no investment should occur
            expect(result.totalInvested).toBe(0);
            expect(result.finalBtcBalance).toBe(0);
            expect(result.finalPortfolioValue).toBe(0);
            expect(result.totalReturn).toBe(0);
        });

        it("should have finalPortfolioValue = 0 when totalInvested = 0 regardless of time period", async () => {
            // This test verifies that even if cashBalance > 0 (budget was added),
            // if totalInvested = 0, finalPortfolioValue must be 0
            // This is the core fix: unused budget should not be counted in finalPortfolioValue

            // Use AHR999 with all multipliers = 0 to guarantee no investment
            // Even though AHR999 doesn't add to cashBalance, this test verifies the invariant
            const strategy = new AHR999PercentileStrategy(500, {
                multiplier_p10: 0,
                multiplier_p25: 0,
                multiplier_p50: 0,
                multiplier_p75: 0,
                multiplier_p90: 0,
                multiplier_p100: 0,
            });
            const engine = new BacktestEngine(strategy, dataLoader);

            // Test multiple time periods to ensure the invariant holds
            const testPeriods = [
                { start: "2025-01-01", end: "2025-01-31" },
                { start: "2025-03-03", end: "2025-11-13" },
                { start: "2025-01-01", end: "2025-12-31" },
            ];

            for (const period of testPeriods) {
                const startDate = new Date(period.start);
                const endDate = new Date(period.end);

                const result = await engine.run(startDate, endDate, 500);

                // Core invariant: if totalInvested = 0, finalPortfolioValue must be 0
                // This ensures unused budget is not counted
                expect(result.totalInvested).toBe(0);
                expect(result.finalPortfolioValue).toBe(0);
                expect(result.totalReturn).toBe(0);
            }
        });
    });
});
