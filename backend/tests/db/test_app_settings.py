from pathlib import Path

from poker_trainer.settings import AppSettings, get_settings

_VARS = ("PPT_DATABASE_URL", "PPT_FRONTEND_DIST", "PPT_HOST", "PPT_PORT", "PPT_LLM_PROVIDER")


def test_settings_defaults_and_env(monkeypatch):
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    s = AppSettings(_env_file=None)
    assert s.database_url == "sqlite:///./poker_trainer.db"
    assert s.frontend_dist == Path("../frontend/dist")
    assert s.host == "127.0.0.1"
    assert s.port == 8000
    assert s.llm_provider == "none"

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
