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
    enforce_monthly_cap: bool = Field(default=True)  # Enforce monthly budget limit
    ahr999_multiplier_low: float  # Legacy field, kept for backward compatibility
    ahr999_multiplier_mid: float  # Legacy field, kept for backward compatibility
    ahr999_multiplier_high: float  # Legacy field, kept for backward compatibility
    
    # AHR999 Percentile Strategy multipliers (6 tiers)
    ahr999_multiplier_p10: Optional[float] = Field(default=None)  # Bottom 10% (EXTREME CHEAP)
    ahr999_multiplier_p25: Optional[float] = Field(default=None)  # 10-25% (Very Cheap)
    ahr999_multiplier_p50: Optional[float] = Field(default=None)  # 25-50% (Cheap)
    ahr999_multiplier_p75: Optional[float] = Field(default=None)  # 50-75% (Fair)
    ahr999_multiplier_p90: Optional[float] = Field(default=None)  # 75-90% (Expensive)
    ahr999_multiplier_p100: Optional[float] = Field(default=None)  # Top 10% (VERY EXPENSIVE)
    
    target_btc_amount: float = Field(default=1.0)
    execution_frequency: str = Field(default="daily") # "daily" or "weekly"
    execution_day_of_week: Optional[str] = Field(default=None) # "monday", "tuesday", etc. (only for weekly)
    execution_time_utc: str = Field(default="00:00") # "HH:MM"
    
    # Strategy Configuration
    strategy_type: str = Field(default="legacy_band") # "legacy_band" or "dynamic_ahr999"
    
    # Execution Mode (Phase 9: Execution Mode Plumbing)
    execution_mode: str = Field(default="DRY_RUN")  # "DRY_RUN" or "LIVE"
    
    # Dynamic Strategy Config (Nullable, used if strategy_type="dynamic_ahr999")
    dynamic_min_multiplier: Optional[float] = None
    dynamic_max_multiplier: Optional[float] = None
    dynamic_gamma: Optional[float] = None
    dynamic_a_low: Optional[float] = None
    dynamic_a_high: Optional[float] = None
    dynamic_enable_drawdown_boost: Optional[bool] = None

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

