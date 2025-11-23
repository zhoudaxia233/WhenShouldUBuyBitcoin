from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel

class DCATransaction(SQLModel, table=True):
    __tablename__ = "dca_transactions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str  # SUCCESS, FAILED, SKIPPED
    
    # Legacy fields (keep for backwards compatibility)
    fiat_amount: float = Field(alias="amount_usd")
    btc_amount: Optional[float] = Field(default=None, alias="amount_btc")
    price: float
    ahr999: float = Field(alias="ahr999_value")
    notes: Optional[str] = Field(default=None, alias="note")
    
    # New fields for Binance integration (Phase 6)
    # Intent fields - what we wanted to execute
    intended_amount_usd: Optional[float] = None
    
    # Execution fields - what actually happened (for future Binance fills)
    executed_amount_usd: Optional[float] = None
    executed_amount_btc: Optional[float] = None
    avg_execution_price_usd: Optional[float] = None
    
    # Fee fields (for future Binance trading)
    fee_amount: Optional[float] = None
    fee_asset: Optional[str] = None
    
    # Source field - where the transaction came from
    source: Optional[str] = Field(default="SIMULATED")  # SIMULATED, BINANCE, LEDGER

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
    execution_day_of_week: Optional[str] = Field(default=None) # "monday", "tuesday", etc. (only for weekly)
    execution_time_utc: str = Field(default="00:00") # "HH:MM"
    
    # Strategy Configuration
    strategy_type: str = Field(default="legacy_band") # "legacy_band" or "dynamic_ahr999"
    
    # Dynamic Strategy Config (Nullable, used if strategy_type="dynamic_ahr999")
    dynamic_min_multiplier: Optional[float] = None
    dynamic_max_multiplier: Optional[float] = None
    dynamic_gamma: Optional[float] = None
    dynamic_a_low: Optional[float] = None
    dynamic_a_high: Optional[float] = None
    dynamic_enable_drawdown_boost: Optional[bool] = None
    dynamic_enable_monthly_cap: Optional[bool] = None
    dynamic_monthly_cap: Optional[float] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class BinanceCredentials(SQLModel, table=True):
    __tablename__ = "binance_credentials"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    api_key_encrypted: str
    api_secret_encrypted: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ColdWalletEntry(SQLModel, table=True):
    __tablename__ = "cold_wallet_entries"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    btc_amount: float
    fee_btc: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

