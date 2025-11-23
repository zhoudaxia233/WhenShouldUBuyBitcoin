import sqlite3
from pathlib import Path

def migrate_db():
    db_path = Path("dca.db")
    if not db_path.exists():
        print(f"Database {db_path} not found. Skipping migration.")
        return

    print(f"Migrating database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # List of columns to add
    # (name, type, default_value)
    columns_to_add = [
        ("strategy_type", "TEXT", "'legacy_band'"),
        ("dynamic_min_multiplier", "FLOAT", "NULL"),
        ("dynamic_max_multiplier", "FLOAT", "NULL"),
        ("dynamic_gamma", "FLOAT", "NULL"),
        ("dynamic_a_low", "FLOAT", "NULL"),
        ("dynamic_a_high", "FLOAT", "NULL"),
        ("dynamic_enable_drawdown_boost", "BOOLEAN", "NULL"),
        ("dynamic_enable_monthly_cap", "BOOLEAN", "NULL"),
        ("dynamic_monthly_cap", "FLOAT", "NULL"),
    ]

    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(dca_strategy)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        for col_name, col_type, default_val in columns_to_add:
            if col_name not in existing_columns:
                print(f"Adding column {col_name}...")
                if default_val != "NULL":
                    cursor.execute(f"ALTER TABLE dca_strategy ADD COLUMN {col_name} {col_type} DEFAULT {default_val}")
                else:
                    cursor.execute(f"ALTER TABLE dca_strategy ADD COLUMN {col_name} {col_type}")
            else:
                print(f"Column {col_name} already exists.")

        conn.commit()
        print("Migration complete.")

    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
