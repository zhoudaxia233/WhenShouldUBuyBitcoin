#!/usr/bin/env python3
"""
Compare DCA weighting signals without look-ahead.

Usage:
    poetry run python scripts/compare_dca_signals.py [--output report.md]

Reads docs/data/btc_metrics.csv (prices) and docs/data/onchain_metrics.csv
(MVRV), and prints a Markdown report: rolling 4-year windows, the full period,
and the shorter period where MVRV data exists.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from whenshouldubuybitcoin import signal_backtest as sb  # noqa: E402

COMPARED = ["ahr999", "ahr999_lookahead", "mayer"]


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _strategy_table(table: pd.DataFrame) -> list[str]:
    lines = [
        "| Strategy | Wealth ÷ paid in | vs plain DCA | Avg. buy price | Avg. idle cash |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in table.itertuples():
        lines.append(
            f"| {row.label} | {row.wealth_multiple:.2f}× | {_pct(row.vs_plain_pct)} | "
            f"${row.avg_cost:,.0f} | {row.idle_cash_share * 100:.0f}% |"
        )
    return lines


def build_report(prices: pd.DataFrame, mvrv: pd.DataFrame) -> str:
    signals = sb.build_signals(prices, mvrv)
    ready = np.isfinite(sb.expanding_percentile(signals["ahr999"]))
    first_ready = signals.loc[ready, "date"].iloc[0]
    last = signals["date"].iloc[-1]

    lines = [
        "# DCA weighting signals without look-ahead",
        "",
        f"Prices {signals['date'].iloc[0]:%Y-%m-%d} to {last:%Y-%m-%d}. "
        f"Causal ahr999 and Mayer signals are available from {first_ready:%Y-%m-%d} "
        "(two years to fit the trend, then one year of signal history).",
        "",
        "Every strategy pays in the same amount each day; unspent cash is kept and "
        "counted at face value. Weighted strategies buy 5× / 2× / 1× / 0× the daily "
        "amount when the signal is in its cheapest 10% / 10–25% / 25–50% / rest, "
        "ranked against its own history up to that day.",
        "",
    ]

    windows = sb.rolling_windows(signals, start=first_ready, horizon_days=4 * 365, step_days=182)
    lines += [f"## Rolling 4-year windows ({len(windows)}, started every 6 months)", ""]
    lines += ["| Start | " + " | ".join(sb.STRATEGIES[k] for k in COMPARED) + " |",
              "|---|" + "---:|" * len(COMPARED)]
    results = {k: [] for k in COMPARED}
    for window in windows:
        table = sb.compare_strategies(window).set_index("strategy")
        for k in COMPARED:
            results[k].append(table.loc[k, "vs_plain_pct"])
        lines.append(f"| {window['date'].iloc[0]:%Y-%m-%d} | " + " | ".join(_pct(table.loc[k, 'vs_plain_pct']) for k in COMPARED) + " |")
    lines += ["", "Gain over plain DCA across windows (windows overlap, so they are not independent):", "",
              "| Strategy | Median | Worst | Best | Beat plain DCA |", "|---|---:|---:|---:|---:|"]
    for k in COMPARED:
        values = np.array(results[k])
        lines.append(f"| {sb.STRATEGIES[k]} | {_pct(np.median(values))} | {_pct(values.min())} | "
                     f"{_pct(values.max())} | {int((values > 0).sum())} of {len(values)} |")

    full = signals[signals["date"] >= first_ready].reset_index(drop=True)
    lines += ["", f"## Whole period {first_ready:%Y-%m-%d} to {last:%Y-%m-%d}", ""]
    lines += _strategy_table(sb.compare_strategies(full, strategies=COMPARED))

    mvrv_ready = signals.loc[signals["mvrv_signal_ready"], "date"]
    if len(mvrv_ready):
        start = mvrv_ready.iloc[0]
        window = signals[signals["date"] >= start].reset_index(drop=True)
        lines += ["", f"## Period with MVRV data, {start:%Y-%m-%d} to {last:%Y-%m-%d}", "",
                  f"MVRV history starts {mvrv['date'].min()}; the free data source keeps about four years. "
                  "This is one short window inside a single market cycle, and MVRV is ranked against "
                  "only one year of its own history at the start, so treat it as a sanity check only.", ""]
        lines += _strategy_table(sb.compare_strategies(window))

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, help="Write the Markdown report to this file")
    args = parser.parse_args()

    prices = pd.read_csv(ROOT / "docs" / "data" / "btc_metrics.csv", usecols=["date", "close_price"])
    onchain_path = ROOT / "docs" / "data" / "onchain_metrics.csv"
    mvrv = pd.read_csv(onchain_path, usecols=["date", "mvrv"]).dropna() if onchain_path.exists() else pd.DataFrame()

    report = build_report(prices, mvrv)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
