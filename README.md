# When Should You Buy Bitcoin

A quantitative approach to identify Bitcoin buying opportunities using two independent valuation metrics.

---

## 🎯 The Strategy

Bitcoin enters a **Double Undervaluation Buy Zone** when **BOTH** conditions are met:

1. **Price < 200-Day DCA Cost** - Current price is cheaper than the average cost of consistent buyers over the past 6-7 months
2. **Price < Power Law Trend** - Current price is below Bitcoin's long-term fundamental value based on network growth effects

Using two independent metrics reduces false signals and identifies stronger buying opportunities.

---

## 📊 Website

**[When Should U Buy Bitcoin](https://zhoudaxia233.github.io/WhenShouldUBuyBitcoin/)**

### Features

- **Historical Charts** - Visualize when Bitcoin has been in the buy zone
- **Real-Time Check** - Get current valuation status
- **Future Price Forecast** - Calculate predicted Bitcoin price on any future date
- **Strategy Backtesting** - Test different investment strategies with historical data
- **Distance to Buy Zone** - See how much Bitcoin needs to drop to enter the zone

### Data Updates

- Historical data update workflow is currently **manual trigger only** (`workflow_dispatch`); cron schedule is intentionally commented out
- DCA service real-time checks fetch **live BTC price** from the configured active exchange, then fall back to Coinbase with the fallback source labeled
- Historical charts and daily summaries use the generated files in `docs/data/`; check each page's displayed update timestamp before treating non-price metrics as current.

### Local DCA Service (Poetry)

- Start/restart backend on port 8000:
```bash
lsof -i :8000 | awk 'NR!=1 {print $2}' | xargs kill -9; poetry run uvicorn dca_service.main:app --reload
```
- Run DCA service tests with Poetry:
```bash
poetry run pytest dca_service/tests -v
```

### Macro Risk Score (Quick Config)

The chart `Macro Risk Score` is a weighted blend of macro stress signals:

- Net Liquidity 90D change
- SOFR
- MOVE
- HY OAS

Default weights are defined in:

- `src/whenshouldubuybitcoin/visualization.py` -> `MACRO_RISK_SCORE_WEIGHTS`

Current defaults:

- `net_liquidity_90d_change`: `0.35`
- `sofr`: `0.20`
- `move`: `0.20`
- `hy_oas`: `0.25`

To quickly tune weights:

1. Edit `MACRO_RISK_SCORE_WEIGHTS` in `visualization.py`
2. Regenerate charts:

```bash
poetry run python main.py
```

---

## 🎮 Strategy Backtesting

Test different Bitcoin investment strategies without risking real money. All calculations run entirely in your browser.

### Available Strategies

#### 1. Daily DCA
Invest the same amount every day. Simple and consistent.

#### 2. Monthly DCA
Invest your full monthly budget on a specific day each month (1-28). More realistic for most investors.

#### 3. AHR999 Historical Percentile
Dynamically adjust investment based on where current AHR999 ranks historically. Buy more when Bitcoin is cheaper.

**Default Multipliers:**
- **Bottom 10%** (EXTREME CHEAP): 5x daily investment
- **10-25%** (Very Cheap): 2x daily investment
- **25-50%** (Cheap): 1x daily investment
- **50-75%** (Fair): 0x (no investment)
- **75-90%** (Expensive): 0x (no investment)
- **Top 10%** (VERY EXPENSIVE): 0x (no investment)

**Features:**
- Fully customizable multipliers for each percentile tier
- Real-time display of daily investment amounts
- Unlimited budget mode option (ignore total budget constraints)
- Only available for historical backtests (requires AHR999 data)

### Results

- Total invested, final BTC balance, portfolio value
- Total return (%) and annualized return (%)
- Interactive chart showing portfolio growth over time
- Detailed transaction history with AHR999 values

---

## 🔬 Methodology

### 200-Day DCA Cost
```
DCA Cost = 200 / Σ(1/price_i)
```
Harmonic mean of the last 200 daily closing prices.

### Power Law Trend Model
```
Trend = a × days^n
```
Fitted via linear regression on log-log transformed data. Models network effects (Metcalfe's Law) with decreasing growth rate over time.

---

## ⚠️ Disclaimer

This tool is for educational purposes only. Do your own research before making investment decisions.
