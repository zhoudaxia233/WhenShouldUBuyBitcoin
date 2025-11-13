"""
Data persistence module for storing and loading Bitcoin metrics.

This module handles saving/loading historical metrics to/from CSV files.
"""

from pathlib import Path
from typing import Optional

import pandas as pd


def get_data_dir() -> Path:
    """
    Get the data directory path, creating it if it doesn't exist.
    
    Returns:
        Path object for the data directory
    """
    # Get project root (3 levels up from this file)
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def load_existing_metrics(filename: str = "btc_metrics.csv") -> Optional[pd.DataFrame]:
    """
    Load existing metrics from CSV file.
    
    Args:
        filename: Name of the CSV file (default: "btc_metrics.csv")
        
    Returns:
        DataFrame with historical metrics, or None if file doesn't exist
    """
    data_dir = get_data_dir()
    filepath = data_dir / filename
    
    if not filepath.exists():
        print(f"No existing data file found at {filepath}")
        return None
    
    try:
        df = pd.read_csv(filepath)
        
        # Convert date column to datetime
        df["date"] = pd.to_datetime(df["date"])
        
        print(f"✓ Loaded {len(df)} rows from {filepath}")
        print(f"  Date range: {df['date'].min().date()} to {df['date'].max().date()}")
        
        return df
        
    except Exception as e:
        print(f"✗ Error loading data from {filepath}: {e}")
        return None


def save_metrics(df: pd.DataFrame, filename: str = "btc_metrics.csv") -> bool:
    """
    Save metrics DataFrame to CSV file.
    
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
            "dca_cost",
            "ratio_dca",
            "trend_value",
            "ratio_trend",
            "is_double_undervalued",
        ]
        
        # Filter to only existing columns
        save_cols = [col for col in columns_to_save if col in df.columns]
        df_to_save = df[save_cols].copy()
        
        # Convert date to string for CSV storage
        df_to_save["date"] = df_to_save["date"].dt.strftime("%Y-%m-%d")
        
        # Save to CSV
        df_to_save.to_csv(filepath, index=False)
        
        print(f"✓ Saved {len(df_to_save)} rows to {filepath}")
        
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


def get_days_to_fetch(existing_df: Optional[pd.DataFrame], buffer_days: int = 30) -> int:
    """
    Determine how many days of data to fetch based on existing data.
    
    If we have existing data, fetch from the last date with a buffer.
    Otherwise, fetch the full historical dataset.
    
    Args:
        existing_df: Existing DataFrame or None
        buffer_days: Number of days to overlap for recalculation (default: 30)
        
    Returns:
        Number of days to fetch
    """
    if existing_df is None or existing_df.empty:
        # No existing data, fetch full history
        return 2000
    
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

