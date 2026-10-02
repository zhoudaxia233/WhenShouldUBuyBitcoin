"""
Look-ahead-free comparison of DCA weighting signals.

Each strategy deposits the same daily budget into a cash account and buys
``budget × multiplier`` worth of BTC (limited by the cash it has), so every
strategy contributes the same money; unspent cash counts at face value.

Signals are computed only from data available on each day:
- the power-law trend is refitted every day on prices up to that day
- percentiles rank today's value against the signal's own history so far

The site's current ahr999 (trend fitted on all data, percentiles over the whole
history) is kept as ``ahr999_lookahead`` to measure how much that look-ahead
flatters the result.
"""

from __future__ import annotations

import bisect
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import BITCOIN_GENESIS, causal_power_law_trend, fit_exponential_trend

GENESIS = BITCOIN_GENESIS

# Percentile upper bound -> buy multiplier; the site's default ahr999
# percentile strategy (cheapest 10%: 5x, 10-25%: 2x, 25-50%: 1x, else 0x).
DEFAULT_TIERS = ((10.0, 5.0), (25.0, 2.0), (50.0, 1.0), (100.0, 0.0))

STRATEGIES = {
    "plain_dca": "Plain DCA",
    "ahr999": "ahr999 weighted (no look-ahead)",
    "ahr999_lookahead": "ahr999 weighted (site's current, uses future data)",
    "mayer": "Mayer multiple weighted",
    "mvrv": "MVRV weighted",
}


# ---- Signals ----

def harmonic_dca_cost(prices, window: int = 200) -> np.ndarray:
    """200-day DCA cost: the harmonic mean of the last ``window`` prices."""
    inverse = pd.Series(1.0 / np.asarray(prices, dtype=float))
    return (window / inverse.rolling(window).sum()).to_numpy()


def mayer_multiple(prices, window: int = 200) -> np.ndarray:
    """Price divided by its simple moving average over ``window`` days."""
    series = pd.Series(np.asarray(prices, dtype=float))
    return (series / series.rolling(window).mean()).to_numpy()


def expanding_percentile(values, min_history: int = 365) -> np.ndarray:
    """Share (0-100) of values so far, today included, at or below today's.

    Missing values are skipped; days with fewer than ``min_history`` known
    values get NaN.
    """
    values = np.asarray(values, dtype=float)
    seen: list[float] = []
    out = np.full(len(values), np.nan)
    for i, value in enumerate(values):
        if not np.isfinite(value):
            continue
        bisect.insort(seen, value)
        if len(seen) >= min_history:
            out[i] = 100.0 * bisect.bisect_right(seen, value) / len(seen)
    return out


def known_rank(series: pd.Series, min_history: int = 1) -> pd.Series:
    """Rank (0-1) of each value among the values known up to that day."""
    pct = expanding_percentile(pd.to_numeric(series, errors="coerce").to_numpy(dtype=float), min_history)
    return pd.Series(pct / 100.0, index=series.index)


def full_sample_percentile(values) -> np.ndarray:
    """Percentile against the whole series, future included (the look-ahead)."""
    series = pd.Series(np.asarray(values, dtype=float))
    return (series.rank(method="max", pct=True) * 100.0).to_numpy()


def tier_multipliers(percentiles, tiers=DEFAULT_TIERS) -> np.ndarray:
    """Buy multiplier for each percentile; unknown percentiles buy the base 1x."""
    percentiles = np.asarray(percentiles, dtype=float)
    out = np.ones(len(percentiles))
    known = np.isfinite(percentiles)
    for i in np.flatnonzero(known):
        for upper, multiplier in tiers:
            if percentiles[i] <= upper:
                out[i] = multiplier
                break
    return out


