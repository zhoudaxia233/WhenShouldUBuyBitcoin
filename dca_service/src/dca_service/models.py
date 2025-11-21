from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class DCATransaction(SQLModel, table=True):
    __tablename__ = "dca_transactions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str  # SUCCESS, FAILED, SKIPPED
    fiat_amount: float = Field(alias="amount_usd") # Mapping old field if needed, or just renaming
    btc_amount: Optional[float] = Field(default=None, alias="amount_btc")
    price: float
    ahr999: float = Field(alias="ahr999_value")
    notes: Optional[str] = Field(default=None, alias="note")

    # Pydantic v2 config to allow population by alias
    model_config = {"populate_by_name": True}

class DCAStrategy(SQLModel, table=True):
    __tablename__ = "dca_strategy"

    id: Optional[int] = Field(default=None, primary_key=True)
    is_active: bool = Field(default=False)
    total_budget_usd: float
    allow_over_budget: bool = Field(default=False)
    ahr999_multiplier_low: float
    ahr999_multiplier_mid: float
    ahr999_multiplier_high: float
    target_btc_amount: float = Field(default=1.0)
    execution_frequency: str = Field(default="daily") # "daily" or "weekly"
    execution_time_utc: str = Field(default="00:00") # "HH:MM"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

