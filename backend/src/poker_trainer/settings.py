"""Environment config (prefix ``PPT_``), with an optional ``.env`` in the working directory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Every setting has a safe default; tests pass ``_env_file=None`` to ignore a local ``.env``."""

    model_config = SettingsConfigDict(
        env_prefix="PPT_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./poker_trainer.db"
    frontend_dist: Path = Path("../frontend/dist")
    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: Literal["none"] = "none"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
