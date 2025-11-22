from datetime import datetime
from typing import Optional
from pydantic import BaseModel

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

class ManualTransactionCreate(BaseModel):
    type: str  # BUY, TRANSFER_IN, TRANSFER_OUT, OTHER
    btc_amount: float
    fiat_amount: Optional[float] = None
    price_usd: Optional[float] = None
    fee_usdc: Optional[float] = None
    notes: Optional[str] = None
    timestamp: Optional[datetime] = None

class ManualTransactionRead(BaseModel):
    id: int
    timestamp: datetime
    type: str
    btc_amount: float
    fiat_amount: Optional[float] = None
    price_usd: Optional[float] = None
    fee_usdc: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime

# Unified schema for list display
class UnifiedTransaction(BaseModel):
    id: str # Changed from int to str to support prefixes (e.g. "DCA-1", "MAN-1")
    timestamp: datetime
    type: str # BUY, SELL, TRANSFER_IN, TRANSFER_OUT, OTHER, DCA
    status: str # SUCCESS, FAILED, SKIPPED, COMPLETED (for manual)
    btc_amount: Optional[float] = None
    fiat_amount: Optional[float] = None
    price: Optional[float] = None
    notes: Optional[str] = None
    source: str # SIMULATED, BINANCE, LEDGER (MANUAL)
    
    # Extra fields for DCA
    ahr999: Optional[float] = None
    
    # Extra fields for Manual
    fee_usdc: Optional[float] = None

