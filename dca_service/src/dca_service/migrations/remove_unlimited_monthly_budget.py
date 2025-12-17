"""
Database migration: Remove unlimited_monthly_budget column from dca_strategy table

This migration removes the redundant unlimited_monthly_budget field since
we now only use enforce_monthly_cap to control budget behavior:
- enforce_monthly_cap=True: Budget resets monthly (limited mode)
- enforce_monthly_cap=False: Budget accumulates (unlimited mode)

Usage:
    poetry run python -m dca_service.migrations.remove_unlimited_monthly_budget
"""
import sqlite3
from pathlib import Path
from dca_service.config import settings


def migrate():
    """Remove unlimited_monthly_budget column from dca_strategy table if it exists"""
    # Extract database path from DATABASE_URL
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    
    # Check if database exists
    if not Path(db_path).exists():
        print(f"Database {db_path} does not exist yet. No migration needed.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if unlimited_monthly_budget column exists
        cursor.execute("PRAGMA table_info(dca_strategy)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'unlimited_monthly_budget' not in columns:
            print("✓ unlimited_monthly_budget column already removed. No migration needed.")
            return
        
        print("Removing unlimited_monthly_budget column from dca_strategy table...")
        
        # Check SQLite version
        cursor.execute("SELECT sqlite_version()")
        sqlite_version = cursor.fetchone()[0]
        major, minor, _ = sqlite_version.split('.')
        
        # SQLite 3.35.0+ supports ALTER TABLE DROP COLUMN
        if int(major) >= 3 and int(minor) >= 35:
            print(f"SQLite version {sqlite_version} supports DROP COLUMN")
            cursor.execute("""
                ALTER TABLE dca_strategy 
                DROP COLUMN unlimited_monthly_budget
            """)
            conn.commit()
            print("✓ Successfully removed unlimited_monthly_budget column")
        else:
            print(f"SQLite version {sqlite_version} does not support DROP COLUMN")
            print("Using table recreation method...")
            
            # Get all columns except unlimited_monthly_budget
            cursor.execute("PRAGMA table_info(dca_strategy)")
            all_columns = cursor.fetchall()
            keep_columns = [col[1] for col in all_columns if col[1] != 'unlimited_monthly_budget']
            columns_str = ', '.join(keep_columns)
            
            # Create new table without unlimited_monthly_budget
            cursor.execute("""
                CREATE TABLE dca_strategy_new (
                    id INTEGER PRIMARY KEY,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    total_budget_usd REAL NOT NULL,
                    enforce_monthly_cap INTEGER NOT NULL DEFAULT 1,
                    accumulated_savings REAL NOT NULL DEFAULT 0.0,
                    last_monthly_inflow TIMESTAMP,
                    ahr999_multiplier_low REAL NOT NULL,
                    ahr999_multiplier_mid REAL NOT NULL,
                    ahr999_multiplier_high REAL NOT NULL,
                    ahr999_multiplier_p10 REAL,
                    ahr999_multiplier_p25 REAL,
                    ahr999_multiplier_p50 REAL,
                    ahr999_multiplier_p75 REAL,
                    ahr999_multiplier_p90 REAL,
                    ahr999_multiplier_p100 REAL,
                    ahr999_multiplier_r045 REAL,
                    ahr999_multiplier_r050 REAL,
                    ahr999_multiplier_r060 REAL,
                    ahr999_multiplier_r070 REAL,
                    ahr999_multiplier_r080 REAL,
                    ahr999_multiplier_r090 REAL,
                    ahr999_multiplier_r100 REAL,
                    ahr999_multiplier_r999 REAL,
                    target_btc_amount REAL NOT NULL DEFAULT 1.0,
                    execution_frequency TEXT NOT NULL DEFAULT 'daily',
                    execution_day_of_week TEXT,
                    execution_time_utc TEXT NOT NULL DEFAULT '00:00',
                    strategy_type TEXT NOT NULL DEFAULT 'legacy_band',
                    execution_mode TEXT NOT NULL DEFAULT 'DRY_RUN',
                    dynamic_min_multiplier REAL,
                    dynamic_max_multiplier REAL,
                    dynamic_gamma REAL,
                    dynamic_a_low REAL,
                    dynamic_a_high REAL,
                    dynamic_enable_drawdown_boost INTEGER,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)
            
            # Copy data from old table to new table
            cursor.execute(f"""
                INSERT INTO dca_strategy_new ({columns_str})
                SELECT {columns_str}
                FROM dca_strategy
            """)
            
            # Drop old table and rename new table
            cursor.execute("DROP TABLE dca_strategy")
            cursor.execute("ALTER TABLE dca_strategy_new RENAME TO dca_strategy")
            
            conn.commit()
            print("✓ Successfully removed unlimited_monthly_budget column via table recreation")
        
    except sqlite3.OperationalError as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()

