"""Application settings, read from the environment (12-factor).

One `Settings` class, reached only through `get_settings`, which is cached so the
environment is read once per process.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "martingale-wall-simulator"
    log_level: str = "INFO"

    # Console renderer for a terminal, one JSON object per line for a log
    # platform. The deploy sets this to true; local development leaves it off.
    log_json: bool = False

    # SQLite for the prototype; a Postgres or MySQL URL is the only change in production.
    database_url: str = "sqlite:///./app.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
