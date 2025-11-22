#!/usr/bin/env python3
"""
Manual migration script to add missing columns to dca_transactions table.
Run this if automatic migration fails.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dca_service.database import engine, _migrate_transaction_table
from sqlmodel import Session, text

def main():
    print("Starting manual migration...")
    
    # Check current table structure
    with Session(engine) as session:
        result = session.exec(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='dca_transactions'
        """)).first()
        
        if not result:
            print("Table dca_transactions does not exist. Creating it...")
            from dca_service.database import create_db_and_tables
            create_db_and_tables()
            print("Table created successfully.")
            return
        
        print("Table exists. Checking columns...")
        columns = session.exec(text("""
            SELECT name FROM pragma_table_info('dca_transactions')
        """)).all()
        # Extract column names properly
        column_names = []
        for col in columns:
            if isinstance(col, tuple) and len(col) > 0:
                column_names.append(col[0])
            elif hasattr(col, '__getitem__'):
                column_names.append(col[0])
            else:
                column_names.append(str(col))
        print(f"Current columns: {', '.join(column_names)}")
    
    # Run migration
    try:
        _migrate_transaction_table()
        print("Migration completed successfully!")
        
        # Verify columns
        with Session(engine) as session:
            columns = session.exec(text("""
                SELECT name FROM pragma_table_info('dca_transactions')
            """)).all()
            # Extract column names properly
            column_names = []
            for col in columns:
                if isinstance(col, tuple) and len(col) > 0:
                    column_names.append(col[0])
                elif hasattr(col, '__getitem__'):
                    column_names.append(col[0])
                else:
                    column_names.append(str(col))
            print(f"Columns after migration: {', '.join(column_names)}")
            
            if 'source' in column_names and 'fee_amount' in column_names and 'fee_asset' in column_names:
                print("✓ All required columns are present!")
            else:
                missing = []
                if 'source' not in column_names:
                    missing.append('source')
                if 'fee_amount' not in column_names:
                    missing.append('fee_amount')
                if 'fee_asset' not in column_names:
                    missing.append('fee_asset')
                print(f"✗ Missing columns: {', '.join(missing)}")
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

