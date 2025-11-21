from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dca.db"
    METRICS_FILE_PATH: str = "data/metrics.csv"
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "DCA Service"

    class Config:
        env_file = ".env"

settings = Settings()
