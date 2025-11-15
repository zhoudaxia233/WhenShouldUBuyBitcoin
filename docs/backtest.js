/**
 * Bitcoin Strategy Backtesting and Simulation Engine
 *
 * This module provides a complete backtesting framework for different Bitcoin
 * investment strategies, using historical data and power law projections.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const BACKTEST_CONFIG = {
    DATA_CSV: "data/btc_metrics.csv",
    DATA_METADATA: "data/btc_metadata.json",
    GENESIS_DATE: new Date("2009-01-03"),
    DCA_WINDOW: 200,
    DAYS_PER_MONTH: 30.44, // Average days per month
};

// ============================================================================
// DATA STRUCTURES
// ============================================================================

/**
 * Represents a single day's price and indicator data
 */
class DayData {
    constructor(
        date,
        price,
        ahr999 = null,
        ratio_dca = null,
        ratio_trend = null
    ) {
        this.date = date;
        this.price = price;
        this.ahr999 = ahr999;
        this.ratio_dca = ratio_dca;
        this.ratio_trend = ratio_trend;
    }
}

/**
 * Represents the state of a portfolio at a point in time
 */
class PortfolioState {
    constructor(date, cashBalance, btcBalance, totalInvested, portfolioValue) {
        this.date = date;
        this.cashBalance = cashBalance;
        this.btcBalance = btcBalance;
        this.totalInvested = totalInvested;
        this.portfolioValue = portfolioValue;
    }
}

/**
 * Backtest results summary
 */
class BacktestResult {
    constructor() {
        this.totalInvested = 0;
        this.finalBtcBalance = 0;
        this.finalPortfolioValue = 0;
        this.totalReturn = 0;
        this.annualizedReturn = 0;
        this.portfolioHistory = []; // Array of PortfolioState
        this.strategyName = "";
        this.startDate = null;
        this.endDate = null;
        this.durationDays = 0;
    }
}

// ============================================================================
// DATA LOADER
// ============================================================================

class DataLoader {
    constructor() {
        this.historicalData = null;
        this.metadata = null;
        this.priceCache = new Map(); // Cache for quick date lookups
    }

    /**
     * Load all required data (CSV + metadata)
     */
    async load() {
        if (this.historicalData && this.metadata) {
            return; // Already loaded
        }

        // Load both in parallel
        const [csvData, metadata] = await Promise.all([
            this.loadCSV(),
            this.loadMetadata(),
        ]);

        this.historicalData = csvData;
        this.metadata = metadata;

        // Build price cache for fast lookups
        this.buildPriceCache();
    }

    /**
     * Load and parse CSV data
     */
    async loadCSV() {
        const response = await fetch(BACKTEST_CONFIG.DATA_CSV);
        const text = await response.text();

        const lines = text.trim().split("\n");
        const headers = lines[0].split(",");

        const data = [];
        for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(",");
            const row = {};
            headers.forEach((header, index) => {
                row[header] = values[index];
            });
            data.push(row);
        }

