"""Environment config (prefix ``PPT_``), with an optional ``.env`` in the working directory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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
    # The optional local model that rewords explanations (spec §9). "none": templates only, and
    # nothing calls a network. "ollama": ask the Ollama server at ``ollama_url``.
    llm_provider: Literal["none", "ollama"] = "none"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    llm_timeout: float = Field(default=60.0, gt=0)  # seconds; a cold model on CPU is slow


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
