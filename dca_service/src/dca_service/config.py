from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dca.db"
    METRICS_CSV_PATH: str = "../docs/data/btc_metrics.csv"
    METRICS_MAX_AGE_HOURS: int = 48
    METRICS_BACKEND: str = "realtime"  # "csv" or "realtime"
    METRICS_FALLBACK_TO_CSV: bool = True
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "DCA Service"
    BINANCE_CRED_ENC_KEY: str = ""  # Required for saving credentials
    DCA_QUOTE_ASSET: str = "USDC"
    
    # Email Notification Settings
    EMAIL_ENABLED: bool = False
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 587  # Default TLS port
    EMAIL_SMTP_USER: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_TO: str = ""

    # Logging Settings
    LOG_LEVEL: str = "INFO"
    LOG_FILE_PATH: str = "logs/dca_service.log"
    
    # Session Settings (for authentication)
    # WARNING: In production, MUST set a strong random SESSION_SECRET
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    SESSION_SECRET: str = "dev-secret-change-in-production-12345678901234567890"  # Insecure default for dev/test
    SESSION_COOKIE_NAME: str = "dca_session"
    SESSION_COOKIE_HTTPS_ONLY: bool = False  # Must be True in production with HTTPS. False for local HTTP development.
    SESSION_COOKIE_SAMESITE: str = "lax"  # "lax" or "strict" for CSRF protection
    SESSION_MAX_AGE: int = 86400  # 24 hours in seconds

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
