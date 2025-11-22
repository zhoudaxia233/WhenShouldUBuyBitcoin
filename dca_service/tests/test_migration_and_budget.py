"""
Tests for database migration and budget calculation logic.
Ensures that:
1. Database migration correctly adds missing columns
2. Transactions are created with all required fields (source, fee_amount, fee_asset)
3. Budget calculation works correctly with monthly reset
4. Remaining budget is calculated correctly
"""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from sqlmodel import Session, SQLModel, create_engine, text, select
from sqlmodel.pool import StaticPool

from dca_service.models import DCATransaction, DCAStrategy
from dca_service.database import _migrate_transaction_table, create_db_and_tables
from dca_service.services.dca_engine import calculate_dca_decision
from dca_service.services.metrics_provider import get_latest_metrics


@pytest.fixture
def mock_metrics():
    """Mock metrics provider to return consistent test data"""
    with patch('dca_service.services.dca_engine.get_latest_metrics') as mock:
        mock.return_value = {
            "ahr999": 0.6,
            "price_usd": 50000.0,
            "timestamp": datetime.now(timezone.utc),
            "source": "csv",
            "source_label": "CSV (test data)"
        }
        yield mock


@pytest.fixture
def old_schema_engine():
    """Create an engine with old schema (without source, fee_amount, fee_asset columns)"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    
    # Create table with old schema (without new columns)
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE dca_transactions (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                status TEXT NOT NULL,
                fiat_amount REAL NOT NULL,
                btc_amount REAL,
                price REAL NOT NULL,
                ahr999 REAL NOT NULL,
                notes TEXT,
                intended_amount_usd REAL,
                executed_amount_usd REAL,
                executed_amount_btc REAL,
                avg_execution_price_usd REAL
            )
        """))
        conn.commit()
    
    return engine


def test_migration_adds_missing_columns(old_schema_engine):
    """Test that migration correctly adds source, fee_amount, and fee_asset columns"""
    # Use the old schema engine
    from dca_service.database import engine
    original_engine = engine
    
    # Temporarily replace engine
    import dca_service.database as db_module
    db_module.engine = old_schema_engine
    
    try:
        # Run migration
        _migrate_transaction_table()
        
        # Verify columns were added
        with Session(old_schema_engine) as session:
            columns = session.exec(text("""
                SELECT name FROM pragma_table_info('dca_transactions')
            """)).all()
            # Extract column names properly
            column_names = set()
            for col in columns:
                if isinstance(col, tuple) and len(col) > 0:
                    column_names.add(col[0])
                elif hasattr(col, '__getitem__'):
                    column_names.add(col[0])
                else:
                    column_names.add(str(col))
            
            assert 'source' in column_names, f"source column should be added. Found columns: {column_names}"
            assert 'fee_amount' in column_names, f"fee_amount column should be added. Found columns: {column_names}"
            assert 'fee_asset' in column_names, f"fee_asset column should be added. Found columns: {column_names}"
    finally:
        # Restore original engine
        db_module.engine = original_engine


def test_migration_handles_existing_columns(session: Session):
    """Test that migration doesn't fail if columns already exist"""
    # Create table with all columns
    SQLModel.metadata.create_all(session.bind)
    
    # Run migration (should not fail)
    _migrate_transaction_table()
    
    # Verify columns still exist
    columns = session.exec(text("""
        SELECT name FROM pragma_table_info('dca_transactions')
    """)).all()
    # Extract column names properly
    column_names = set()
    for col in columns:
        if isinstance(col, tuple) and len(col) > 0:
            column_names.add(col[0])
        elif hasattr(col, '__getitem__'):
            column_names.add(col[0])
        else:
            column_names.add(str(col))
    
    assert 'source' in column_names, f"source column should exist. Found columns: {column_names}"
    assert 'fee_amount' in column_names, f"fee_amount column should exist. Found columns: {column_names}"
    assert 'fee_asset' in column_names, f"fee_asset column should exist. Found columns: {column_names}"


def test_transaction_creation_includes_source_and_fee(session: Session):
    """Test that new transactions are created with source, fee_amount, and fee_asset"""
    SQLModel.metadata.create_all(session.bind)
    
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=100.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        notes="Test transaction",
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC"
    )
    
    session.add(transaction)
    session.commit()
    session.refresh(transaction)
    
    assert transaction.source == "SIMULATED"
    assert transaction.fee_amount == 0.0
    assert transaction.fee_asset == "USDC"
    assert transaction.id is not None


