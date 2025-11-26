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
    
    # Binance order ID (for LIVE trades executed by the bot)
    binance_order_id: Optional[int] = None  # Binance order ID to match trades
    
    # New fields for Incremental Sync (Phase 7)
    binance_trade_id: Optional[int] = Field(default=None, sa_column_kwargs={"unique": True})  # Unique trade ID from Binance
    is_manual: bool = Field(default=False)  # True if imported from Binance history, False if created by DCA bot

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
    
    id: int | None = Field(default=None, primary_key=True)
    credential_type: str = Field(default="READ_ONLY", index=True)  # "READ_ONLY" or "TRADING"
    api_key_encrypted: str
    api_secret_encrypted: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



class GlobalSettings(SQLModel, table=True):
    """
    Application-wide settings stored as a singleton record.
    Always uses id=1 to ensure single instance.
    """
    __tablename__ = "global_settings"
    
    id: int = Field(default=1, primary_key=True)
    cold_wallet_balance: float = Field(default=0.0)  # Current BTC in cold storage
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmailSettings(SQLModel, table=True):
    """
    Email SMTP configuration with encrypted password storage.
    Similar to BinanceCredentials pattern.
    """
    __tablename__ = "email_settings"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    is_enabled: bool = Field(default=False)
    smtp_host: str
    smtp_port: int = Field(default=587)
    smtp_user: str
    smtp_password_encrypted: str  # Encrypted password
    email_from: str
    email_to: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