        return data;
    }

    /**
     * Load metadata with power law parameters
     */
    async loadMetadata() {
        const response = await fetch(BACKTEST_CONFIG.DATA_METADATA);
        return await response.json();
    }

    /**
     * Build a map of date -> price for fast lookups
     */
    buildPriceCache() {
        this.priceCache.clear();
        this.historicalData.forEach((row) => {
            const dateStr = row.date;
            this.priceCache.set(dateStr, {
                price: parseFloat(row.close_price),
                ahr999: row.ahr999 ? parseFloat(row.ahr999) : null,
                ratio_dca: row.ratio_dca ? parseFloat(row.ratio_dca) : null,
                ratio_trend: row.ratio_trend
                    ? parseFloat(row.ratio_trend)
                    : null,
            });
        });
    }

    /**
     * Get the last available historical date
     */
    getLastHistoricalDate() {
        if (!this.historicalData || this.historicalData.length === 0) {
            return null;
        }
        const lastRow = this.historicalData[this.historicalData.length - 1];
        return new Date(lastRow.date);
    }

    /**
     * Get price and indicators for a specific date
     * If date is beyond historical data, use power law model
     */
    getPriceData(date) {
        const dateStr = this.formatDate(date);

        // Check if we have historical data for this date
        if (this.priceCache.has(dateStr)) {
            const cached = this.priceCache.get(dateStr);
            return new DayData(
                date,
                cached.price,
                cached.ahr999,
                cached.ratio_dca,
                cached.ratio_trend
            );
        }

        // If date is in the future, use power law model
        const lastHistoricalDate = this.getLastHistoricalDate();
        if (date > lastHistoricalDate) {
            const syntheticPrice = this.calculatePowerLawPrice(date);
            return new DayData(date, syntheticPrice, null, null, null);
        }

        // Date is in historical range but missing (weekend/holiday) - return null
        return null;
    }

    /**
     * Calculate Bitcoin price using power law model
     * Formula: price = a * (days since genesis)^n
     */
    calculatePowerLawPrice(date) {
        const bitcoinAgeDays = Math.floor(
            (date - BACKTEST_CONFIG.GENESIS_DATE) / (1000 * 60 * 60 * 24)
        );
        return (
            this.metadata.trend_a *
            Math.pow(bitcoinAgeDays, this.metadata.trend_b)
        );
    }

    /**
     * Calculate AHR999 for any date using rolling window
     * This is needed for future dates where we don't have precomputed values
     */
    calculateAHR999(date, priceHistory) {
        // Need at least 200 days of history
        if (priceHistory.length < BACKTEST_CONFIG.DCA_WINDOW) {
            return null;
        }

        // Get last 200 prices
        const last200 = priceHistory.slice(-BACKTEST_CONFIG.DCA_WINDOW);

        // Calculate DCA cost (harmonic mean)
        const sumInverse = last200.reduce((sum, p) => sum + 1 / p, 0);
        const dcaCost = BACKTEST_CONFIG.DCA_WINDOW / sumInverse;

        // Calculate trend value
        const trendValue = this.calculatePowerLawPrice(date);

        // Get current price
        const currentPrice = priceHistory[priceHistory.length - 1];

        // Calculate ratios
        const ratio_dca = currentPrice / dcaCost;
        const ratio_trend = currentPrice / trendValue;

        // AHR999 = ratio_dca * ratio_trend
        return ratio_dca * ratio_trend;
    }

    /**
     * Get all historical AHR999 values for percentile calculations
     */
    getHistoricalAHR999Values() {
        return this.historicalData
            .map((row) => {
                const ratio_dca = parseFloat(row.ratio_dca);
                const ratio_trend = parseFloat(row.ratio_trend);
                if (isNaN(ratio_dca) || isNaN(ratio_trend)) return null;
                return ratio_dca * ratio_trend;
            })
            .filter((val) => val !== null);
    }

    /**
     * Format date as YYYY-MM-DD string
     */
    formatDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Calculate percentile of a value in an array
 */
function calculatePercentile(arr, value) {
    const sorted = [...arr].sort((a, b) => a - b);
    const belowCount = sorted.filter((v) => v < value).length;
    return (belowCount / sorted.length) * 100;
}

/**
 * Get percentile value from array
 */
function getPercentileValue(arr, percentile) {
    const sorted = [...arr].sort((a, b) => a - b);
    const index = Math.floor((percentile / 100) * sorted.length);
    return sorted[Math.min(index, sorted.length - 1)];
}

/**
 * Add days to a date
 */
function addDays(date, days) {
    const result = new Date(date);
    result.setDate(result.getDate() + days);
    return result;
}

/**
 * Check if it's the first day of the month
 */
function isFirstDayOfMonth(date, prevDate) {
    if (!prevDate) return true;
    return date.getMonth() !== prevDate.getMonth();
}

/**
 * Check if it's a specific day of the month
 */
function isDayOfMonth(date, targetDay) {
    return date.getDate() === targetDay;
}

// ============================================================================
// STRATEGY BASE CLASS
// ============================================================================

/**
 * Abstract base class for all investment strategies
 *
 * All strategies must implement:
 * - getName(): Return strategy name
 * - getDescription(): Return strategy description
 * - initialize(): Called once before backtest starts
 * - shouldInvest(): Return investment amount for a given day
 * - onMonthStart(): Called at the start of each month
 */
class Strategy {
    constructor(monthlyBudget, config = {}) {
        this.monthlyBudget = monthlyBudget;
        this.config = config;
        this.cashBuffer = 0;
        this.dataLoader = null;
        this.priceHistory = []; // Rolling price history for AHR999 calculation
    }

    /**
     * Set data loader reference
     */
    setDataLoader(dataLoader) {
        this.dataLoader = dataLoader;
    }

