# When Should U Buy Bitcoin

A Python application for Bitcoin valuation analysis using DCA cost and exponential trend analysis.

## Project Status

**Current: Step 5+ MVP Complete ✓**
- ✓ Basic data fetching from Yahoo Finance
- ✓ 200-day DCA cost calculation
- ✓ Exponential trend fitting
- ✓ Combined valuation metrics & "double undervaluation" detection
- ✓ Data persistence (CSV storage for efficient updates)
- ✓ Interactive visualizations (Plotly charts)
- ⏳ Daily updates & notifications (Step 6)
- ⏳ Email notifications (Step 7)
- ⏳ Backtesting (Step 8)

## Setup

### Prerequisites
- Python 3.10+
- Poetry

### Installation

1. Install dependencies:
```bash
poetry install
```

2. Activate the virtual environment:
```bash
poetry shell
```

## Usage

### Full Analysis (Default)

Run the main script to perform full Bitcoin valuation analysis with CSV storage:

```bash
python main.py
```

**First run:**
- Fetches ~2000 days of BTC price history from Yahoo Finance
- Calculates all valuation metrics
- Saves to `data/btc_metrics.csv`
- Generates 3 interactive charts

**Subsequent runs (efficient updates):**
- Loads existing data from CSV
- Only fetches recent days (not full 2000 days!)
- Merges and recalculates metrics
- Updates the CSV file
- Regenerates charts

**What it shows:**
- 200-day DCA cost analysis
- Exponential trend model with growth rates
- **Double Undervaluation buy zones** (Price < DCA AND Price < Trend)
- Historical statistics and buy zone periods
- Current valuation status
- **3 interactive charts** (automatically generated and opened in browser):
  - Valuation ratios over time with buy zones highlighted
  - Price comparison (actual vs DCA vs Trend)
  - Historical statistics by year

### Real-Time Buy Zone Check (CLI) ⚡

Quickly check if Bitcoin is currently in a buy zone without running the full analysis:

```bash
python main.py --check-now
# or
python main.py --realtime
```

**Use cases:**
- 📰 News of a market crash - check immediately if it's a buy opportunity
- 🚨 Black swan events - evaluate real-time without waiting for daily close
- 📊 Intraday monitoring - see current status during high volatility

**What it shows:**
- Real-time BTC price (latest available)
- Timestamp in both UTC and Berlin time
- Current Price/DCA and Price/Trend ratios
- **Buy zone status for each metric**
- **Distance to buy zone**: Shows exactly how much BTC needs to drop to enter buy zone
- Overall double undervaluation status
- Warning that this is a real-time estimate (wait for daily close to confirm)

**Example output:**
```
📡 Fetching real-time BTC price...
   ✓ Success
      UTC:    2025-11-13 19:39:00
      Berlin: 2025-11-13 20:39:00 CET

💰 CURRENT STATUS
  Real-time BTC Price:  $45,230
  Time (UTC):           2025-11-13 19:39:00
  Time (Berlin):        2025-11-13 20:39:00 CET

📊 VALUATION METRICS
  🔵 200-Day DCA Cost:   $48,500
     Status:             ❌ Above threshold
     Distance:           Need 6.74% drop to enter zone

  🟢 Exponential Trend:  $43,200
     Status:             ✅ IN BUY ZONE (below by 4.68%)

🎯 DOUBLE UNDERVALUATION STATUS
  🔴 NOT in double undervaluation buy zone

  ✓ Trend condition already met
  📉 Need 6.74% more drop for DCA condition
```

### Real-Time Buy Zone Check (Web) 🌐 NEW!

**Browser-based real-time checker** - No Python installation needed!

#### Live Demo (after deploying to GitHub Pages):
```
https://<your-username>.github.io/<repo-name>/
```

#### Local Testing:
```bash
cd docs
python -m http.server 8000
# Open http://localhost:8000
```

**Features:**
- ✅ Pure JavaScript implementation (runs entirely in browser)
- ✅ Fetches real-time BTC price from Yahoo Finance
- ✅ Calculates buy zone status instantly
- ✅ Shows distance to buy zone
- ✅ Displays time in UTC and Berlin (CET/CEST)
- ✅ Responsive design, works on mobile
- ✅ **Reuses the same data files** (btc_metrics.csv & btc_metadata.json)

**How it works:**
1. Python script (via GitHub Actions) updates data daily
2. Web interface loads historical data from CSV/JSON
3. User clicks button → fetches real-time price → calculates instantly
4. No backend server needed!

