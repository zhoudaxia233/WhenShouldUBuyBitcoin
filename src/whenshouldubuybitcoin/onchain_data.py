"""
Orchestration for the on-chain bottom-signal dataset.

Fetches free on-chain series (bitcoin-data.com) plus Fear & Greed history
(alternative.me), accumulates them in docs/data/onchain_metrics.csv (history
never shrinks even though the free API only serves the last ~4 years), and
guards the free-tier request budget with a freshness check.
"""

import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from .persistence import get_data_dir
from .providers.alternative_me import fetch_fear_and_greed_history
from .providers.bitcoin_data_com import fetch_all_onchain_series

ONCHAIN_CSV = "onchain_metrics.csv"

ONCHAIN_COLUMNS = [
    "date",
    "lth_realized_price",
    "realized_price",
    "sth_realized_price",
    "mvrv",
    "supply_loss_pct",
    "realized_cap_change_30d_usd",
    "fear_greed",
]

# Refetch this many days before the last cached date to absorb upstream revisions.
REFETCH_OVERLAP_DAYS = 7


def _normalize_realized_cap_change(series: pd.Series) -> pd.Series:
    """Store the 30d realized-cap change in USD whether the API sends USD or billions."""
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return s
    return s * 1e9 if s.abs().max() < 1e6 else s


def load_onchain_metrics() -> Optional[pd.DataFrame]:
    """Load the accumulated dataset; None when absent or unreadable."""
    filepath = get_data_dir() / ONCHAIN_CSV
    if not filepath.exists():
        print(f"No existing on-chain data file at {filepath}")
        return None
    try:
        df = pd.read_csv(filepath)
        if "date" not in df.columns or df.empty:
            return None
        df["date"] = df["date"].astype(str).str[:10]
        for col in ONCHAIN_COLUMNS:
            if col == "date":
                continue
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        df = df[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)
        print(f"✓ Loaded {len(df)} on-chain rows from {filepath}")
        return df
    except Exception as e:
        print(f"✗ Error loading {filepath}: {e}")
        return None


def save_onchain_metrics(df: pd.DataFrame) -> bool:
    """Atomically persist the dataset sorted by date."""
    filepath = get_data_dir() / ONCHAIN_CSV
    try:
        out = df[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=filepath.parent,
                prefix=f".{filepath.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                out.to_csv(tmp, index=False)
                tmp_path = Path(tmp.name)
            tmp_path.replace(filepath)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        print(f"✓ Saved {len(out)} on-chain rows to {filepath}")
        return True
    except Exception as e:
        print(f"✗ Error saving {filepath}: {e}")
        return False


def merge_onchain(
    existing: Optional[pd.DataFrame], new: pd.DataFrame
) -> pd.DataFrame:
    """Outer-merge on date; new values win where present, history is never dropped."""
    new = new[ONCHAIN_COLUMNS].sort_values("date")
    if existing is None or existing.empty:
        return new.reset_index(drop=True)
    merged = (
        new.set_index("date")
        .combine_first(existing[ONCHAIN_COLUMNS].set_index("date"))
        .reset_index()
    )
    return merged[ONCHAIN_COLUMNS].sort_values("date").reset_index(drop=True)


def is_fresh(df: Optional[pd.DataFrame], today: Optional[date] = None) -> bool:
    """True when the newest cached row is from today or yesterday (UTC daily lag)."""
    if df is None or df.empty:
        return False
    today = today or date.today()
    try:
        last = date.fromisoformat(str(df["date"].max())[:10])
    except ValueError:
        return False
    return last >= today - timedelta(days=1)


def _series_dict_to_frame(series_by_metric: dict, fng_rows) -> pd.DataFrame:
    """Pivot fetched series into one wide normalized frame keyed by date."""
    frames = []
    for metric, series in (series_by_metric or {}).items():
        if not series:
            continue
        frame = pd.DataFrame(series, columns=["date", metric]).set_index("date")
        frames.append(frame[~frame.index.duplicated(keep="last")])
    if fng_rows:
        fng = pd.DataFrame(fng_rows).rename(columns={"value": "fear_greed"})
        fng = fng.set_index("date")
        frames.append(fng[~fng.index.duplicated(keep="last")])
    if not frames:
        return pd.DataFrame(columns=ONCHAIN_COLUMNS)

    wide = pd.concat(frames, axis=1, join="outer").reset_index()
    wide = wide.rename(columns={"index": "date"})
    for col in ("supply_loss_btc", "supply_profit_btc", *ONCHAIN_COLUMNS):
        if col not in wide.columns:
            wide[col] = pd.NA

    # The API reports absolute BTC in loss/profit; their sum is the provider's
    # circulating-supply universe, so the ratio is an exact in-loss share.
    loss = pd.to_numeric(wide["supply_loss_btc"], errors="coerce")
    profit = pd.to_numeric(wide["supply_profit_btc"], errors="coerce")
    total = loss + profit
    wide["supply_loss_pct"] = (100.0 * loss / total).where(total > 0)

    wide["realized_cap_change_30d_usd"] = _normalize_realized_cap_change(
        wide["realized_cap_change_30d_usd"]
    )
    return wide[ONCHAIN_COLUMNS]


def update_onchain_metrics(force: bool = False) -> Optional[pd.DataFrame]:
    """Load, freshen (within free-tier limits), persist, and return the dataset.

    Network is skipped entirely when the cache already holds today's or
    yesterday's row, so repeated local runs cannot burn the request budget.
    """
    existing = load_onchain_metrics()
    if not force and is_fresh(existing):
        print("✓ On-chain metrics are fresh; skipping API calls (free-tier budget guard)")
        return existing

    startday = None
    if existing is not None and not existing.empty:
        last = date.fromisoformat(str(existing["date"].max())[:10])
        startday = (last - timedelta(days=REFETCH_OVERLAP_DAYS)).isoformat()

    series_by_metric = fetch_all_onchain_series(startday=startday)
    fng_rows = fetch_fear_and_greed_history()
    new = _series_dict_to_frame(series_by_metric, fng_rows)

    if new.empty:
        print("⚠ No new on-chain data fetched; using cached dataset")
        return existing

    merged = merge_onchain(existing, new)
    save_onchain_metrics(merged)
    return merged
