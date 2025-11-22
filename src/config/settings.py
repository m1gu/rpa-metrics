from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Project root (two levels up from this file: src/config/settings.py -> src -> repo root)
ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"

# Load .env if present; fallback to real environment otherwise.
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()


def _get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable '{name}'")
    return value


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True)
class PlaywrightSettings:
    base_url: str
    username: str
    password: str
    headless: bool
    slow_mo_ms: int


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    schema: str
    table: str

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass(frozen=True)
class RuntimeSettings:
    log_level: str
    max_retries: int
    retry_backoff_seconds: int
    date_range_days: int


@dataclass(frozen=True)
class Settings:
    playwright: PlaywrightSettings
    database: DatabaseSettings
    runtime: RuntimeSettings

    @classmethod
    def from_env(cls) -> "Settings":
        playwright_settings = PlaywrightSettings(
            base_url=_get_env("METRC_BASE_URL"),
            username=_get_env("METRC_USERNAME"),
            password=_get_env("METRC_PASSWORD"),
            headless=_get_bool("PLAYWRIGHT_HEADLESS", True),
            slow_mo_ms=_get_int("PLAYWRIGHT_SLOWMO_MS", 0),
        )
        database_settings = DatabaseSettings(
            host=_get_env("POSTGRES_HOST"),
            port=_get_int("POSTGRES_PORT", 5432),
            database=_get_env("POSTGRES_DB"),
            user=_get_env("POSTGRES_USER"),
            password=_get_env("POSTGRES_PASSWORD"),
            schema=_get_env("POSTGRES_SCHEMA", "public"),
            table=_get_env("POSTGRES_TABLE", "metrc_packages"),
        )
        runtime_settings = RuntimeSettings(
            log_level=_get_env("LOG_LEVEL", "INFO"),
            max_retries=_get_int("MAX_RETRIES", 3),
            retry_backoff_seconds=_get_int("RETRY_BACKOFF_SECONDS", 5),
            date_range_days=_get_int("DATE_RANGE_DAYS", 30),
        )
        return cls(
            playwright=playwright_settings,
            database=database_settings,
            runtime=runtime_settings,
        )


settings = Settings.from_env()

__all__ = ["settings", "Settings", "DatabaseSettings", "PlaywrightSettings", "RuntimeSettings"]

