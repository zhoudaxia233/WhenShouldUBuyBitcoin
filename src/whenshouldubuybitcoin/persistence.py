"""
Data persistence module for storing and loading Bitcoin metrics.

This module handles saving/loading historical metrics to/from CSV files
and metadata to/from JSON files.
"""

import json
from pathlib import Path
from typing import Optional
import tempfile

import pandas as pd


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically to avoid partial writes and bypass read-only target files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _sanitize_metrics_rows(df: pd.DataFrame, context: str) -> pd.DataFrame:
    """
    Remove rows that cannot safely participate in price-based calculations.

    This self-heals stale CSVs that already contain an incomplete current-day row
    and keeps merge logic from preferring a newer but unusable close price.
    """
    df = df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "close_price" in df.columns:
        df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")

    invalid_mask = df["date"].isna()
    if "close_price" in df.columns:
        invalid_mask |= df["close_price"].isna() | (df["close_price"] <= 0)

    dropped = int(invalid_mask.sum())
    if dropped:
        print(f"  Dropped {dropped} invalid row(s) while {context}")
    return df.loc[~invalid_mask].reset_index(drop=True)


def get_data_dir() -> Path:
    """
    Get the data directory path, creating it if it doesn't exist.
    
    Returns:
        Path object for the data directory (inside docs/ for GitHub Pages)
    """
    # Get project root (3 levels up from this file)
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "docs" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def load_existing_metrics(filename: str = "btc_metrics.csv") -> Optional[pd.DataFrame]:
    """
    Load existing metrics from CSV file and restore metadata.
    
    Args:
        filename: Name of the CSV file (default: "btc_metrics.csv")
        
    Returns:
        DataFrame with historical metrics and metadata restored, or None if file doesn't exist
    """
    data_dir = get_data_dir()
    filepath = data_dir / filename
    
    if not filepath.exists():
        print(f"No existing data file found at {filepath}")
        return None
    
    try:
        df = pd.read_csv(filepath)
        df = _sanitize_metrics_rows(df, f"loading {filepath}")
        if df.empty:
            print(f"⚠ No usable rows found in {filepath}; treating as no existing data")
            return None

        # Load and restore metadata
        metadata = load_metadata()
        if metadata:
            df.attrs["trend_a"] = metadata.get("trend_a")
            df.attrs["trend_b"] = metadata.get("trend_b")
        
        print(f"✓ Loaded {len(df)} rows from {filepath}")
        print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        
        return df
        
    except Exception as e:
        print(f"✗ Error loading data from {filepath}: {e}")
        return None


def save_metadata(df: pd.DataFrame, filename: str = "btc_metadata.json") -> bool:
    """
    Save DataFrame metadata (attrs) to JSON file.
    
    This stores trend parameters and other metadata that can't be saved in CSV.
    
    Args:
        df: DataFrame with metadata in attrs
        filename: Name of the JSON file (default: "btc_metadata.json")
        
    Returns:
        True if successful, False otherwise
    """
    data_dir = get_data_dir()
    filepath = data_dir / filename
    
    try:
        metadata = {
            "trend_a": df.attrs.get("trend_a"),
            "trend_b": df.attrs.get("trend_b"),
            "last_updated": pd.Timestamp.now().isoformat()
        }
        
        _atomic_write_text(filepath, json.dumps(metadata, indent=2))
        
        return True
        
    except Exception as e:
        print(f"✗ Error saving metadata to {filepath}: {e}")
        return False


def load_metadata(filename: str = "btc_metadata.json") -> Optional[dict]:
    """
    Load metadata from JSON file.
    
    Args:
        filename: Name of the JSON file (default: "btc_metadata.json")
        
    Returns:
        Dictionary with metadata, or None if file doesn't exist
    """
    data_dir = get_data_dir()
    filepath = data_dir / filename
    
    if not filepath.exists():
        return None
    
    try:
        with open(filepath, "r") as f:
            metadata = json.load(f)
        return metadata
        
    except Exception as e:
        print(f"✗ Error loading metadata from {filepath}: {e}")
        return None