See `docs/README.md` for detailed setup and deployment instructions.

## Project Structure

```
.
├── .github/
│   └── workflows/
│       └── update-data.yml      # GitHub Actions for daily updates
├── src/
│   └── whenshouldubuybitcoin/
│       ├── __init__.py
│       ├── data_fetcher.py      # Yahoo Finance integration
│       ├── metrics.py           # DCA cost & valuation metrics
│       ├── persistence.py       # CSV & JSON storage/loading
│       ├── visualization.py     # Interactive Plotly charts
│       └── realtime_check.py    # Real-time CLI checking
├── docs/                         # Web interface (GitHub Pages)
│   ├── index.html               # Main webpage
│   ├── realtime.js              # Pure JavaScript implementation
│   └── README.md                # Web interface documentation
├── data/
│   ├── btc_metrics.csv          # Historical metrics (auto-generated)
│   └── btc_metadata.json        # Trend parameters (auto-generated)
├── charts/                       # Interactive charts (auto-generated)
│   ├── valuation_ratios.html
│   ├── price_comparison.html
│   └── double_uv_stats.html
├── main.py                       # CLI entry point
├── pyproject.toml               # Poetry dependencies
└── README.md
```

## Development

### Code Quality Tools

Format code:
```bash
poetry run black .
```

Lint code:
```bash
poetry run ruff check .
```

Run tests:
```bash
poetry run pytest
```

## Data Source

**Yahoo Finance via yfinance library**:
- Free, no authentication required
- No rate limits for reasonable use
- Reliable historical data back to 2014 for BTC-USD
- Perfect for daily price data

## Features

### Data Persistence
- Historical metrics stored in `data/btc_metrics.csv`
- Efficient updates: only fetches recent data on subsequent runs
- Automatic merging of new and existing data
- No duplicate dates

### Valuation Metrics
- **200-day DCA Cost**: Short-term valuation (harmonic mean of last 200 days)
- **Exponential Trend**: Long-term growth model fitted to all historical data
- **Double Undervaluation**: Buy zone when BOTH metrics show undervaluation

### Interactive Visualizations
- **Valuation Ratios Chart**: Shows Price/DCA and Price/Trend ratios over time
  - Red shaded areas highlight double undervaluation buy zones
  - Horizontal line at ratio = 1.0 (fair value)
  - Zoom, pan, hover for details
- **Price Comparison Chart**: Actual BTC price vs DCA cost vs Exponential trend
  - Log scale to show exponential growth clearly
  - Red dots mark buy zone days
- **Statistics Chart**: Historical analysis by year
  - Number of buy zone days per year
  - Percentage of time in buy zone
- All charts are interactive HTML files (Plotly)
- Auto-open in browser on first generation

### Real-Time Monitoring ⚡
- **Quick buy zone check** without waiting for daily close
- Fetches current BTC price (intraday, minute-level updates)
- Calculates real-time DCA and Trend ratios
- **Distance calculation**: Shows exactly how much price needs to drop to enter buy zone
- Useful for:
  - Black swan events / market crashes
  - Breaking news evaluation
  - Intraday monitoring during high volatility
- Fast execution (no full data refresh needed)

## Deployment to GitHub Pages

### Quick Setup

1. **Enable GitHub Pages:**
   - Go to repository Settings → Pages
   - Source: Branch `main`, Folder `/docs`
   - Save

2. **Enable GitHub Actions:**
   - Go to repository Settings → Actions → General
   - Allow all actions and reusable workflows

3. **First Run:**
   - Manually run the workflow: Actions → "Update BTC Data Daily" → Run workflow
   - Or wait for the daily schedule (00:30 UTC)

4. **Access Your Site:**
   - Visit: `https://<username>.github.io/<repo-name>/`
   - Click the button to check real-time buy zone status!

### Automatic Updates

- GitHub Actions runs daily at 00:30 UTC
- Updates data and charts automatically
- Commits changes back to repository
- GitHub Pages redeploys automatically

## Next Steps

After the web interface, we can implement:
- **Step 6**: Daily update mechanism + check if in buy zone
- **Step 7**: Email notifications when BTC enters double undervaluation buy zone
- **Step 8**: Backtesting to compare strategies:
  - Double undervaluation buy strategy
  - Buy & Hold from start
  - Daily DCA strategy

## License

See LICENSE file.
