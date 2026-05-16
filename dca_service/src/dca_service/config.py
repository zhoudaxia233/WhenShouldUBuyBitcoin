from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os
import subprocess
import sys
import tomllib

DEV_SESSION_SECRET_DEFAULT = "dev-secret-change-in-production-12345678901234567890"


def _find_repo_root() -> Path:
    """Find repository root by locating pyproject.toml."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _detect_app_version() -> str:
    """Read version from pyproject.toml; fallback to dev tag."""
    repo_root = _find_repo_root()
    pyproject_path = repo_root / "pyproject.toml"

    try:
        with pyproject_path.open("rb") as fh:
            pyproject = tomllib.load(fh)
        return pyproject.get("project", {}).get("version", "0.0.0-dev")
    except Exception:
        return "0.0.0-dev"


def _detect_commit_sha() -> str:
    """Resolve current git short SHA; fallback to empty string."""
    repo_root = _find_repo_root()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dca.db"
    METRICS_CSV_PATH: str = "../docs/data/btc_metrics.csv"
    METRICS_MAX_AGE_HOURS: int = 48
    METRICS_BACKEND: str = "realtime"  # "csv" or "realtime"
    METRICS_FALLBACK_TO_CSV: bool = True
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "DCA Service"
    APP_VERSION: str = _detect_app_version()
    APP_COMMIT_SHA: str = _detect_commit_sha()
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
    SESSION_SECRET: str = DEV_SESSION_SECRET_DEFAULT  # Insecure default for dev/test
    SESSION_COOKIE_NAME: str = "dca_session"
    SESSION_COOKIE_HTTPS_ONLY: bool = False  # Must be True in production with HTTPS. False for local HTTP development.
    SESSION_COOKIE_SAMESITE: str = "lax"  # "lax" or "strict" for CSRF protection
    SESSION_MAX_AGE: int = 86400  # 24 hours in seconds
    LOCAL_TIMEZONE: str = "Europe/Berlin"  # Used when strategy time_display_mode is LOCAL

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def _enforce_secure_session_secret(settings: "Settings") -> None:
    """Refuse to boot with the insecure default SESSION_SECRET when secure mode is required.

    Set DCA_REQUIRE_SECURE_SESSION=true (or 1/yes) in production to enforce; otherwise we
    only print a loud warning so dev/test workflows keep working.
    """
    if settings.SESSION_SECRET != DEV_SESSION_SECRET_DEFAULT:
        return

    require_secure = os.environ.get("DCA_REQUIRE_SECURE_SESSION", "").strip().lower() in {"1", "true", "yes"}
    msg = (
        "SESSION_SECRET is the insecure dev default. Generate one with "
        "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"` and set it in .env."
    )
    if require_secure:
        raise RuntimeError(msg)
    print(f"WARNING: {msg}", file=sys.stderr)


settings = Settings()
_enforce_secure_session_secret(settings)