def save_metrics(df: pd.DataFrame, filename: str = "btc_metrics.csv") -> bool:
    """
    Save metrics DataFrame to CSV file and metadata to JSON file.
    
    Args:
        df: DataFrame with metrics to save
        filename: Name of the CSV file (default: "btc_metrics.csv")
        
    Returns:
        True if successful, False otherwise
    """
    data_dir = get_data_dir()
    filepath = data_dir / filename
    
    try:
        # Select columns to save (drop any internal pandas attributes)
        columns_to_save = [
            "date",
            "close_price",
            "volume",
            "dca_cost",
            "ratio_dca",
            "trend_value",
            "ratio_trend",
            "is_double_undervalued",
            "ahr999",
            # Reserved for future relative-volume/bottoming signals
            "volume_ma30",
            "volume_ratio_30",
            "daily_return_pct",
            "is_panic_selloff_day",
            "recent_panic_selloff_7d",
            "is_post_panic_volume_contraction",
            "rsi14",
            "rsi14w",
            "is_rsi_daily_oversold",
            "is_rsi_weekly_oversold_proxy",
            "is_rsi_bottoming_signal",
        ]
        
        # Filter to only existing columns
        save_cols = [col for col in columns_to_save if col in df.columns]
        df_to_save = _sanitize_metrics_rows(
            df[save_cols].copy(), f"saving {filepath}"
        )
        if df_to_save.empty:
            raise ValueError("No usable metric rows available to save")
        
        # Convert date to string for CSV storage
        df_to_save["date"] = df_to_save["date"].dt.strftime("%Y-%m-%d")
        
        # Save to CSV atomically (handles read-only target file metadata on host mounts).
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
                df_to_save.to_csv(tmp, index=False)
                tmp_path = Path(tmp.name)
            tmp_path.replace(filepath)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        
        print(f"✓ Saved {len(df_to_save)} rows to {filepath}")
        
        # Save metadata (trend parameters)
        save_metadata(df)
        
        return True
        
    except Exception as e:
        print(f"✗ Error saving data to {filepath}: {e}")
        return False


def merge_with_existing(
    new_df: pd.DataFrame, 
    existing_df: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """
    Merge new data with existing data, avoiding duplicates.
    
    Strategy:
    - If no existing data, return new data
    - Otherwise, combine and keep the most recent data for each date
    - Remove duplicates, keeping last occurrence
    
    Args:
        new_df: DataFrame with new/updated data
        existing_df: DataFrame with existing data (or None)
        
    Returns:
        Merged DataFrame sorted by date
    """
    if existing_df is None or existing_df.empty:
        print("No existing data to merge, using new data only")
        return new_df
    
    existing_df = _sanitize_metrics_rows(existing_df, "merging existing metrics")
    new_df = _sanitize_metrics_rows(new_df, "merging freshly fetched metrics")
    if new_df.empty:
        raise ValueError("New price data contains no usable close_price rows")
    if existing_df.empty:
        print("  Existing data had no usable rows after sanitization; using new data only")
        return new_df

    print(f"\nMerging data:")
    print(f"  Existing: {len(existing_df)} rows ({existing_df['date'].min().date()} to {existing_df['date'].max().date()})")
    print(f"  New:      {len(new_df)} rows ({new_df['date'].min().date()} to {new_df['date'].max().date()})")
    
    # Combine the dataframes
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    
    # Remove duplicates, keeping the last occurrence (newest data)
    # This ensures we use the most recent calculation for each date
    combined = combined.drop_duplicates(subset=["date"], keep="last")
    
    # Sort by date
    combined = combined.sort_values("date").reset_index(drop=True)
    
    print(f"  Merged:   {len(combined)} rows ({combined['date'].min().date()} to {combined['date'].max().date()})")
    
    return combined


def get_days_to_fetch(existing_df: Optional[pd.DataFrame], buffer_days: int = 30) -> Optional[int]:
    """
    Determine how many days of data to fetch based on existing data.
    
    If we have existing data, fetch from the last date with a buffer.
    Otherwise, return None to fetch ALL available historical data.
    
    Args:
        existing_df: Existing DataFrame or None
        buffer_days: Number of days to overlap for recalculation (default: 30)
        
    Returns:
        Number of days to fetch, or None to fetch all available data
        
    Note:
        For power law model accuracy, fetching all available data (~4000+ days from 2014)
        provides much better parameter fitting than limited history.
    """
    if existing_df is None or existing_df.empty:
        # No existing data, fetch ALL available history for accurate power law fitting
        print("\nNo existing data found.")
        print("Will fetch ALL available history from Yahoo Finance (2014-09-17 onwards)")
        return None
    
    # Calculate days since last data point
    last_date = existing_df["date"].max()
    days_since = (pd.Timestamp.now() - last_date).days
    
    # Add buffer for recalculation
    days_to_fetch = days_since + buffer_days
    
    print(f"\nLast data point: {last_date.date()} ({days_since} days ago)")
    print(f"Fetching {days_to_fetch} days (including {buffer_days}-day buffer)")
    
    return max(days_to_fetch, 365)  # Minimum 1 year for good metrics


if __name__ == "__main__":
    # Quick test
    print("Testing persistence module...")
    print(f"Data directory: {get_data_dir()}")
    
    # Try to load existing data
    df = load_existing_metrics()
    if df is not None:
        print(f"\nLoaded data shape: {df.shape}")
        print(f"Columns: {df.columns.tolist()}")
