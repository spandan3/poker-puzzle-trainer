from sqlalchemy import select

from poker_trainer.db import DEFAULT_USER_ID, UserSettings
from poker_trainer.villain.profiles import PROFILE_NAMES


def test_settings_get_defaults(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["show_pot_odds"] is True
    assert body["show_profile"] is True
    assert body["profile"] is None
    assert body["daily_goal"] == 10
    assert body["llm_provider"] == "none"
    assert body["llm_status"] == "off"
    assert body["llm_model"] is None
    assert body["llm_detail"] is None
    assert [p["name"] for p in body["profiles"]] == list(PROFILE_NAMES)
    assert len(body["profiles"]) == 4
    assert all(p["label"] and p["description"] for p in body["profiles"])


def test_settings_patch_partial(client, sessions):
    with sessions() as db:
        before = db.scalar(select(UserSettings).where(UserSettings.user_id == DEFAULT_USER_ID))
        t0 = before.updated_at
    r = client.patch("/api/settings", json={"daily_goal": 25, "profile": "lag"})
    assert r.status_code == 200
    body = r.json()
    assert body["daily_goal"] == 25 and body["profile"] == "lag"
    assert body["show_pot_odds"] is True and body["show_profile"] is True
    again = client.patch("/api/settings", json={"show_pot_odds": False}).json()
    assert again["show_pot_odds"] is False
    assert again["daily_goal"] == 25 and again["profile"] == "lag"  # omitted: unchanged
    assert client.get("/api/settings").json() == again
    with sessions() as db:
        row = db.scalar(select(UserSettings).where(UserSettings.user_id == DEFAULT_USER_ID))
        assert row.updated_at > t0
        assert row.updated_at.utcoffset().total_seconds() == 0


def test_settings_validation(client):
    bad = [
        {"profile": "nope"},
        {"daily_goal": 0},
        {"daily_goal": 501},
        {"daily_goal": 1.5},
        {"show_pot_odds": None},
        {"show_pot_odds": 1},
        {"show_profile": "false"},
        {"daily_goal": "10"},
        {"daily_goal": True},
        {"llm_provider": "none"},
        {"llm_status": "off"},
        {"llm_model": "mistral"},
        {"llm_detail": "x"},
        {"profiles": []},
        {"bogus": 1},
    ]
    for body in bad:
        assert client.patch("/api/settings", json=body).status_code == 422, body
    assert client.get("/api/settings").json()["daily_goal"] == 10


def test_settings_profile_null_resets(client):
    client.patch("/api/settings", json={"profile": "sticky"})
    assert client.get("/api/settings").json()["profile"] == "sticky"
    r = client.patch("/api/settings", json={"profile": None})
    assert r.status_code == 200 and r.json()["profile"] is None
    r = client.patch("/api/settings", json={})
    assert r.status_code == 200 and r.json()["profile"] is None


def _client_with_probe(db_url, factory, llm_off, probe, clock, provider="ollama"):
    from fastapi.testclient import TestClient

    from poker_trainer.api.app import create_app
    from poker_trainer.explain.service import Explainer
    from poker_trainer.settings import AppSettings

    settings = AppSettings(
        _env_file=None, database_url=db_url, **{**llm_off, "llm_provider": provider}
    )
    explainer = Explainer(settings, probe=probe, clock=clock)
    return TestClient(create_app(settings, puzzle_factory=factory, explainer=explainer))


def test_llm_check_re_probes_past_the_cache(db_url, factory, llm_off):
    calls = []
    answer = [("unavailable", "Ollama isn't answering.")]

    def probe(url, model, timeout=1.5):
        calls.append(model)
        return answer[0]

    with _client_with_probe(db_url, factory, llm_off, probe, lambda: 0.0) as c:
        first = c.get("/api/settings").json()
        assert first["llm_status"] == "unavailable"
        answer[0] = ("ready", None)
        assert c.get("/api/settings").json()["llm_status"] == "unavailable"  # cached
        assert len(calls) == 1
        r = c.post("/api/settings/llm-check")
        assert r.status_code == 200
        body = r.json()
        assert body["llm_status"] == "ready" and body["llm_detail"] is None
        assert set(body) == set(first)  # the full SettingsView
        assert len(calls) == 2
        assert c.get("/api/settings").json()["llm_status"] == "ready"
        assert len(calls) == 2


def test_llm_check_with_provider_none_does_not_probe(db_url, factory, llm_off):
    calls = []

    def probe(*_a, **_k):
        calls.append(1)
        return "ready", None

    with _client_with_probe(db_url, factory, llm_off, probe, lambda: 0.0, provider="none") as c:
        body = c.post("/api/settings/llm-check").json()
        assert body["llm_status"] == "off" and body["llm_detail"] is None
    assert calls == []


def test_patch_never_probes(db_url, factory, llm_off):
    calls = []

    def probe(*_a, **_k):
        calls.append(1)
        return "ready", None

    with _client_with_probe(db_url, factory, llm_off, probe, lambda: 0.0) as c:
        r = c.patch("/api/settings", json={"daily_goal": 12})
        assert r.status_code == 200
        assert r.json()["llm_status"] == "unavailable"
        assert r.json()["llm_detail"] == "Not checked yet."
    assert calls == []
