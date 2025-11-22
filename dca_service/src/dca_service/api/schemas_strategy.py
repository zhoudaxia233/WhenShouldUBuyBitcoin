from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class StrategyBase(BaseModel):
    is_active: bool = False
    total_budget_usd: float
    allow_over_budget: bool = False
    ahr999_multiplier_low: float
    ahr999_multiplier_mid: float
    ahr999_multiplier_high: float
    target_btc_amount: float = 1.0
    execution_frequency: str = "daily"
    execution_day_of_week: Optional[str] = None
    execution_time_utc: str = "00:00"

class StrategyCreate(StrategyBase):
    pass

class StrategyUpdate(StrategyBase):
    pass

class StrategyRead(StrategyBase):
    id: int
    created_at: datetime
    updated_at: datetime
