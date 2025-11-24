"""
Database migration: Add execution_mode column to dca_strategy table

Usage:
    poetry run python -m dca_service.migrations.add_execution_mode
"""
import sqlite3
from pathlib import Path
from dca_service.config import settings


def migrate():
    """Add execution_mode column to dca_strategy table if it doesn't exist"""
    # Extract database path from DATABASE_URL
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    
    # Check if database exists
    if not Path(db_path).exists():
        print(f"Database {db_path} does not exist yet. No migration needed.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if execution_mode column exists
        cursor.execute("PRAGMA table_info(dca_strategy)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'execution_mode' in columns:
            print("✓ execution_mode column already exists. No migration needed.")
        else:
            print("Adding execution_mode column to dca_strategy table...")
            cursor.execute("""
                ALTER TABLE dca_strategy 
                ADD COLUMN execution_mode TEXT DEFAULT 'DRY_RUN'
            """)
            conn.commit()
            print("✓ Successfully added execution_mode column with default value 'DRY_RUN'")
        
    except sqlite3.OperationalError as e:
        print(f"Error during migration: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
