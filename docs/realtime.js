/**
 * Real-time Bitcoin Buy Zone Checker
 *
 * This JavaScript implementation mirrors the Python version but runs entirely in the browser.
 * It fetches real-time BTC prices from exchange APIs and calculates buy zone status.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
    // Real-time price APIs (priority order: Binance -> Coinbase)
    BINANCE_API: "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDC",
    COINBASE_API: "https://api.coinbase.com/v2/exchange-rates?currency=BTC",

    // Data paths (relative to the docs folder)
    DATA_CSV: "data/btc_metrics.csv",
    DATA_METADATA: "data/btc_metadata.json",

    // DCA window
    DCA_WINDOW: 200,

    // Retry configuration
    MAX_RETRIES: 3,
    RETRY_DELAY: 1000, // milliseconds
};

// ============================================================================
// DATA LOADING
// ============================================================================

/**
 * Load CSV data from file
 * @returns {Promise<Array>} Array of price data objects
 */
async function loadCSVData() {
    try {
        const response = await fetch(CONFIG.DATA_CSV);
        const text = await response.text();

        // Parse CSV (simple parser, assumes comma-separated)
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
    } catch (error) {
        console.error("Error loading CSV:", error);
        throw new Error("Failed to load historical data");
    }
}

/**
 * Load metadata (trend parameters) from JSON
 * @returns {Promise<Object>} Metadata object with trend_a and trend_b
 */
async function loadMetadata() {
    try {
        const response = await fetch(CONFIG.DATA_METADATA);
        return await response.json();
    } catch (error) {
        console.error("Error loading metadata:", error);
        throw new Error("Failed to load trend parameters");
    }
}

/**
 * Load daily report snapshot (optional) for free proxy signals (F&G / hashrate).
 * This keeps the realtime checker browser-only and avoids direct third-party API calls.
 */