def build_signals(
    prices: pd.DataFrame,
    mvrv: Optional[pd.DataFrame] = None,
    trend_min_points: int = 730,
    percentile_min_history: int = 365,
) -> pd.DataFrame:
    """Daily prices with each strategy's buy multiplier, all computed causally."""
    df = prices[["date", "close_price"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["close_price"]).sort_values("date").reset_index(drop=True)
    price = df["close_price"].to_numpy(dtype=float)

    dca_cost = harmonic_dca_cost(price)
    causal_trend = causal_power_law_trend(df["date"], price, min_points=trend_min_points)
    df["ahr999"] = (price / dca_cost) * (price / causal_trend)

    full_trend, _, _ = fit_exponential_trend(df, price_col="close_price")
    df["ahr999_full_sample"] = (price / dca_cost) * (price / full_trend.to_numpy())
    df["mayer"] = mayer_multiple(price)

    if mvrv is not None and not mvrv.empty:
        m = mvrv[["date", "mvrv"]].copy()
        m["date"] = pd.to_datetime(m["date"])
        df = df.merge(m, on="date", how="left")
    else:
        df["mvrv"] = np.nan

    df["mult_plain_dca"] = 1.0
    df["mult_ahr999"] = tier_multipliers(expanding_percentile(df["ahr999"], percentile_min_history))
    df["mult_ahr999_lookahead"] = tier_multipliers(full_sample_percentile(df["ahr999_full_sample"]))
    df["mult_mayer"] = tier_multipliers(expanding_percentile(df["mayer"], percentile_min_history))
    df["mult_mvrv"] = tier_multipliers(expanding_percentile(df["mvrv"], percentile_min_history))
    df["mvrv_signal_ready"] = np.isfinite(expanding_percentile(df["mvrv"], percentile_min_history))
    return df


# ---- Simulation ----

def simulate(prices, multipliers, daily_budget: float = 10.0) -> dict:
    """Run one strategy through a cash account; see the module docstring."""
    prices = np.asarray(prices, dtype=float)
    multipliers = np.asarray(multipliers, dtype=float)
    cash = btc = spent = idle = 0.0
    for price, multiplier in zip(prices, multipliers):
        cash += daily_budget
        spend = min(cash, daily_budget * multiplier)
        if spend > 0:
            btc += spend / price
            spent += spend
            cash -= spend
        idle += cash
    contributed = daily_budget * len(prices)
    wealth = btc * prices[-1] + cash
    # Average share of the money paid in so far that sat in cash
    deposits = daily_budget * np.arange(1, len(prices) + 1)
    return {
        "contributed": contributed,
        "btc": btc,
        "cash": cash,
        "wealth": wealth,
        "wealth_multiple": wealth / contributed,
        "avg_cost": spent / btc if btc else np.nan,
        "idle_cash_share": idle / deposits.sum(),
    }


def compare_strategies(
    window: pd.DataFrame, daily_budget: float = 10.0, strategies=None
) -> pd.DataFrame:
    """The strategies (all by default) over one window, with the gain over plain DCA."""
    prices = window["close_price"].to_numpy(dtype=float)
    keys = ["plain_dca"] + [k for k in (strategies or STRATEGIES) if k != "plain_dca"]
    rows = []
    for key in keys:
        label = STRATEGIES[key]
        result = simulate(prices, window[f"mult_{key}"].to_numpy(), daily_budget)
        rows.append({"strategy": key, "label": label, **result})
    table = pd.DataFrame(rows)
    plain = table.loc[table["strategy"] == "plain_dca", "wealth"].iloc[0]
    table["vs_plain_pct"] = (table["wealth"] / plain - 1.0) * 100.0
    return table


def rolling_windows(
    signals: pd.DataFrame,
    start,
    horizon_days: int = 4 * 365,
    step_days: int = 182,
) -> list[pd.DataFrame]:
    """Windows of ``horizon_days`` starting every ``step_days`` from ``start``."""
    start = pd.Timestamp(start)
    last = signals["date"].iloc[-1]
    windows = []
    while start + pd.Timedelta(days=horizon_days - 1) <= last:
        end = start + pd.Timedelta(days=horizon_days - 1)
        window = signals[(signals["date"] >= start) & (signals["date"] <= end)]
        if len(window) and (window["date"].iloc[-1] - window["date"].iloc[0]).days == horizon_days - 1:
            windows.append(window.reset_index(drop=True))
        start += pd.Timedelta(days=step_days)
    return windows