def test_budget_calculation_monthly_reset(mock_metrics, session: Session):
    """Test that budget resets monthly when allow_over_budget=False"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy with monthly reset
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,  # Monthly reset enabled
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    # Create transaction in current month
    now = datetime.now(timezone.utc)
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=450.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC",
        timestamp=now
    )
    session.add(transaction)
    session.commit()
    
    # Calculate decision
    decision = calculate_dca_decision(session)
    
    # Should only count current month transactions
    assert decision.remaining_budget == 550.0, f"Expected 550.0, got {decision.remaining_budget}"
    assert decision.budget_resets is True
    assert decision.time_until_reset is not None


def test_budget_calculation_no_reset(mock_metrics, session: Session):
    """Test that budget accumulates when allow_over_budget=True"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy without reset
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=True,  # No reset
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    # Create transaction last month
    last_month = datetime.now(timezone.utc) - timedelta(days=35)
    transaction = DCATransaction(
        status="SUCCESS",
        fiat_amount=450.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC",
        timestamp=last_month
    )
    session.add(transaction)
    session.commit()
    
    # Calculate decision
    decision = calculate_dca_decision(session)
    
    # Should count all transactions (including last month)
    assert decision.remaining_budget == 550.0, f"Expected 550.0, got {decision.remaining_budget}"
    assert decision.budget_resets is False
    assert decision.time_until_reset is None


def test_budget_calculation_empty_transactions(mock_metrics, session: Session):
    """Test that budget calculation works correctly with no transactions"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    # Calculate decision with no transactions
    decision = calculate_dca_decision(session)
    
    # Should have full budget
    assert decision.remaining_budget == 1000.0, f"Expected 1000.0, got {decision.remaining_budget}"
    assert decision.budget_resets is True


def test_budget_calculation_only_counts_success(mock_metrics, session: Session):
    """Test that only SUCCESS transactions are counted in budget"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    # Create SUCCESS transaction
    success_tx = DCATransaction(
        status="SUCCESS",
        fiat_amount=300.0,
        btc_amount=0.001,
        price=50000.0,
        ahr999=0.5,
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC"
    )
    session.add(success_tx)
    
    # Create FAILED transaction (should not be counted)
    failed_tx = DCATransaction(
        status="FAILED",
        fiat_amount=200.0,
        btc_amount=0.0,
        price=50000.0,
        ahr999=0.5,
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC"
    )
    session.add(failed_tx)
    
    # Create SKIPPED transaction (should not be counted)
    skipped_tx = DCATransaction(
        status="SKIPPED",
        fiat_amount=100.0,
        btc_amount=0.0,
        price=50000.0,
        ahr999=0.5,
        source="SIMULATED",
        fee_amount=0.0,
        fee_asset="USDC"
    )
    session.add(skipped_tx)
    
    session.commit()
    
    # Calculate decision
    decision = calculate_dca_decision(session)
    
    # Should only count SUCCESS transaction
    assert decision.remaining_budget == 700.0, f"Expected 700.0, got {decision.remaining_budget}"


def test_api_returns_budget_info(mock_metrics, client, session: Session):
    """Test that /api/dca/preview returns budget information"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy
    from dca_service.models import DCAStrategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    # Call preview API
    response = client.get("/api/dca/preview")
    assert response.status_code == 200
    
    data = response.json()
    assert "remaining_budget" in data
    assert "budget_resets" in data
    assert "time_until_reset" in data
    
    assert data["remaining_budget"] == 1000.0
    assert data["budget_resets"] is True
    assert data["time_until_reset"] is not None


def test_simulate_transaction_creates_with_all_fields(client, session: Session):
    """Test that simulated transaction creation includes source, fee_amount, fee_asset"""
    SQLModel.metadata.create_all(session.bind)
    
    response = client.post("/api/transactions/simulate", json={
        "fiat_amount": 100.0,
        "ahr999": 0.45,
        "price": 50000.0,
        "notes": "Test"
    })
    
    assert response.status_code == 200
    data = response.json()
    
    assert "source" in data
    assert "fee_amount" in data
    assert "fee_asset" in data
    
    assert data["source"] == "SIMULATED"
    assert data["fee_amount"] == 0.0
    assert data["fee_asset"] == "USDC"


def test_execute_simulated_dca_creates_with_all_fields(mock_metrics, client, session: Session):
    """Test that execute-simulated DCA creates transaction with all fields"""
    SQLModel.metadata.create_all(session.bind)
    
    # Create strategy
    from dca_service.models import DCAStrategy
    strategy = DCAStrategy(
        is_active=True,
        total_budget_usd=1000.0,
        allow_over_budget=False,
        ahr999_multiplier_low=2.0,
        ahr999_multiplier_mid=1.0,
        ahr999_multiplier_high=0.5
    )
    session.add(strategy)
    session.commit()
    
    response = client.post("/api/dca/execute-simulated")
    assert response.status_code == 200
    
    data = response.json()
    assert "transaction" in data
    
    if data["transaction"]:
        tx = data["transaction"]
        assert "source" in tx
        assert "fee_amount" in tx
        assert "fee_asset" in tx
        
        assert tx["source"] == "SIMULATED"
        assert tx["fee_amount"] == 0.0
        assert tx["fee_asset"] == "USDC"