    /**
     * Get strategy name (must be implemented by subclasses)
     */
    getName() {
        throw new Error("Strategy.getName() must be implemented");
    }

    /**
     * Get strategy description (must be implemented by subclasses)
     */
    getDescription() {
        throw new Error("Strategy.getDescription() must be implemented");
    }

    /**
     * Initialize strategy before backtest (optional override)
     */
    initialize() {
        this.cashBuffer = 0;
        this.priceHistory = [];
    }

    /**
     * Calculate how much to invest on this day
     * Returns: amount in USD to invest
     * (must be implemented by subclasses)
     */
    shouldInvest(date, price, dayData) {
        throw new Error("Strategy.shouldInvest() must be implemented");
    }

    /**
     * Called at the start of each new month (optional override)
     */
    onMonthStart(date) {
        // Default: add monthly budget to cash buffer
        this.cashBuffer += this.monthlyBudget;
    }

    /**
     * Update price history (used for AHR999 calculation)
     */
    updatePriceHistory(price) {
        this.priceHistory.push(price);
        // Keep only what we need for calculations
        if (this.priceHistory.length > BACKTEST_CONFIG.DCA_WINDOW + 100) {
            this.priceHistory.shift();
        }
    }

    /**
     * Get current AHR999 value
     */
    getCurrentAHR999(date) {
        if (!this.dataLoader) return null;
        return this.dataLoader.calculateAHR999(date, this.priceHistory);
    }
}

// ============================================================================
// STRATEGY A: DAILY DCA
// ============================================================================

/**
 * Daily DCA Strategy
 * Invests a fixed amount every single day
 */
class DailyDCAStrategy extends Strategy {
    constructor(monthlyBudget) {
        super(monthlyBudget);
        this.dailyAmount = monthlyBudget / BACKTEST_CONFIG.DAYS_PER_MONTH;
    }

    getName() {
        return "Daily DCA";
    }

    getDescription() {
        return `Invest $${this.dailyAmount.toFixed(2)} every day`;
    }

    initialize() {
        super.initialize();
        // Daily DCA doesn't need cash buffer - invests immediately
        this.cashBuffer = 0;
    }

    shouldInvest(date, price, dayData) {
        // Always invest the daily amount
        return this.dailyAmount;
    }

    onMonthStart(date) {
        // Daily DCA doesn't accumulate monthly - it's truly daily
        // So we don't add to cash buffer
    }
}

// ============================================================================
// STRATEGY B: MONTHLY DCA
// ============================================================================

/**
 * Monthly DCA Strategy
 * Invests entire monthly budget on a specific day each month
 */
class MonthlyDCAStrategy extends Strategy {
    constructor(monthlyBudget, config = {}) {
        super(monthlyBudget, config);
        this.dayOfMonth = config.dayOfMonth || 1; // Default to 1st of month
    }

    getName() {
        return "Monthly DCA";
    }

    getDescription() {
        return `Invest $${this.monthlyBudget} on day ${this.dayOfMonth} of each month`;
    }

    shouldInvest(date, price, dayData) {
        // Invest if it's the target day of month AND we have cash
        if (
            isDayOfMonth(date, this.dayOfMonth) &&
            this.cashBuffer >= this.monthlyBudget
        ) {
            const investAmount = this.monthlyBudget;
            this.cashBuffer -= investAmount;
            return investAmount;
        }
        return 0;
    }
}

// ============================================================================
// STRATEGY C: AHR999 THRESHOLD
// ============================================================================

/**
 * AHR999 Threshold Strategy
 * Only invests when AHR999 is below a specific threshold
 * Accumulates cash when above threshold
 */
class AHR999ThresholdStrategy extends Strategy {
    constructor(monthlyBudget, config = {}) {
        super(monthlyBudget, config);
        this.threshold = config.threshold || 0.45;
    }

    getName() {
        return "AHR999 Threshold";
    }

    getDescription() {
        return `Invest when AHR999 < ${this.threshold}, accumulate cash otherwise`;
    }

    shouldInvest(date, price, dayData) {
        // Get AHR999 value
        let ahr999;
        if (dayData && dayData.ahr999 !== null) {
            ahr999 = dayData.ahr999;
        } else {
            ahr999 = this.getCurrentAHR999(date);
        }

        // If we can't calculate AHR999, don't invest
        if (ahr999 === null) {
            return 0;
        }

        // Only invest if below threshold and we have cash
        if (ahr999 < this.threshold && this.cashBuffer > 0) {
            // Invest all available cash when condition is met
            const investAmount = this.cashBuffer;
            this.cashBuffer = 0;
            return investAmount;
        }

        return 0;
    }
}

