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

class SimulationRequest(BaseModel):
    fiat_amount: float
    ahr999: float
    price: float
    notes: Optional[str] = None

