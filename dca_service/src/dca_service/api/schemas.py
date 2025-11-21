from datetime import datetime
from typing import Optional
from pydantic import BaseModel

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

class SimulationRequest(BaseModel):
    fiat_amount: float
    ahr999: float
    price: float
    notes: Optional[str] = None