// ============================================================================
// STRATEGY D: VALUATION-AWARE DCA
// ============================================================================

/**
 * Valuation-Aware DCA Strategy
 * Dynamically adjusts investment amount based on AHR999 percentile
 * - Very low AHR999 (cheap): Invest aggressively
 * - Very high AHR999 (expensive): Invest minimally or not at all
 * Uses historical AHR999 distribution to determine boundaries
 */
class ValuationAwareDCAStrategy extends Strategy {
    constructor(monthlyBudget, config = {}) {
        super(monthlyBudget, config);
        this.ahr999Percentiles = null;
        this.dailyBudget = monthlyBudget / BACKTEST_CONFIG.DAYS_PER_MONTH;
    }

    getName() {
        return "Valuation-Aware DCA";
    }

    getDescription() {
        return "Invest aggressively when cheap (low AHR999), conservatively when expensive";
    }

    initialize() {
        super.initialize();

        // Calculate historical AHR999 percentiles for dynamic boundaries
        const historicalAHR999 = this.dataLoader.getHistoricalAHR999Values();

        this.ahr999Percentiles = {
            p10: getPercentileValue(historicalAHR999, 10), // Very cheap
            p25: getPercentileValue(historicalAHR999, 25), // Cheap
            p50: getPercentileValue(historicalAHR999, 50), // Fair
            p75: getPercentileValue(historicalAHR999, 75), // Expensive
            p90: getPercentileValue(historicalAHR999, 90), // Very expensive
        };

        console.log("AHR999 Percentiles:", this.ahr999Percentiles);
    }

    shouldInvest(date, price, dayData) {
        // Get AHR999 value
        let ahr999;
        if (dayData && dayData.ahr999 !== null) {
            ahr999 = dayData.ahr999;
        } else {
            ahr999 = this.getCurrentAHR999(date);
        }

        // If we can't calculate AHR999 or no cash, don't invest
        if (ahr999 === null || this.cashBuffer <= 0) {
            return 0;
        }

        // Calculate investment multiplier based on AHR999 percentile
        let multiplier;

        if (ahr999 < this.ahr999Percentiles.p10) {
            // Bottom 10% - EXTREMELY cheap - invest 5x daily budget
            multiplier = 5.0;
        } else if (ahr999 < this.ahr999Percentiles.p25) {
            // Bottom 25% - Very cheap - invest 3x daily budget
            multiplier = 3.0;
        } else if (ahr999 < this.ahr999Percentiles.p50) {
            // Below median - Cheap - invest 2x daily budget
            multiplier = 2.0;
        } else if (ahr999 < this.ahr999Percentiles.p75) {
            // Below 75% - Fair - invest 1x daily budget
            multiplier = 1.0;
        } else if (ahr999 < this.ahr999Percentiles.p90) {
            // Top 25% - Expensive - invest 0.5x daily budget
            multiplier = 0.5;
        } else {
            // Top 10% - VERY expensive - don't invest
            multiplier = 0;
        }

        // Calculate investment amount
        const idealInvestment = this.dailyBudget * multiplier;

        // Don't invest more than available cash
        const investAmount = Math.min(idealInvestment, this.cashBuffer);

        // Update cash buffer
        this.cashBuffer -= investAmount;

        return investAmount;
    }
}

// ============================================================================
// BACKTESTING ENGINE
// ============================================================================

/**
 * Main backtesting engine
 * Simulates a strategy over a date range
 */
class BacktestEngine {
    constructor(strategy, dataLoader) {
        this.strategy = strategy;
        this.dataLoader = dataLoader;
        this.strategy.setDataLoader(dataLoader);
    }

