# When Should You Buy Bitcoin

A quantitative approach to identify Bitcoin buying opportunities using two independent valuation metrics.

---

## 🎯 The Strategy

Bitcoin enters a **Double Undervaluation Buy Zone** when **BOTH** conditions are met:

### 1. Price < 200-Day DCA Cost
The harmonic mean of Bitcoin's price over the past 200 days. This represents the average cost if you had been dollar-cost-averaging with a fixed USD amount daily.

**When price drops below this level:** The current price is cheaper than the average cost of consistent buyers over the past 6-7 months.

### 2. Price < Exponential Trend
A long-term exponential growth model fitted to all historical price data. This represents Bitcoin's fundamental fair value based on its growth trajectory.

**When price drops below this level:** The current price is below Bitcoin's long-term trend, suggesting undervaluation relative to historical growth patterns.

---

## 💡 Why Both Conditions Matter

Using **two independent metrics** reduces false signals:

- **DCA Cost** reflects recent market sentiment (200-day window)
- **Exponential Trend** reflects long-term fundamental value (all history)

When both signal undervaluation simultaneously, it suggests a stronger buying opportunity.

---

## 📊 How to Use

**Website:** [When Should U Buy Bitcoin](https://zhoudaxia233.github.io/WhenShouldUBuyBitcoin/)

### What You'll See

1. **Historical Chart**: Visualize when Bitcoin has been in the buy zone historically
2. **Real-Time Check**: Click the button to get current valuation status
3. **Distance to Buy Zone**: See how much Bitcoin would need to drop (or if you're already in the zone)

### Data Updates

- Historical data updates **daily at 00:30 UTC** via automated script
- Real-time check fetches **live price** directly from Yahoo Finance

---

## ⚠️ Important Disclaimer

Do your own research!

---

## 🔬 Methodology

### 200-Day DCA Cost Calculation
```
DCA Cost = 200 / Σ(1/price_i)
```
Harmonic mean of the last 200 daily closing prices.

### Exponential Trend Model
```
Trend = a × e^(b × days)
```
Fitted via linear regression on log-transformed prices across all historical data.

---

**Built with:** Python, Plotly, JavaScript • **Data Source:** Yahoo Finance
