from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to .env — works regardless of the process's working directory
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: str = "development"
    secret_key: str = "change-me-in-production"

    # Upstox
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_access_token: str = ""

    # Fyers
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_access_token: str = ""

    # Angel One SmartAPI
    angel_api_key: str = ""
    angel_access_token: str = ""

    # Dhan
    dhan_client_id: str = ""
    dhan_app_id: str = ""
    dhan_app_secret: str = ""
    dhan_access_token: str = ""

    # ICICI Direct Breeze
    icici_api_key: str = ""
    icici_api_secret: str = ""
    icici_access_token: str = ""

    # Broker selection — comma-separated e.g. "upstox,fyers"
    active_brokers: str = ""

    # Data pipeline
    scraper_timeout_seconds: int = 15
    pipeline_max_retries: int = 2

    # Storage
    db_path: str = "portfolio_mcp.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def update_env_key(key: str, value: str) -> None:
    """Write / update a single key in .env and clear the settings cache."""
    import re

    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        raise FileNotFoundError(f".env not found at {env_file}")

    text = env_file.read_text()
    pattern = rf"^({re.escape(key)}\s*=).*$"
    if re.search(pattern, text, re.MULTILINE):
        text = re.sub(pattern, f"{key}={value}", text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"

    env_file.write_text(text)
    get_settings.cache_clear()


# Convenience wrappers kept for backward compat
def update_token(new_token: str) -> None:
    update_env_key("UPSTOX_ACCESS_TOKEN", new_token)