    /**
     * Run backtest from startDate to endDate
     */
    async run(startDate, endDate, monthlyBudget) {
        // Initialize result
        const result = new BacktestResult();
        result.strategyName = this.strategy.getName();
        result.startDate = startDate;
        result.endDate = endDate;
        result.durationDays = Math.floor(
            (endDate - startDate) / (1000 * 60 * 60 * 24)
        );

        // Initialize strategy
        this.strategy.initialize();

        // Portfolio state
        let cashBalance = 0;
        let btcBalance = 0;
        let totalInvested = 0;
        let prevDate = null;

        // Iterate day by day
        let currentDate = new Date(startDate);

        while (currentDate <= endDate) {
            // Check if new month started
            if (isFirstDayOfMonth(currentDate, prevDate)) {
                this.strategy.onMonthStart(currentDate);
                cashBalance += monthlyBudget; // Add monthly budget to cash
            }

            // Get price data for this day
            const dayData = this.dataLoader.getPriceData(currentDate);

            if (dayData && dayData.price > 0) {
                const price = dayData.price;

                // Update strategy's price history
                this.strategy.updatePriceHistory(price);

                // Ask strategy how much to invest
                const investAmount = this.strategy.shouldInvest(
                    currentDate,
                    price,
                    dayData
                );

                // Execute investment if strategy decided to invest
                if (investAmount > 0) {
                    const actualInvestment = Math.min(
                        investAmount,
                        cashBalance
                    );
                    if (actualInvestment > 0) {
                        const btcBought = actualInvestment / price;
                        btcBalance += btcBought;
                        cashBalance -= actualInvestment;
                        totalInvested += actualInvestment;
                    }
                }

                // Calculate portfolio value
                const portfolioValue = cashBalance + btcBalance * price;

                // Record portfolio state (sample every 7 days to reduce data size)
                const daysSinceStart = Math.floor(
                    (currentDate - startDate) / (1000 * 60 * 60 * 24)
                );
                if (
                    daysSinceStart % 7 === 0 ||
                    currentDate.getTime() === endDate.getTime()
                ) {
                    result.portfolioHistory.push(
                        new PortfolioState(
                            new Date(currentDate),
                            cashBalance,
                            btcBalance,
                            totalInvested,
                            portfolioValue
                        )
                    );
                }
            }

            // Move to next day
            prevDate = new Date(currentDate);
            currentDate = addDays(currentDate, 1);
        }

        // Calculate final results
        const finalPrice = this.dataLoader.getPriceData(endDate)?.price || 0;
        result.totalInvested = totalInvested;
        result.finalBtcBalance = btcBalance;
        result.finalPortfolioValue = cashBalance + btcBalance * finalPrice;

        // Calculate returns
        if (totalInvested > 0) {
            result.totalReturn =
                ((result.finalPortfolioValue - totalInvested) / totalInvested) *
                100;

            // Annualized return: ((final/initial)^(365/days) - 1) * 100
            if (result.durationDays > 0) {
                const returnRatio = result.finalPortfolioValue / totalInvested;
                const yearsElapsed = result.durationDays / 365.25;
                result.annualizedReturn =
                    (Math.pow(returnRatio, 1 / yearsElapsed) - 1) * 100;
            }
        }

        return result;
    }
}

// ============================================================================
// CHART RENDERING
// ============================================================================

/**
 * Render backtest results using Chart.js
 */
function renderBacktestChart(result, canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        console.error("Canvas not found:", canvasId);
        return;
    }

    const ctx = canvas.getContext("2d");

    // Destroy existing chart if any
    if (canvas.chart) {
        canvas.chart.destroy();
    }

    // Prepare data
    const labels = result.portfolioHistory.map((state) =>
        state.date.toLocaleDateString()
    );
    const portfolioValues = result.portfolioHistory.map(
        (state) => state.portfolioValue
    );
    const investedValues = result.portfolioHistory.map(
        (state) => state.totalInvested
    );

    // Create chart
    canvas.chart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Portfolio Value",
                    data: portfolioValues,
                    borderColor: "#0071e3",
                    backgroundColor: "rgba(0, 113, 227, 0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.1,
                },
                {
                    label: "Total Invested",
                    data: investedValues,
                    borderColor: "#86868b",
                    backgroundColor: "rgba(134, 134, 139, 0.05)",
                    borderWidth: 1,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                },
                tooltip: {
                    mode: "index",
                    intersect: false,
                    callbacks: {
                        label: function (context) {
                            let label = context.dataset.label || "";
                            if (label) {
                                label += ": ";
                            }
                            label +=
                                "$" +
                                context.parsed.y.toLocaleString("en-US", {
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                });
                            return label;
                        },
                    },
                },
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: "Date",
                    },
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45,
                        maxTicksLimit: 12,
                    },
                },
                y: {
                    display: true,
                    title: {
                        display: true,
                        text: "Value (USD)",
                    },
                    ticks: {
                        callback: function (value) {
                            return (
                                "$" +
                                value.toLocaleString("en-US", {
                                    minimumFractionDigits: 0,
                                    maximumFractionDigits: 0,
                                })
                            );
                        },
                    },
                },
            },
        },
    });
}

