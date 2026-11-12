from pathlib import Path

import pytest
from pydantic import ValidationError

from poker_trainer.settings import AppSettings, get_settings

_VARS = (
    "PPT_DATABASE_URL",
    "PPT_FRONTEND_DIST",
    "PPT_HOST",
    "PPT_PORT",
    "PPT_LLM_PROVIDER",
    "PPT_OLLAMA_URL",
    "PPT_OLLAMA_MODEL",
    "PPT_LLM_TIMEOUT",
)


def test_settings_defaults_and_env(monkeypatch):
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    s = AppSettings(_env_file=None)
    assert s.database_url == "sqlite:///./poker_trainer.db"
    assert s.frontend_dist == Path("../frontend/dist")
    assert s.host == "127.0.0.1"
    assert s.port == 8000
    assert s.llm_provider == "none"
    assert s.ollama_url == "http://127.0.0.1:11434"
    assert s.ollama_model == "llama3.2:3b"
    assert s.llm_timeout == 60.0

    monkeypatch.setenv("PPT_DATABASE_URL", "sqlite:///./other.db")
    monkeypatch.setenv("PPT_PORT", "9001")
    s = AppSettings(_env_file=None)
    assert s.database_url == "sqlite:///./other.db"
    assert s.port == 9001


def test_settings_reads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("PPT_DATABASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("PPT_DATABASE_URL=sqlite:///from-file.db\n", encoding="utf-8")
    assert AppSettings(_env_file=env).database_url == "sqlite:///from-file.db"


def test_get_settings_cached():
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_llm_settings_from_env(monkeypatch):
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PPT_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("PPT_OLLAMA_URL", "http://localhost:9999")
    monkeypatch.setenv("PPT_OLLAMA_MODEL", "mistral")
    monkeypatch.setenv("PPT_LLM_TIMEOUT", "12.5")
    s = AppSettings(_env_file=None)
    assert (s.llm_provider, s.ollama_url, s.ollama_model, s.llm_timeout) == (
        "ollama",
        "http://localhost:9999",
        "mistral",
        12.5,
    )


def test_llm_settings_validation():
    explicit = {
        "llm_provider": "ollama",
        "ollama_url": "http://127.0.0.1:11434",
        "ollama_model": "llama3.2:3b",
        "llm_timeout": 60.0,
    }
    assert AppSettings(_env_file=None, **explicit).llm_provider == "ollama"
    for bad in ({"llm_provider": "openai"}, {"llm_timeout": 0}, {"llm_timeout": -1.0}):
        with pytest.raises(ValidationError):
            AppSettings(_env_file=None, **{**explicit, **bad})
