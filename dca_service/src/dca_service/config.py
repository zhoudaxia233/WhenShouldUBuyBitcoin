from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dca.db"
    METRICS_CSV_PATH: str = "../docs/data/btc_metrics.csv"
    METRICS_MAX_AGE_HOURS: int = 48
    METRICS_BACKEND: str = "realtime" # "csv" or "realtime"
    METRICS_FALLBACK_TO_CSV: bool = True
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "DCA Service"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