// ============================================================================
// UI CONTROLLER
// ============================================================================

/**
 * Main UI controller for backtest interface
 */
class BacktestUI {
    constructor() {
        this.dataLoader = new DataLoader();
        this.isRunning = false;
    }

    /**
     * Initialize UI and load data
     */
    async initialize() {
        try {
            // Show loading state
            console.log("Loading data for backtesting...");
            await this.dataLoader.load();
            console.log("Data loaded successfully");

            // Set date input constraints
            this.setupDateInputs();

            // Attach event listeners
            this.attachEventListeners();
        } catch (error) {
            console.error("Failed to initialize backtest UI:", error);
            alert("Failed to load data for backtesting: " + error.message);
        }
    }

    /**
     * Setup date input constraints
     */
    setupDateInputs() {
        const startDateInput = document.getElementById("backtestStartDate");
        const endDateInput = document.getElementById("backtestEndDate");

        if (!startDateInput || !endDateInput) return;

        // Get first and last historical dates
        const firstHistoricalDate = new Date(
            this.dataLoader.historicalData[0].date
        );
        const lastHistoricalDate = this.dataLoader.getLastHistoricalDate();

        // Set min date for start date
        startDateInput.min = this.formatDate(firstHistoricalDate);

        // Set default start date to 5 years ago or first available date
        const fiveYearsAgo = new Date();
        fiveYearsAgo.setFullYear(fiveYearsAgo.getFullYear() - 5);
        const defaultStartDate =
            fiveYearsAgo > firstHistoricalDate
                ? fiveYearsAgo
                : firstHistoricalDate;
        startDateInput.value = this.formatDate(defaultStartDate);

        // Set default end date to last historical date
        endDateInput.value = this.formatDate(lastHistoricalDate);

        // Allow end date up to 5 years in the future
        const fiveYearsFromNow = new Date();
        fiveYearsFromNow.setFullYear(fiveYearsFromNow.getFullYear() + 5);
        endDateInput.max = this.formatDate(fiveYearsFromNow);
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Strategy selection changes
        const strategyRadios = document.querySelectorAll(
            'input[name="backtestStrategy"]'
        );
        strategyRadios.forEach((radio) => {
            radio.addEventListener("change", () => this.onStrategyChange());
        });

        // Run backtest button
        const runButton = document.getElementById("runBacktestButton");
        if (runButton) {
            runButton.addEventListener("click", () => this.runBacktest());
        }

        // Initial strategy change to show/hide config options
        this.onStrategyChange();
    }

    /**
     * Handle strategy selection change
     */
    onStrategyChange() {
        const selectedStrategy = document.querySelector(
            'input[name="backtestStrategy"]:checked'
        )?.value;

        // Show/hide strategy-specific config
        document.getElementById("monthlyDcaConfig").style.display =
            selectedStrategy === "monthly-dca" ? "block" : "none";

        document.getElementById("ahr999ThresholdConfig").style.display =
            selectedStrategy === "ahr999-threshold" ? "block" : "none";
    }

