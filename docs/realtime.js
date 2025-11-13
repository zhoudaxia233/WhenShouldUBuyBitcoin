/**
 * Real-time Bitcoin Buy Zone Checker
 *
 * This JavaScript implementation mirrors the Python version but runs entirely in the browser.
 * It fetches real-time BTC prices from Yahoo Finance and calculates buy zone status.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

const CONFIG = {
    // Yahoo Finance API endpoint for BTC-USD
    YAHOO_API:
        "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1m&range=1d",

    // CORS proxy (needed if Yahoo Finance blocks direct browser access)
    // You can use: https://corsproxy.io/ or https://cors-anywhere.herokuapp.com/
    USE_CORS_PROXY: true,
    CORS_PROXY: "https://corsproxy.io/?",

    // Data paths (relative to the docs folder)
    DATA_CSV: "data/btc_metrics.csv",
    DATA_METADATA: "data/btc_metadata.json",

    // DCA window
    DCA_WINDOW: 200,
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

// ============================================================================
// YAHOO FINANCE API
// ============================================================================

/**
 * Fetch real-time BTC price from Yahoo Finance
 * @returns {Promise<Object>} Object with price and timestamp
 */
async function fetchRealtimeBTCPrice() {
    try {
        // Construct URL (with or without CORS proxy)
        const url = CONFIG.USE_CORS_PROXY
            ? CONFIG.CORS_PROXY + encodeURIComponent(CONFIG.YAHOO_API)
            : CONFIG.YAHOO_API;

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        // Extract price and timestamp from Yahoo Finance response
        const result = data.chart.result[0];
        const meta = result.meta;

        // Get the latest price (regularMarketPrice)
        const price = meta.regularMarketPrice;

        // Get timestamp (current time in UTC)
        const timestamp = new Date();

        return {
            price: price,
            timestamp: timestamp,
        };
    } catch (error) {
        console.error("Error fetching Yahoo Finance data:", error);

        // If CORS error, suggest enabling proxy
        if (
            error.message.includes("CORS") ||
            error.message.includes("Failed to fetch")
        ) {
            throw new Error(
                "CORS error - Yahoo Finance blocked browser access. Enable CORS proxy or use alternative data source."
            );
        }

        throw error;
    }
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
 * Calculate exponential trend value
 *
 * Formula: trend = a * exp(b * days)
 *
 * @param {number} a - Trend coefficient
 * @param {number} b - Growth rate (per day)
 * @param {number} daysSinceStart - Days since first date in dataset
 * @returns {number} Trend value
 */
function calculateTrend(a, b, daysSinceStart) {
    return a * Math.exp(b * daysSinceStart);
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

    return {
        utc: utcString,
        berlin: berlinString,
        berlinTZ: berlinTZ,
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

    try {
        // Show loading state
        loadingEl.style.display = "block";
        resultsEl.classList.remove("show");
        buttonEl.disabled = true;

        // 1. Load historical data
        console.log("Loading historical data...");
        const csvData = await loadCSVData();
        const metadata = await loadMetadata();

        // Extract close prices from CSV
        const historicalPrices = csvData.map((row) =>
            parseFloat(row.close_price)
        );

        // Get first date for day calculation
        const firstDate = new Date(csvData[0].date);

        // 2. Fetch real-time price
        console.log("Fetching real-time BTC price...");
        const { price: realtimePrice, timestamp } =
            await fetchRealtimeBTCPrice();

        // 3. Calculate DCA
        // Use last 199 days + today's real-time price
        const last199 = historicalPrices.slice(-199);
        const prices200 = [...last199, realtimePrice];
        const dcaCost = calculateDCA(prices200);
        const ratioDCA = realtimePrice / dcaCost;
        const dcaDistance = calculateDistance(ratioDCA);

        // 4. Calculate Trend
        const now = new Date();
        const daysSinceStart = daysBetween(firstDate, now);
        const trendValue = calculateTrend(
            metadata.trend_a,
            metadata.trend_b,
            daysSinceStart
        );
        const ratioTrend = realtimePrice / trendValue;
        const trendDistance = calculateDistance(ratioTrend);

        // 5. Determine buy zone status
        const isDoubleUndervalued = ratioDCA < 1.0 && ratioTrend < 1.0;

        // 6. Format timestamps
        const timestamps = formatTimestamps(timestamp);

        // 7. Display results
        displayResults({
            price: realtimePrice,
            timestamps,
            dcaCost,
            ratioDCA,
            dcaDistance,
            trendValue,
            ratioTrend,
            trendDistance,
            isDoubleUndervalued,
            lastDataDate: csvData[csvData.length - 1].date,
        });
    } catch (error) {
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

        <div class="timestamp">
            Real-time: $${data.price.toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            })} 
            • UTC: ${data.timestamps.utc} • Berlin: ${data.timestamps.berlin} ${
        data.timestamps.berlinTZ
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
                <h3>Exponential Trend</h3>
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
