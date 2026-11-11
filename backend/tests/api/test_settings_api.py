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