    /**
     * Run backtest with selected parameters
     */
    async runBacktest() {
        if (this.isRunning) return;

        try {
            this.isRunning = true;

            // Get form values
            const startDate = new Date(
                document.getElementById("backtestStartDate").value
            );
            const endDate = new Date(
                document.getElementById("backtestEndDate").value
            );
            const monthlyBudget = parseFloat(
                document.getElementById("backtestBudget").value
            );
            const strategyType = document.querySelector(
                'input[name="backtestStrategy"]:checked'
            )?.value;

            // Validate inputs
            if (!startDate || !endDate || !monthlyBudget || !strategyType) {
                alert("Please fill in all required fields");
                return;
            }

            if (startDate >= endDate) {
                alert("End date must be after start date");
                return;
            }

            if (monthlyBudget <= 0) {
                alert("Monthly budget must be greater than 0");
                return;
            }

            // Show loading state
            const resultsDiv = document.getElementById("backtestResults");
            resultsDiv.innerHTML =
                '<div class="loading">Running backtest...</div>';
            resultsDiv.style.display = "block";

            // Create strategy based on selection
            let strategy;
            switch (strategyType) {
                case "daily-dca":
                    strategy = new DailyDCAStrategy(monthlyBudget);
                    break;

                case "monthly-dca":
                    const dayOfMonth =
                        parseInt(
                            document.getElementById("monthlyDcaDay").value
                        ) || 1;
                    strategy = new MonthlyDCAStrategy(monthlyBudget, {
                        dayOfMonth,
                    });
                    break;

                case "ahr999-threshold":
                    const threshold =
                        parseFloat(
                            document.getElementById("ahr999Threshold").value
                        ) || 0.45;
                    strategy = new AHR999ThresholdStrategy(monthlyBudget, {
                        threshold,
                    });
                    break;

                case "valuation-aware":
                    strategy = new ValuationAwareDCAStrategy(monthlyBudget);
                    break;

                default:
                    alert("Invalid strategy selected");
                    return;
            }

            // Create and run backtest engine
            const engine = new BacktestEngine(strategy, this.dataLoader);
            const result = await engine.run(startDate, endDate, monthlyBudget);

            // Display results
            this.displayResults(result);
        } catch (error) {
            console.error("Backtest error:", error);
            document.getElementById("backtestResults").innerHTML = `
                <div class="error">
                    <strong>Error:</strong> ${error.message}
                </div>
            `;
        } finally {
            this.isRunning = false;
        }
    }

    /**
     * Display backtest results
     */
    displayResults(result) {
        const resultsDiv = document.getElementById("backtestResults");

        // Determine if end date was in historical range or future
        const lastHistoricalDate = this.dataLoader.getLastHistoricalDate();
        const usedSimulation = result.endDate > lastHistoricalDate;

        const html = `
            <div class="backtest-summary">
                <h3>${result.strategyName} Results</h3>
                <p class="backtest-period">
                    ${result.startDate.toLocaleDateString()} to ${result.endDate.toLocaleDateString()}
                    (${result.durationDays} days / ${(
            result.durationDays / 365.25
        ).toFixed(1)} years)
                    ${
                        usedSimulation
                            ? '<br><span class="simulation-badge">⚡ Includes simulated future data</span>'
                            : ""
                    }
                </p>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <h3>Total Invested</h3>
                        <div class="metric-value">$${result.totalInvested.toLocaleString(
                            "en-US",
                            {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }
                        )}</div>
                    </div>

                    <div class="metric-card">
                        <h3>Final BTC Balance</h3>
                        <div class="metric-value">${result.finalBtcBalance.toFixed(
                            4
                        )} BTC</div>
                    </div>

                    <div class="metric-card">
                        <h3>Final Portfolio Value</h3>
                        <div class="metric-value">$${result.finalPortfolioValue.toLocaleString(
                            "en-US",
                            {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }
                        )}</div>
                    </div>

                    <div class="metric-card">
                        <h3>Total Return</h3>
                        <div class="metric-value" style="color: ${
                            result.totalReturn >= 0 ? "#28a745" : "#ff3b30"
                        }">
                            ${
                                result.totalReturn >= 0 ? "+" : ""
                            }${result.totalReturn.toFixed(2)}%
                        </div>
                        <div class="metric-detail">
                            Annualized: ${
                                result.annualizedReturn >= 0 ? "+" : ""
                            }${result.annualizedReturn.toFixed(2)}%
                        </div>
                    </div>
                </div>

                <div class="chart-wrapper">
                    <h4>Portfolio Value Over Time</h4>
                    <canvas id="backtestChart"></canvas>
                </div>
            </div>
        `;

        resultsDiv.innerHTML = html;
        resultsDiv.style.display = "block";

        // Render chart
        setTimeout(() => {
            renderBacktestChart(result, "backtestChart");
        }, 100);
    }

    /**
     * Format date as YYYY-MM-DD
     */
    formatDate(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================

// ============================================================================
// EXPORTS (for testing and external use)
// ============================================================================

export {
    DataLoader,
    Strategy,
    DailyDCAStrategy,
    MonthlyDCAStrategy,
    AHR999ThresholdStrategy,
    ValuationAwareDCAStrategy,
    BacktestEngine,
    BacktestUI,
    DayData,
    PortfolioState,
    BacktestResult,
};

// ============================================================================
// AUTO-INITIALIZATION
// ============================================================================

// Initialize when DOM is ready
let backtestUI;
document.addEventListener("DOMContentLoaded", async () => {
    backtestUI = new BacktestUI();
    await backtestUI.initialize();
});
