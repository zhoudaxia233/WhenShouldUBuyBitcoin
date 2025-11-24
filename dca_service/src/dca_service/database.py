from sqlmodel import SQLModel, create_engine, Session, text
from .config import settings
from dca_service.core.logging import logger

# check_same_thread=False is needed for SQLite with FastAPI
engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False}
)

def _migrate_transaction_table():
    """
    Migrate existing dca_transactions table to add new columns if they don't exist.
    This ensures backward compatibility with existing databases.
    """
    try:
        with Session(engine) as session:
            # First check if table exists
            table_exists = session.exec(text("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='dca_transactions'
            """)).first()
            
            if not table_exists:
                # Table doesn't exist yet, SQLModel will create it with all columns
                # No migration needed
                return
            
            # Get all existing column names
            existing_columns = session.exec(text("""
                SELECT name FROM pragma_table_info('dca_transactions')
            """)).all()
            # Handle both tuple and string results from SQLModel
            # SQLModel returns Row objects which can be indexed or converted to tuple
            existing_column_names = set()
            for col in existing_columns:
                if isinstance(col, tuple) and len(col) > 0:
                    existing_column_names.add(col[0])
                elif hasattr(col, '__getitem__'):
                    existing_column_names.add(col[0])
                else:
                    existing_column_names.add(str(col))
            
            # Check and add source column
            if 'source' not in existing_column_names:
                logger.info("Adding 'source' column to dca_transactions table...")
                session.exec(text("""
                    ALTER TABLE dca_transactions 
                    ADD COLUMN source TEXT
                """))
                # Update existing rows to have SIMULATED as source
                session.exec(text("""
                    UPDATE dca_transactions 
                    SET source = 'SIMULATED' 
                    WHERE source IS NULL
                """))
            
            # Check and add fee_amount column
            if 'fee_amount' not in existing_column_names:
                logger.info("Adding 'fee_amount' column to dca_transactions table...")
                session.exec(text("""
                    ALTER TABLE dca_transactions 
                    ADD COLUMN fee_amount REAL
                """))
            
            # Check and add fee_asset column
            if 'fee_asset' not in existing_column_names:
                logger.info("Adding 'fee_asset' column to dca_transactions table...")
                session.exec(text("""
                    ALTER TABLE dca_transactions 
                    ADD COLUMN fee_asset TEXT
                """))
            
            session.commit()
            logger.info("Migration completed successfully")
    except Exception as e:
        # Log error and re-raise to ensure we know about the issue
        logger.error(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def _migrate_strategy_table():
    """
    Migrate existing dca_strategy table to add new percentile multiplier columns if they don't exist.
    This ensures backward compatibility with existing databases.
    """
    try:
        with Session(engine) as session:
            # First check if table exists
            table_exists = session.exec(text("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='dca_strategy'
            """)).first()
            
            if not table_exists:
                # Table doesn't exist yet, SQLModel will create it with all columns
                # No migration needed
                return
            
            # Get all existing column names
            existing_columns = session.exec(text("""
                SELECT name FROM pragma_table_info('dca_strategy')
            """)).all()
            # Handle both tuple and string results from SQLModel
            existing_column_names = set()
            for col in existing_columns:
                if isinstance(col, tuple) and len(col) > 0:
                    existing_column_names.add(col[0])
                elif hasattr(col, '__getitem__'):
                    existing_column_names.add(col[0])
                else:
                    existing_column_names.add(str(col))
            
            # List of new percentile multiplier columns to add
            new_columns = [
                ('ahr999_multiplier_p10', 'REAL', None),  # Bottom 10% (EXTREME CHEAP)
                ('ahr999_multiplier_p25', 'REAL', None),  # 10-25% (Very Cheap)
                ('ahr999_multiplier_p50', 'REAL', None),  # 25-50% (Cheap)
                ('ahr999_multiplier_p75', 'REAL', None),  # 50-75% (Fair)
                ('ahr999_multiplier_p90', 'REAL', None),  # 75-90% (Expensive)
                ('ahr999_multiplier_p100', 'REAL', None),  # Top 10% (VERY EXPENSIVE)
            ]
            
            # Check and add each column
            for column_name, column_type, default_value in new_columns:
                if column_name not in existing_column_names:
                    logger.info(f"Adding '{column_name}' column to dca_strategy table...")
                    alter_sql = f"""
                        ALTER TABLE dca_strategy 
                        ADD COLUMN {column_name} {column_type}
                    """
                    if default_value is not None:
                        alter_sql = alter_sql.rstrip() + f" DEFAULT {default_value}"
                    session.exec(text(alter_sql))
                    logger.info(f"  ✓ Added {column_name}")
            
            session.commit()
            logger.info("Strategy table migration completed successfully")
    except Exception as e:
        # Log error and re-raise to ensure we know about the issue
        logger.error(f"Strategy table migration failed: {e}")
        import traceback
        traceback.print_exc()
        raise

def create_db_and_tables():
    # Create all tables first (this will create new tables with all columns)
    SQLModel.metadata.create_all(engine)
    # Then run migration to add columns to existing tables that might be missing them
    _migrate_transaction_table()
    _migrate_strategy_table()

def get_session():
    with Session(engine) as session:
        yield session
