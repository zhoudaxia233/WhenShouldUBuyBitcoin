import sqlite3
import pytest
from pathlib import Path
import os

from scripts.migrate_strategy_columns import migrate_db

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database with the OLD schema"""
    db_path = tmp_path / "dca.db"
    
    # Switch to tmp dir for the migration script to find the db file
    # (The script looks for "dca.db" in current dir)
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    
    conn = sqlite3.connect("dca.db")
    cursor = conn.cursor()
    
    # Create table with OLD schema (missing new columns)
    cursor.execute("""
        CREATE TABLE dca_strategy (
            id INTEGER PRIMARY KEY,
            is_active BOOLEAN,
            total_budget_usd FLOAT,
            allow_over_budget BOOLEAN,
            ahr999_multiplier_low FLOAT,
            ahr999_multiplier_mid FLOAT,
            ahr999_multiplier_high FLOAT,
            target_btc_amount FLOAT,
            execution_frequency TEXT,
            execution_day_of_week TEXT,
            execution_time_utc TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
    """)
    conn.commit()
    conn.close()
    
    yield db_path
    
    # Cleanup and restore CWD
    os.chdir(original_cwd)

def test_migration_adds_columns(temp_db):
    """Test that migration script adds the missing columns"""
    # Run migration
    migrate_db()
    
    # Verify columns exist
    conn = sqlite3.connect("dca.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(dca_strategy)")
    columns = {row[1] for row in cursor.fetchall()}
    
    assert "strategy_type" in columns
    assert "dynamic_min_multiplier" in columns
    assert "dynamic_max_multiplier" in columns
    assert "dynamic_gamma" in columns
    assert "dynamic_monthly_cap" in columns
    
    conn.close()

def test_migration_idempotent(temp_db):
    """Test that running migration twice doesn't fail"""
    migrate_db()
    migrate_db() # Should not raise error
    
    conn = sqlite3.connect("dca.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(dca_strategy)")
    columns = {row[1] for row in cursor.fetchall()}
    
    assert "strategy_type" in columns
    conn.close()
