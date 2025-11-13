# When Should U Buy Bitcoin

A Python application for Bitcoin valuation analysis using DCA cost and exponential trend analysis.

## Project Status

**Current: Step 5 MVP Complete ✓**
- ✓ Basic data fetching from Yahoo Finance
- ✓ 200-day DCA cost calculation
- ✓ Exponential trend fitting
- ✓ Combined valuation metrics & "double undervaluation" detection
- ✓ Data persistence (CSV storage for efficient updates)
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

### Step 5: Full Analysis with Data Persistence

Run the main script to perform full Bitcoin valuation analysis with CSV storage:

```bash
python main.py
```

**First run:**
- Fetches ~2000 days of BTC price history from Yahoo Finance
- Calculates all valuation metrics
- Saves to `data/btc_metrics.csv`

**Subsequent runs (efficient updates):**
- Loads existing data from CSV
- Only fetches recent days (not full 2000 days!)
- Merges and recalculates metrics
- Updates the CSV file

**What it shows:**
- 200-day DCA cost analysis
- Exponential trend model with growth rates
- **Double Undervaluation buy zones** (Price < DCA AND Price < Trend)
- Historical statistics and buy zone periods
- Current valuation status

## Project Structure

```
.
├── src/
│   └── whenshouldubuybitcoin/
│       ├── __init__.py
│       ├── data_fetcher.py      # Yahoo Finance integration
│       ├── metrics.py           # DCA cost & valuation metrics
│       └── persistence.py       # CSV storage & loading
├── data/
│   └── btc_metrics.csv          # Stored historical metrics (auto-generated)
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

## Next Steps

After Step 5, we'll implement:
- **Step 6**: Daily update mechanism + check if in buy zone
- **Step 7**: Email notifications when BTC enters double undervaluation buy zone
- **Step 8**: Backtesting to compare strategies:
  - Double undervaluation buy strategy
  - Buy & Hold from start
  - Daily DCA strategy

## License

See LICENSE file.