async function loadDailyReportSnapshot() {
    try {
        const response = await fetch(`data/daily_report.json?t=${Date.now()}`, {
            cache: "no-store",
        });
        if (!response.ok) {
            throw new Error(`daily_report HTTP ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.warn("Failed to load daily_report snapshot for free signals:", error);
        return null;
    }
}

// ============================================================================
// REAL-TIME PRICE APIs
// ============================================================================

/**
 * Validate price data
 * @param {number} price - Price to validate
 * @returns {boolean} True if price is valid
 */
function validatePrice(price) {
    if (typeof price !== "number" || isNaN(price) || !isFinite(price)) {
        return false;
    }
    // Bitcoin price should be between $1,000 and $200,000 (reasonable range)
    return price > 1000 && price < 200000;
}

/**
 * Fetch real-time BTC price from Binance
 * @returns {Promise<Object>} Object with price, timestamp, and source
 */
async function fetchPriceFromBinance() {
    const response = await fetch(CONFIG.BINANCE_API);

    if (!response.ok) {
        throw new Error(`Binance API error: ${response.status}`);
    }

    const data = await response.json();

    if (!data || !data.price) {
        throw new Error("Invalid response from Binance API");
    }

    const price = parseFloat(data.price);

    if (!validatePrice(price)) {
        throw new Error(`Invalid price from Binance: ${price}`);
    }

    // Binance returns current server time, use it for timestamp
    const timestamp = new Date();

    return {
        price: price,
        timestamp: timestamp,
        source: "Binance",
    };
}

/**
 * Fetch real-time BTC price from Coinbase
 * @returns {Promise<Object>} Object with price, timestamp, and source
 */
async function fetchPriceFromCoinbase() {
    const response = await fetch(CONFIG.COINBASE_API);

    if (!response.ok) {
        throw new Error(`Coinbase API error: ${response.status}`);
    }

    const data = await response.json();

    if (!data || !data.data || !data.data.rates || !data.data.rates.USD) {
        throw new Error("Invalid response from Coinbase API");
    }

    const price = parseFloat(data.data.rates.USD);

    if (!validatePrice(price)) {
        throw new Error(`Invalid price from Coinbase: ${price}`);
    }

    // Coinbase doesn't provide timestamp, use current time
    const timestamp = new Date();

    return {
        price: price,
        timestamp: timestamp,
        source: "Coinbase",
    };
}

/**
 * Fetch real-time BTC price with retry logic
 * Priority: Binance -> Coinbase
 * @returns {Promise<Object>} Object with price, timestamp, and source
 */
async function fetchRealtimeBTCPrice() {
    const sources = [
        { name: "Binance", fetch: fetchPriceFromBinance },
        { name: "Coinbase", fetch: fetchPriceFromCoinbase },
    ];

    let lastError = null;

    // Try each source
    for (const source of sources) {
        // Retry logic for each source
        for (let attempt = 1; attempt <= CONFIG.MAX_RETRIES; attempt++) {
            try {
                console.log(
                    `Attempting to fetch price from ${source.name} (attempt ${attempt}/${CONFIG.MAX_RETRIES})...`
                );
                const result = await source.fetch();
                console.log(
                    `✓ Successfully fetched price from ${
                        result.source
                    }: $${result.price.toFixed(2)}`
                );
                return result;
            } catch (error) {
                console.error(
                    `✗ Error fetching from ${source.name} (attempt ${attempt}):`,
                    error.message
                );
                lastError = error;

                // Wait before retry (except on last attempt)
                if (attempt < CONFIG.MAX_RETRIES) {
                    await new Promise((resolve) =>
                        setTimeout(resolve, CONFIG.RETRY_DELAY)
                    );
                }
            }
        }
    }

    // All sources failed
    throw new Error(
        `Failed to fetch price from all sources. Last error: ${
            lastError?.message || "Unknown error"
        }`
    );
}

// ============================================================================
// CORE CALCULATIONS (Ported from Python)
// ============================================================================

/**
 * Calculate 200-day DCA cost
 *
 * This is the harmonic mean of the last 200 days of prices.
 * Formula: DCA = 200 / sum(1/price_i)
 *
 * @param {Array<number>} prices - Array of prices (last 200 days)
 * @returns {number} DCA cost
 */
function calculateDCA(prices) {
    if (prices.length < CONFIG.DCA_WINDOW) {
        throw new Error(`Need at least ${CONFIG.DCA_WINDOW} days of data`);
    }

    // Take last 200 prices
    const last200 = prices.slice(-CONFIG.DCA_WINDOW);

    // Calculate sum of 1/price
    const sumInverse = last200.reduce((sum, price) => sum + 1 / price, 0);

    // DCA cost = window / sum(1/price)
    return CONFIG.DCA_WINDOW / sumInverse;
}

/**
 * Calculate power law trend value
 *
 * Formula: trend = a * t^n
 *
 * This models Bitcoin price growth using a power law, which is more appropriate
 * than exponential growth because:
 * - It models network effects (Metcalfe's Law)
 * - Growth rate decreases over time (more realistic for mature assets)
 * - Widely used in academic Bitcoin research
 *
 * @param {number} a - Scaling coefficient
 * @param {number} n - Power law exponent (typically 5-6 for Bitcoin)
 * @param {number} bitcoinAgeDays - Bitcoin age in days since genesis (2009-01-03)
 * @returns {number} Trend value
 */
function calculateTrend(a, n, bitcoinAgeDays) {
    // Use Bitcoin age (days since 2009-01-03), NOT data age
    // This is critical for matching academic research!
    return a * Math.pow(bitcoinAgeDays, n);
}

/**
 * Calculate distance to buy zone
 *
 * For ratio >= 1.0: Calculate percentage drop needed
 * For ratio < 1.0: Already in buy zone, show how much below
 *
 * @param {number} ratio - Price/threshold ratio
 * @returns {Object} Distance information
 */
function calculateDistance(ratio) {
    if (ratio >= 1.0) {
        // Need to drop to reach buy zone
        // Percentage drop = (ratio - 1.0) / ratio * 100
        const dropNeeded = ((ratio - 1.0) / ratio) * 100;
        return {
            inZone: false,
            percentage: dropNeeded,
            direction: "needs_drop",
        };
    } else {
        // Already in buy zone
        // Percentage below = (1.0 - ratio) / 1.0 * 100
        const belowBy = ((1.0 - ratio) / 1.0) * 100;
        return {
            inZone: true,
            percentage: belowBy,
            direction: "already_below",
        };
    }
}

/**
 * Build a free-data volume-based bottoming proxy from CSV rows.
 * Uses daily close/volume only (no paid on-chain APIs).
 */
function calculateBottomingVolumeProxy(csvData) {
    if (!Array.isArray(csvData) || csvData.length < 35) {
        return { available: false };
    }

    const rows = csvData.map((row) => ({
        date: row.date,
        close: parseFloat(row.close_price),
        volume: parseFloat(row.volume),
    }));

    if (rows.some((r) => !Number.isFinite(r.volume))) {
        return { available: false };
    }

    const volumeWindow = 30;
    const panicLookback = 7;
    const panicDropPctThreshold = -5.0;
    const panicVolumeSpikeRatio = 1.5;

    const volumeSeries = rows.map((r) => r.volume);
    const closeSeries = rows.map((r) => r.close);

    const volumeMA = new Array(rows.length).fill(null);
    const volumeRatio = new Array(rows.length).fill(null);
    const dailyReturnPct = new Array(rows.length).fill(null);
    const panicFlags = new Array(rows.length).fill(false);
    const recentPanicFlags = new Array(rows.length).fill(false);

    for (let i = 0; i < rows.length; i++) {
        if (i >= volumeWindow - 1) {
            const slice = volumeSeries.slice(i - volumeWindow + 1, i + 1);
            const avg = slice.reduce((a, b) => a + b, 0) / slice.length;
            volumeMA[i] = avg;
            volumeRatio[i] = avg > 0 ? volumeSeries[i] / avg : null;
        }
        if (i > 0 && closeSeries[i - 1] > 0) {
            dailyReturnPct[i] = ((closeSeries[i] - closeSeries[i - 1]) / closeSeries[i - 1]) * 100;
        }
        if (
            dailyReturnPct[i] !== null &&
            volumeRatio[i] !== null &&
            dailyReturnPct[i] <= panicDropPctThreshold &&
            volumeRatio[i] >= panicVolumeSpikeRatio
        ) {
            panicFlags[i] = true;
        }
    }

    for (let i = 0; i < rows.length; i++) {
        const start = Math.max(0, i - panicLookback);
        // Exclude current day to preserve "panic first, contraction later"
        const priorSlice = panicFlags.slice(start, i);
        recentPanicFlags[i] = priorSlice.some(Boolean);
    }

    const idx = rows.length - 1;
    const isPostPanicVolumeContraction =
        recentPanicFlags[idx] && volumeRatio[idx] !== null && volumeRatio[idx] < 1.0;

    return {
        available: true,
        asOfDate: rows[idx].date || null,
        volume: rows[idx].volume,
        volumeMA30: volumeMA[idx],
        volumeRatio30: volumeRatio[idx],
        dailyReturnPct: dailyReturnPct[idx],
        isPanicSelloffDay: panicFlags[idx],
        recentPanicSelloff7d: recentPanicFlags[idx],
        isPostPanicVolumeContraction,
    };
}

function calculateRsiSeries(values, period = 14) {
    if (!Array.isArray(values) || values.length < period + 1) {
        return new Array(Array.isArray(values) ? values.length : 0).fill(null);
    }
    const out = new Array(values.length).fill(null);
    let gains = 0;
    let losses = 0;

    for (let i = 1; i <= period; i++) {
        const delta = values[i] - values[i - 1];
        if (!Number.isFinite(delta)) return out;
        if (delta > 0) gains += delta;
        else losses -= delta;
    }

    let avgGain = gains / period;
    let avgLoss = losses / period;
    out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

    for (let i = period + 1; i < values.length; i++) {
        const delta = values[i] - values[i - 1];
        const gain = delta > 0 ? delta : 0;
        const loss = delta < 0 ? -delta : 0;
        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;

        if (avgLoss === 0 && avgGain === 0) out[i] = 50;
        else if (avgLoss === 0) out[i] = 100;
        else out[i] = 100 - 100 / (1 + avgGain / avgLoss);
    }
    return out;
}

function calculateRsiContext(csvData) {
    if (!Array.isArray(csvData) || csvData.length < 30) {
        return { available: false };
    }
    const rows = csvData
        .map((row) => ({
            date: row.date,
            close: parseFloat(row.close_price),
        }))
        .filter((r) => Number.isFinite(r.close) && r.date);

    if (rows.length < 30) return { available: false };

    const closes = rows.map((r) => r.close);
    const dailyRsi = calculateRsiSeries(closes, 14);
    const latestDailyRsi = dailyRsi[dailyRsi.length - 1];

    // Weekly proxy: take last close per ISO-like week using YYYY-WW key via Date.
    const weeklyRows = [];
    let lastWeekKey = null;
    for (const row of rows) {
        const d = new Date(row.date);
        if (Number.isNaN(d.getTime())) continue;
        const weekKey = `${d.getUTCFullYear()}-${Math.floor((d.getUTCDate() - 1) / 7)}-${d.getUTCMonth()}`;
        if (lastWeekKey === weekKey && weeklyRows.length > 0) {
            weeklyRows[weeklyRows.length - 1] = row;
        } else {
            weeklyRows.push(row);
            lastWeekKey = weekKey;
        }
    }
    const weeklyCloses = weeklyRows.map((r) => r.close);
    const weeklyRsiSeries = calculateRsiSeries(weeklyCloses, 14);
    const latestWeeklyRsi = weeklyRsiSeries[weeklyRsiSeries.length - 1];

    return {
        available: Number.isFinite(latestDailyRsi) || Number.isFinite(latestWeeklyRsi),
        rsi14: Number.isFinite(latestDailyRsi) ? latestDailyRsi : null,
        rsi14w: Number.isFinite(latestWeeklyRsi) ? latestWeeklyRsi : null,
        isRsiDailyOversold: Number.isFinite(latestDailyRsi) ? latestDailyRsi < 30 : null,
        isRsiWeeklyOversoldProxy: Number.isFinite(latestWeeklyRsi) ? latestWeeklyRsi <= 35 : null,
        isRsiBottomingSignal:
            Number.isFinite(latestDailyRsi) && Number.isFinite(latestWeeklyRsi)
                ? latestDailyRsi < 30 && latestWeeklyRsi <= 35
                : null,
    };
}

function extractFreeBottomingSignalsFromDailyReport(report) {
    if (!report || !Array.isArray(report.sections)) {
        return { available: false };
    }
    const section = report.sections.find(
        (s) =>
            s &&
            (s.chart === "Supplemental Bottoming Signals" ||
                s.chart === "Free Bottoming Signals" ||
                s.chart === "Sentiment & Miner Proxies (Free)") &&
            s.metrics
    );
    if (!section) return { available: false };
    const m = section.metrics || {};
    const fearGreedValue = parseFloat(m.fear_greed_value);
    const fearPanicScore = parseFloat(m.fear_panic_score);
    const hashrate30dChangePct = parseFloat(m.hashrate_30d_change_pct);
    return {
        available: true,
        fearGreedValue: Number.isFinite(fearGreedValue) ? fearGreedValue : null,
        fearGreedClassification:
            typeof m.fear_greed_classification === "string"
                ? m.fear_greed_classification
                : null,
        fearPanicScore: Number.isFinite(fearPanicScore) ? fearPanicScore : null,
        isExtremeFearProxy:
            typeof m.is_extreme_fear_proxy === "boolean"
                ? m.is_extreme_fear_proxy
                : null,
        hashrate30dChangePct: Number.isFinite(hashrate30dChangePct)
            ? hashrate30dChangePct
            : null,
        minerStressProxy:
            typeof m.miner_stress_proxy === "string" ? m.miner_stress_proxy : null,
    };
}

function formatPctCompact(value) {
    if (!Number.isFinite(value)) return "N/A";
    if (Math.abs(value) < 0.005) {
        return "Nearly unchanged";
    }
    if (Math.abs(value) < 0.05) {
        return `${value.toFixed(4)}%`;
    }
    return `${value.toFixed(2)}%`;
}

/**
 * Calculate days between two dates
 * @param {Date} startDate
 * @param {Date} endDate
 * @returns {number} Number of days
 */
function daysBetween(startDate, endDate) {
    const diffTime = Math.abs(endDate - startDate);
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return diffDays;
}

/**
 * Get ahr999 zone classification
 * @param {number} ahr999Value - The ahr999 index value
 * @returns {Object} Zone classification with emoji, label, description
 */
function getAhr999Zone(ahr999Value) {
    if (ahr999Value < 0.45) {
        return {
            zone: "bottom",
            emoji: "🔥",
            label: "Bottom Zone",
            description:
                "Exceptional buying opportunity - historical bottom territory",
            action: "Strong Buy",
            color: "#28a745",
        };
    } else if (ahr999Value < 1.2) {
        return {
            zone: "dca",
            emoji: "💎",
            label: "DCA Zone",
            description:
                "Good accumulation zone - suitable for dollar-cost averaging",
            action: "Accumulate",
            color: "#0071e3",
        };
    } else {
        return {
            zone: "watch",
            emoji: "⚠️",
            label: "Watch Zone",
            description: "Potentially overheated - exercise caution",
            action: "Wait",
            color: "#ff9500",
        };
    }
}

/**
 * Calculate ahr999 historical percentile
 * @param {Array} csvData - Historical data with ahr999 values
 * @param {number} currentAhr999 - Current ahr999 value
 * @returns {number} Percentile (0-100)
 */
function calculateAhr999Percentile(csvData, currentAhr999) {
    // Calculate ahr999 for all historical data
    const historicalAhr999 = csvData
        .map((row) => parseFloat(row.ratio_dca) * parseFloat(row.ratio_trend))
        .filter((val) => !isNaN(val));

    if (historicalAhr999.length === 0) {
        return null;
    }

    // Count how many historical values are below current value
    const belowCount = historicalAhr999.filter(
        (val) => val < currentAhr999
    ).length;

    // Percentile = (count below / total) * 100
    const percentile = (belowCount / historicalAhr999.length) * 100;

    return percentile;
}

/**
 * Calculate ahr999 percentile among days where ahr999 < 1.0
 * This shows how good the current opportunity is compared to other buy zone days
 * @param {Array} csvData - Historical data with ahr999 values
 * @param {number} currentAhr999 - Current ahr999 value
 * @returns {number|null} Percentile (0-100) if currentAhr999 < 1.0, else null
 */
function calculateAhr999PercentileBelowOne(csvData, currentAhr999) {
    // Only calculate if current value is below 1.0 (in buy zone territory)
    if (currentAhr999 >= 1.0) {
        return null;
    }

    // Calculate ahr999 for all historical data and filter to < 1.0 only
    const historicalAhr999BelowOne = csvData
        .map((row) => parseFloat(row.ratio_dca) * parseFloat(row.ratio_trend))
        .filter((val) => !isNaN(val) && val < 1.0);

    if (historicalAhr999BelowOne.length === 0) {
        return null;
    }

    // Count how many buy zone days are below current value
    const belowCount = historicalAhr999BelowOne.filter(
        (val) => val < currentAhr999
    ).length;

    // Percentile among buy zone days = (count below / total buy zone days) * 100
    const percentile = (belowCount / historicalAhr999BelowOne.length) * 100;

    return percentile;
}

// ============================================================================
// TIMEZONE CONVERSION
// ============================================================================

/**
 * Format timestamp for display in multiple timezones
 * @param {Date} date
 * @returns {Object} Formatted timestamps
 */
function formatTimestamps(date) {
    // UTC time
    const utcString = date.toISOString().replace("T", " ").substring(0, 19);

    // Berlin time (Europe/Berlin)
    const berlinFormatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "Europe/Berlin",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
    });

    const berlinParts = berlinFormatter.formatToParts(date);
    const berlinObj = {};
    berlinParts.forEach((part) => {
        if (part.type !== "literal") {
            berlinObj[part.type] = part.value;
        }
    });

    const berlinString = `${berlinObj.year}-${berlinObj.month}-${berlinObj.day} ${berlinObj.hour}:${berlinObj.minute}:${berlinObj.second}`;

    // Timezone name
    const isDST = isDaylightSavingTime(date);
    const berlinTZ = isDST ? "CEST" : "CET";

    // Local time (user's browser timezone)
    const localTime = date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });

    // Get local timezone abbreviation
    const localTZ = new Intl.DateTimeFormat("en-US", {
        timeZoneName: "short",
    })
        .formatToParts(date)
        .find((part) => part.type === "timeZoneName").value;

    return {
        utc: utcString,
        berlin: berlinString,
        berlinTZ: berlinTZ,
        localTime: localTime,
        localTZ: localTZ,
    };
}

/**
 * Check if date is in daylight saving time for Europe/Berlin
 * @param {Date} date
 * @returns {boolean}
 */
function isDaylightSavingTime(date) {
    const jan = new Date(date.getFullYear(), 0, 1);
    const jul = new Date(date.getFullYear(), 6, 1);
    const janOffset = jan.getTimezoneOffset();
    const julOffset = jul.getTimezoneOffset();
    return Math.min(janOffset, julOffset) === date.getTimezoneOffset();
}

// ============================================================================
// MAIN CHECK FUNCTION
// ============================================================================

/**
 * Perform real-time buy zone check
 * This is the main function that orchestrates all calculations
 */
async function checkRealtimeStatus() {
    const loadingEl = document.getElementById("loading");
    const resultsEl = document.getElementById("results");
    const buttonEl = document.getElementById("checkButton");
    const placeholderEl = document.getElementById("results-placeholder");

    try {
        // Switch to Analysis tab
        if (typeof switchMainTab === "function") {
            switchMainTab("analysis");
        }

        // Show loading state
        loadingEl.style.display = "block";
        resultsEl.classList.remove("show");
        if (placeholderEl) {
            placeholderEl.classList.add("hidden");
        }
        buttonEl.disabled = true;

        // 1. Load historical data
        console.log("Loading historical data...");
        const [csvData, metadata, dailyReportSnapshot] = await Promise.all([
            loadCSVData(),
            loadMetadata(),
            loadDailyReportSnapshot(),
        ]);

        // Extract close prices from CSV
        const historicalPrices = csvData.map((row) =>
            parseFloat(row.close_price)
        );

        // 2. Fetch real-time price
        console.log("Fetching real-time BTC price...");
        const {
            price: realtimePrice,
            timestamp,
            source: priceSource,
        } = await fetchRealtimeBTCPrice();
        console.log(`Price source: ${priceSource}`);

        // 3. Calculate DCA
        // Use last 199 days + today's real-time price
        const last199 = historicalPrices.slice(-199);
        const prices200 = [...last199, realtimePrice];
        const dcaCost = calculateDCA(prices200);
        const ratioDCA = realtimePrice / dcaCost;
        const dcaDistance = calculateDistance(ratioDCA);

        // 4. Calculate Trend
        // IMPORTANT: Use Bitcoin age (days since genesis 2009-01-03), not data age!
        const genesisDate = new Date("2009-01-03");
        const now = new Date();
        const bitcoinAgeDays = daysBetween(genesisDate, now);
        const trendValue = calculateTrend(
            metadata.trend_a,
            metadata.trend_b,
            bitcoinAgeDays
        );
        const ratioTrend = realtimePrice / trendValue;
        const trendDistance = calculateDistance(ratioTrend);

        // 5. Determine buy zone status
        const isDoubleUndervalued = ratioDCA < 1.0 && ratioTrend < 1.0;

        // 6. Calculate ahr999 index
        const ahr999 = ratioDCA * ratioTrend;
        const ahr999Zone = getAhr999Zone(ahr999);
        const ahr999Percentile = calculateAhr999Percentile(csvData, ahr999);
        const ahr999PercentileBelowOne = calculateAhr999PercentileBelowOne(
            csvData,
            ahr999
        );
        const bottomingVolumeProxy = calculateBottomingVolumeProxy(csvData);
        const rsiContext = calculateRsiContext(csvData);
        const freeBottomingSignals = extractFreeBottomingSignalsFromDailyReport(
            dailyReportSnapshot
        );

        // 7. Format timestamps
        const timestamps = formatTimestamps(timestamp);

        // 8. Display results
        displayResults({
            price: realtimePrice,
            priceSource: priceSource,
            timestamps,
            dcaCost,
            ratioDCA,
            dcaDistance,
            trendValue,
            ratioTrend,
            trendDistance,
            isDoubleUndervalued,
            ahr999,
            ahr999Zone,
            ahr999Percentile,
            ahr999PercentileBelowOne,
            bottomingVolumeProxy,
            rsiContext,
            freeBottomingSignals,
            lastDataDate: csvData[csvData.length - 1].date,
        });
    } catch (error) {
        // Hide placeholder on error
        const placeholderEl = document.getElementById("results-placeholder");
        if (placeholderEl) {
            placeholderEl.classList.add("hidden");
        }

        // Display error
        resultsEl.innerHTML = `
            <div class="error">
                <strong>Error:</strong> ${error.message}
                <br><br>
                ${
                    error.message.includes("CORS")
                        ? "Try enabling CORS proxy in the code (CONFIG.USE_CORS_PROXY = true) or contact the developer."
                        : "Please try again later."
                }
            </div>
        `;
        resultsEl.classList.add("show");
    } finally {
        // Hide loading state
        loadingEl.style.display = "none";
        buttonEl.disabled = false;
    }
}

// ============================================================================
// UI DISPLAY
// ============================================================================

/**
 * Display results in the UI
 * @param {Object} data - Calculation results
 */
function displayResults(data) {
    const resultsEl = document.getElementById("results");
    const placeholderEl = document.getElementById("results-placeholder");

    // Hide placeholder and show results
    if (placeholderEl) {
        placeholderEl.classList.add("hidden");
    }

    // Build compact HTML with Apple-style design
    const html = `
        <div class="status-header ${
            data.isDoubleUndervalued ? "buy" : "no-buy"
        }">
            <h2>${
                data.isDoubleUndervalued
                    ? "✓ Buy Zone Active"
                    : "Not in Buy Zone"
            }</h2>
            <p>${
                data.isDoubleUndervalued
                    ? "Double undervaluation conditions met"
                    : "Waiting for better entry point"
            }</p>
        </div>

        <div class="price-display">
            <div class="price-label">Current Bitcoin Price</div>
            <div class="current-price">
                $${data.price.toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                })}
            </div>
            <div class="price-timestamp">
                As of ${data.timestamps.localTime} (${data.timestamps.localTZ})
            </div>
            ${
                data.priceSource
                    ? `<div class="price-source" style="font-size: 12px; color: #86868b; margin-top: 4px;">Source: ${data.priceSource}</div>`
                    : ""
            }
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <h3>200-Day DCA Cost</h3>
                <div class="metric-value">$${data.dcaCost.toLocaleString(
                    "en-US",
                    { minimumFractionDigits: 2, maximumFractionDigits: 2 }
                )}</div>
                <div class="metric-detail">Ratio: ${data.ratioDCA.toFixed(
                    3
                )}</div>
                <div class="metric-status ${
                    data.dcaDistance.inZone ? "in-zone" : "out-zone"
                }">
                    ${
                        data.dcaDistance.inZone
                            ? `✓ In zone (−${data.dcaDistance.percentage.toFixed(
                                  1
                              )}%)`
                            : `Need −${data.dcaDistance.percentage.toFixed(1)}%`
                    }
                </div>
            </div>

            <div class="metric-card">
                <h3>Power Law Trend</h3>
                <div class="metric-value">$${data.trendValue.toLocaleString(
                    "en-US",
                    { minimumFractionDigits: 2, maximumFractionDigits: 2 }
                )}</div>
                <div class="metric-detail">Ratio: ${data.ratioTrend.toFixed(
                    3
                )}</div>
                <div class="metric-status ${
                    data.trendDistance.inZone ? "in-zone" : "out-zone"
                }">
                    ${
                        data.trendDistance.inZone
                            ? `✓ In zone (−${data.trendDistance.percentage.toFixed(
                                  1
                              )}%)`
                            : `Need −${data.trendDistance.percentage.toFixed(
                                  1
                              )}%`
                    }
                </div>
            </div>

            <div class="metric-card" style="grid-column: span 2;">
                <h3>${data.ahr999Zone.emoji} ahr999 Index</h3>
                <div class="metric-value" style="color: ${
                    data.ahr999Zone.color
                }">${data.ahr999.toFixed(3)}</div>
                <div class="metric-detail">
                    <strong>${data.ahr999Zone.label}</strong> - ${
        data.ahr999Zone.action
    }
                </div>
                <div class="metric-detail" style="margin-top: 8px;">
                    ${data.ahr999Zone.description}
                </div>
                ${
                    data.ahr999Percentile !== null
                        ? `
                    <div class="metric-detail" style="margin-top: 12px;">
                        <strong>Overall Percentile:</strong> ${data.ahr999Percentile.toFixed(
                            1
                        )}th percentile (all history)
                        ${getPercentileInterpretation(data.ahr999Percentile)}
                    </div>
                `
                        : ""
                }
                ${
                    data.ahr999PercentileBelowOne !== null
                        ? `
                    <div class="metric-detail" style="margin-top: 12px;">
                        <strong>Buy Zone Percentile:</strong> ${data.ahr999PercentileBelowOne.toFixed(
                            1
                        )}th percentile (among ahr999 < 1.0 days)
                        ${getBuyZonePercentileInterpretation(
                            data.ahr999PercentileBelowOne
                        )}
                    </div>
                `
                        : `
                    <div class="metric-detail" style="margin-top: 12px;">
                        <strong>Buy Zone Percentile:</strong> N/A (ahr999 ≥ 1.0)
                    </div>
                `
                }
                <div class="metric-detail" style="margin-top: 12px; font-size: 12px; color: #86868b;">
                    < 0.45 = Bottom | < 1.2 = DCA | ≥ 1.2 = Watch
                </div>
            </div>

            ${
                data.bottomingVolumeProxy && data.bottomingVolumeProxy.available
                    ? `
            <div class="metric-card" style="grid-column: span 2;">
                <h3>${data.bottomingVolumeProxy.isPostPanicVolumeContraction ? "✓" : "•"} Bottoming Checklist</h3>
                <div class="metric-detail">
                    <strong>Status:</strong> ${
                        data.bottomingVolumeProxy.isPostPanicVolumeContraction
                            ? "Post-panic volume contraction active"
                            : "No active post-panic contraction"
                    }
                </div>
                <div class="metric-detail" style="margin-top: 8px;">
                    Vol/30D MA: ${
                        Number.isFinite(data.bottomingVolumeProxy.volumeRatio30)
                            ? data.bottomingVolumeProxy.volumeRatio30.toFixed(2) + "x"
                            : "N/A"
                    }
                    · Daily Return (close/close): ${formatPctCompact(data.bottomingVolumeProxy.dailyReturnPct)}
                    · Recent Panic (7D): ${data.bottomingVolumeProxy.recentPanicSelloff7d ? "Yes" : "No"}
                </div>
                <div class="metric-detail" style="margin-top: 10px;">
                    <strong>Checklist (combined):</strong>
                    <br>• DCA condition (${data.ratioDCA.toFixed(3)}): ${data.ratioDCA < 1.0 ? "YES" : "NO"}
                    <br>• Trend condition (${data.ratioTrend.toFixed(3)}): ${data.ratioTrend < 1.0 ? "YES" : "NO"}
                    <br>• AHR999 < 1.0 (${data.ahr999.toFixed(3)}): ${data.ahr999 < 1.0 ? "YES" : "NO"}
                    ${
                        data.rsiContext && data.rsiContext.available
                            ? `<br>• RSI oversold (daily<30 & weekly proxy<=35): ${data.rsiContext.isRsiBottomingSignal ? "YES" : "NO"} (RSI14:${Number.isFinite(data.rsiContext.rsi14) ? data.rsiContext.rsi14.toFixed(1) : "N/A"}, RSI14W proxy:${Number.isFinite(data.rsiContext.rsi14w) ? data.rsiContext.rsi14w.toFixed(1) : "N/A"})`
                            : ""
                    }
                    <br>• Post-panic volume contraction: ${data.bottomingVolumeProxy.isPostPanicVolumeContraction ? "YES" : "NO"}
                    ${
                        data.freeBottomingSignals && data.freeBottomingSignals.available
                            ? `<br>• F&G extreme fear proxy: ${
                                  data.freeBottomingSignals.isExtremeFearProxy ? "YES" : "NO"
                              } (F&G: ${
                                  Number.isFinite(data.freeBottomingSignals.fearGreedValue)
                                      ? data.freeBottomingSignals.fearGreedValue.toFixed(0)
                                      : "N/A"
                              })`
                            : ""
                    }
                    ${
                        data.freeBottomingSignals && data.freeBottomingSignals.available
                            ? `<br>• Miner stress proxy (hashrate 30d): ${
                                  Number.isFinite(data.freeBottomingSignals.hashrate30dChangePct) &&
                                  data.freeBottomingSignals.hashrate30dChangePct <= -5
                                      ? "YES"
                                      : "NO"
                              } (${
                                  Number.isFinite(data.freeBottomingSignals.hashrate30dChangePct)
                                      ? data.freeBottomingSignals.hashrate30dChangePct.toFixed(1) + "%"
                                      : "N/A"
                              })`
                            : ""
                    }
                </div>
                <div class="metric-detail" style="margin-top: 8px; font-size: 12px; color: #86868b;">
                    How to read: Vol/30D MA &lt; 1 = below recent average volume; Recent Panic (7D) = panic selloff detected in the last 7 days; RSI14W proxy = weekly RSI estimated from daily closes.
                </div>
                ${
                    data.freeBottomingSignals && data.freeBottomingSignals.available
                        ? `<div class="metric-detail" style="margin-top: 8px; font-size: 12px; color: #86868b;">
                    F&G = crowd sentiment (lower = more fear). Current: ${
                        data.freeBottomingSignals.fearGreedClassification || "N/A"
                    } · Miner stress proxy = hashrate trend proxy. Current: ${
                        data.freeBottomingSignals.minerStressProxy || "N/A"
                    }
                </div>`
                        : ""
                }
            </div>
            `
                    : ""
            }
        </div>

        ${
            !data.isDoubleUndervalued
                ? `
            <div class="distance-info">
                <h4>To Enter Buy Zone</h4>
                ${getBuyZoneAnalysis(data)}
            </div>
        `
                : ""
        }
    `;

    resultsEl.innerHTML = html;
    resultsEl.classList.add("show");
}

/**
 * Get interpretation for ahr999 percentile
 * @param {number} percentile
 * @returns {string} HTML string with interpretation
 */
function getPercentileInterpretation(percentile) {
    if (percentile < 10) {
        return `<br><span style="color: #28a745;">🔥 EXCEPTIONAL - Only ${percentile.toFixed(
            1
        )}% of history was cheaper!</span>`;
    } else if (percentile < 25) {
        return `<br><span style="color: #28a745;">💎 EXCELLENT - Only ${percentile.toFixed(
            1
        )}% of history was cheaper!</span>`;
    } else if (percentile < 50) {
        return `<br><span style="color: #0071e3;">✅ GOOD - Better than ${(
            100 - percentile
        ).toFixed(0)}% of historical days</span>`;
    } else if (percentile < 75) {
        return `<br><span style="color: #ff9500;">⚠️ FAIR - More expensive than ${percentile.toFixed(
            0
        )}% of history</span>`;
    } else {
        return `<br><span style="color: #ff3b30;">🔴 EXPENSIVE - More expensive than ${percentile.toFixed(
            0
        )}% of history</span>`;
    }
}

/**
 * Get interpretation for buy zone percentile (among ahr999 < 1.0 days)
 * @param {number} percentile
 * @returns {string} HTML string with interpretation
 */
function getBuyZonePercentileInterpretation(percentile) {
    if (percentile < 10) {
        return `<br><span style="color: #28a745;">🔥 Top 10% opportunity among buy zone days!</span>`;
    } else if (percentile < 25) {
        return `<br><span style="color: #28a745;">💎 Top 25% opportunity among buy zone days</span>`;
    } else if (percentile < 50) {
        return `<br><span style="color: #0071e3;">✅ Better than average among buy zone days</span>`;
    } else {
        return `<br><span style="color: #ff9500;">⚠️ Below average among buy zone days</span>`;
    }
}

/**
 * Generate buy zone analysis text
 * @param {Object} data
 * @returns {string} HTML string
 */
function getBuyZoneAnalysis(data) {
    const dcaInZone = data.dcaDistance.inZone;
    const trendInZone = data.trendDistance.inZone;

    if (!dcaInZone && !trendInZone) {
        // Both need to drop
        const maxDrop = Math.max(
            data.dcaDistance.percentage,
            data.trendDistance.percentage
        );
        return `<p>Price needs to drop <strong>${maxDrop.toFixed(
            1
        )}%</strong> to enter zone</p>`;
    } else if (dcaInZone && !trendInZone) {
        // Only trend needs to drop
        return `
            <p>✓ DCA condition met</p>
            <p>Need <strong>${data.trendDistance.percentage.toFixed(
                1
            )}%</strong> more drop for trend</p>
        `;
    } else if (!dcaInZone && trendInZone) {
        // Only DCA needs to drop
        return `
            <p>✓ Trend condition met</p>
            <p>Need <strong>${data.dcaDistance.percentage.toFixed(
                1
            )}%</strong> more drop for DCA</p>
        `;
    }

    return "";
}

// ============================================================================
// INITIALIZATION
// ============================================================================

// Add event listener when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
    const buttonEl = document.getElementById("checkButton");
    buttonEl.addEventListener("click", checkRealtimeStatus);
});
