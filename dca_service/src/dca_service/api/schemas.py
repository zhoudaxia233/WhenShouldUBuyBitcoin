from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class MetricsSourceSchema(BaseModel):
    """Schema for metrics source information"""
    backend: str  # "csv" or "realtime"
    label: str    # Human-readable description

class TransactionBase(BaseModel):
    status: str
    fiat_amount: float
    btc_amount: Optional[float] = None
    price: float
    ahr999: float
    notes: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionRead(TransactionBase):
    id: int
    timestamp: datetime
    # New fields for Phase 6
    intended_amount_usd: Optional[float] = None
    executed_amount_usd: Optional[float] = None
    executed_amount_btc: Optional[float] = None
    avg_execution_price_usd: Optional[float] = None
    fee_amount: Optional[float] = None
    fee_asset: Optional[str] = None
    source: Optional[str] = "SIMULATED"  # SIMULATED, BINANCE, LEDGER

class SimulationRequest(BaseModel):
    fiat_amount: float
    ahr999: float
    price: float
    notes: Optional[str] = None

class ColdWalletEntryCreate(BaseModel):
    btc_amount: float
    fee_btc: Optional[float] = None
    notes: Optional[str] = None
    timestamp: datetime

class ColdWalletEntryRead(BaseModel):
    id: int
    timestamp: datetime
    btc_amount: float
    fee_btc: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime

# Unified schema for list display
class UnifiedTransaction(BaseModel):
    id: str # Changed from int to str to support prefixes (e.g. "DCA-1", "MAN-1")
    timestamp: datetime
    type: str # BUY, SELL, TRANSFER_IN, TRANSFER_OUT, OTHER, DCA, MANUAL
    status: str # SUCCESS, FAILED, SKIPPED, COMPLETED (for manual)
    btc_amount: Optional[float] = None
    fiat_amount: Optional[float] = None
    price: Optional[float] = None
    notes: Optional[str] = None
    source: str # SIMULATED, BINANCE, LEDGER (MANUAL)
    
    # Extra fields for DCA
    ahr999: Optional[float] = None
    
    # Extra fields for Manual (Legacy/Optional)
    fee_usdc: Optional[float] = None

# Strategy Schemas (Merged from schemas_strategy.py)
class StrategyBase(BaseModel):
    is_active: bool = False
    total_budget_usd: float
    enforce_monthly_cap: bool = True
    ahr999_multiplier_low: float
    ahr999_multiplier_mid: float
    ahr999_multiplier_high: float
    target_btc_amount: float = 1.0
    execution_frequency: str = "daily"
    execution_day_of_week: Optional[str] = None
    execution_time_utc: str = "00:00"
    
    # Dynamic Strategy Config
    strategy_type: str = "legacy_band" # "legacy_band" or "dynamic_ahr999"
    dynamic_min_multiplier: Optional[float] = None
    dynamic_max_multiplier: Optional[float] = None
    dynamic_gamma: Optional[float] = None
    dynamic_a_low: Optional[float] = None
    dynamic_a_high: Optional[float] = None
    dynamic_enable_drawdown_boost: Optional[float] = None

class StrategyCreate(StrategyBase):
    pass

class StrategyUpdate(StrategyBase):
    pass

class StrategyRead(StrategyBase):
    id: int
    created_at: datetime
    updated_at: datetime
