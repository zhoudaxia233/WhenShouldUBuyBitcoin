from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str  # SUCCESS, FAILED, SKIPPED
    fiat_amount: float
    btc_amount: Optional[float] = None
    price: float
    ahr999: float
    notes: Optional[str] = None
