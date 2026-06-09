"""
On-chain bottom-signal scoring and backtest.

Five signals scored 0-20 each sum to a 0-100 composite:
  S1 price vs holder cost-basis lines, S2 MVRV sigma deviation,
  S3 supply-in-loss sigma deviation, S4 30d realized-cap flow percentile,
  S5 Fear & Greed.
Sigma/percentile statistics are computed once over the full available sample
(not expanding windows); the dashboard page states the look-ahead caveat.
"""

from typing import Optional

import numpy as np
import pandas as pd

MIN_OBSERVATIONS = 180

# (lower bound inclusive, upper bound exclusive, label, color)
ZONES = [
    (0.0, 60.0, "Watch", "#6e6e73"),
    (60.0, 70.0, "Mildly Undervalued", "#10b981"),
    (70.0, 80.0, "Undervalued", "#f59e0b"),
    (80.0, 100.01, "Extremely Undervalued", "#ef4444"),
]

ZONE_ADVICE = {
    "Watch": "Not cheap yet — keep watching.",
    "Mildly Undervalued": "Getting interesting — consider scaling in slowly.",
    "Undervalued": "Undervalued — historically a productive DCA zone.",
    "Extremely Undervalued": "Extremely undervalued — historically rare readings.",
}

# (date, daily-close price) of cycle bottoms inside the free-tier data window.
CYCLE_BOTTOMS = [
    ("2022-11-21", 15797.53),
    ("2024-09-06", 53914.82),
]

# A trigger segment "hits" when its minimum price is within this multiple
# of its assigned cycle bottom.
BOTTOM_HIT_MULTIPLE = 1.3

THRESHOLDS = (60, 70, 80)
DURATIONS = (1, 3, 7)


def zone_for(composite) -> Optional[tuple[str, str]]:
    """Return (label, color) for a composite score, or None for missing input."""
    if composite is None or pd.isna(composite):
        return None
    for low, high, label, color in ZONES:
        if low <= composite < high:
            return label, color
    return None


def _interp(x: float, xs, ys) -> float:
    """Piecewise-linear interpolation clamped to the anchor range."""
    return float(np.interp(x, xs, ys))


def _strictly_increasing(xs) -> np.ndarray:
    """Force anchor positions to strictly increase (cost lines can cross mid-bear)."""
    xs = np.maximum.accumulate(np.asarray(xs, dtype=float))
    return xs + np.arange(len(xs)) * 1e-9


def score_s1_holder_cost(price, lth, avg, sth) -> Optional[float]:
    """Price vs holder cost-basis lines, interpolated in log space.

    Anchors: >= 1.2*STH -> 0; STH -> 5; AVG -> 10; LTH -> 15; <= 0.8*LTH -> 20.
    """
    vals = [price, lth, avg, sth]
    if any(v is None or pd.isna(v) or v <= 0 for v in vals):
        return None
    raw = np.log([0.8 * lth, lth, avg, sth, 1.2 * sth])
    cum = np.maximum.accumulate(raw)
    # Nudge only positions that were flattened (ties after cummax), preserving
    # exact boundary anchors where no crossing occurred.
    nudge = np.where(cum == raw, 0.0, np.arange(5) * 1e-9)
    log_xs = cum + nudge
    ys = [20.0, 15.0, 10.0, 5.0, 0.0]
    return _interp(np.log(price), log_xs, ys)


def full_sample_deviation(series: pd.Series) -> pd.Series:
    """Deviation from the full-sample mean in population-std units.

    All-NaN result when the sample is shorter than MIN_OBSERVATIONS or flat.
    """
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if len(valid) < MIN_OBSERVATIONS or valid.std(ddof=0) == 0:
        return pd.Series(np.nan, index=s.index)
    return (s - valid.mean()) / valid.std(ddof=0)


def _sigma_to_score(dev: pd.Series, anchors_sigma, anchors_score) -> pd.Series:
    return dev.apply(
        lambda v: np.nan if pd.isna(v) else _interp(v, anchors_sigma, anchors_score)
    )


def score_s2_mvrv(series: pd.Series) -> pd.Series:
    """MVRV deviation: +2 sigma -> 0, 0 -> 8, -1.5 sigma -> 20."""
    return _sigma_to_score(
        full_sample_deviation(series), [-1.5, 0.0, 2.0], [20.0, 8.0, 0.0]
    )


def score_s3_supply_loss(series: pd.Series) -> pd.Series:
    """Supply-in-loss deviation: -1 sigma -> 0, 0 -> 6, +0.5 -> 10, +2 -> 20."""
    return _sigma_to_score(
        full_sample_deviation(series),
        [-1.0, 0.0, 0.5, 2.0],
        [0.0, 6.0, 10.0, 20.0],
    )


def score_s4_capital_flow(series: pd.Series) -> pd.Series:
    """20 x (1 - full-sample percentile rank) of the 30d realized-cap change."""
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() < MIN_OBSERVATIONS:
        return pd.Series(np.nan, index=s.index)
    return 20.0 * (1.0 - s.rank(pct=True))


def score_s5_fear_greed(value) -> Optional[float]:
    """Fear & Greed: <= 10 -> 20; >= 75 -> 0; linear between."""
    if value is None or pd.isna(value):
        return None
    return _interp(float(value), [10.0, 75.0], [20.0, 0.0])


def compute_bottom_signal_scores(
    onchain_df: pd.DataFrame, price_df: pd.DataFrame
) -> pd.DataFrame:
    """Join on-chain data with daily closes and score S1-S5 plus the composite.

    price_df needs `date` and `close_price`. Returns one row per on-chain date
    that has a close price, sorted ascending, with raw inputs, s1..s5, the
    diagnostic columns (s2_dev, s3_dev, s4_pctile), composite, zone, zone_color.
    """
    prices = price_df[["date", "close_price"]].copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.strftime("%Y-%m-%d")
    df = (
        onchain_df.merge(prices, on="date", how="inner")
        .sort_values("date")
        .reset_index(drop=True)
    )

    df["s1"] = [
        score_s1_holder_cost(p, lth, avg, sth)
        for p, lth, avg, sth in zip(
            df["close_price"],
            df["lth_realized_price"],
            df["realized_price"],
            df["sth_realized_price"],
        )
    ]
    df["s2_dev"] = full_sample_deviation(df["mvrv"])
    df["s2"] = _sigma_to_score(df["s2_dev"], [-1.5, 0.0, 2.0], [20.0, 8.0, 0.0])
    df["s3_dev"] = full_sample_deviation(df["supply_loss_pct"])
    df["s3"] = _sigma_to_score(
        df["s3_dev"], [-1.0, 0.0, 0.5, 2.0], [0.0, 6.0, 10.0, 20.0]
    )
    s4_raw = pd.to_numeric(df["realized_cap_change_30d_usd"], errors="coerce")
    df["s4_pctile"] = (
        s4_raw.rank(pct=True)
        if s4_raw.notna().sum() >= MIN_OBSERVATIONS
        else pd.Series(np.nan, index=df.index)
    )
    df["s4"] = 20.0 * (1.0 - df["s4_pctile"])
    df["s5"] = [score_s5_fear_greed(v) for v in df["fear_greed"]]

    score_cols = ["s1", "s2", "s3", "s4", "s5"]
    for col in score_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["composite"] = df[score_cols].sum(axis=1, min_count=len(score_cols))

    zones = df["composite"].map(zone_for)
    df["zone"] = zones.map(lambda z: z[0] if z else None)
    df["zone_color"] = zones.map(lambda z: z[1] if z else None)
    return df
