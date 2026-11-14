"""``GET /api/attempts/{id}/explanation`` and the LLM status in the settings."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from poker_trainer.api.app import create_app
from poker_trainer.api.schemas import Explanation
from poker_trainer.db import AttemptRow, PuzzleRow, User
from poker_trainer.explain import ollama
from poker_trainer.explain.service import Explainer
from poker_trainer.settings import AppSettings


def _settings(db_url: str, provider: str = "ollama", **kw: Any) -> AppSettings:
    base = {
        "database_url": db_url,
        "llm_provider": provider,
        "ollama_url": "http://127.0.0.1:1",
        "ollama_model": "llama3.2:3b",
        "llm_timeout": 5.0,
    }
    return AppSettings(_env_file=None, **{**base, **kw})


def _reword(_url, _model, _system, prompt, _schema, _timeout) -> str:
    fields = ollama.template_fields(prompt)
    return json.dumps({**fields, "headline": "In short: " + fields["headline"]})


def _app_client(db_url, factory, explainer, settings=None):
    settings = settings or _settings(db_url)
    return TestClient(create_app(settings, puzzle_factory=factory, explainer=explainer))


def _submit(client) -> dict[str, Any]:
    pid = client.post("/api/puzzles", json={"street": "river"}).json()["id"]
    r = client.post(f"/api/puzzles/{pid}/attempts", json={"option": 0, "equity_guess": 0.4})
    assert r.status_code == 201, r.text
    return r.json()


def test_default_explainer_is_on_app_state(db_url, factory):
    app = create_app(_settings(db_url, "none"), puzzle_factory=factory)
    assert isinstance(app.state.explainer, Explainer)


def test_llm_explanation(db_url, factory):
    s = _settings(db_url)
    with _app_client(db_url, factory, Explainer(s, generate=_reword), s) as client:
        res = _submit(client)
        r = client.get(f"/api/attempts/{res['attempt']['id']}/explanation")
        assert r.status_code == 200
        body = r.json()
        Explanation.model_validate(body)
        assert body["source"] == "llm" and body["model"] == "llama3.2:3b"
        assert body["headline"] == "In short: " + res["explanation"]["headline"]
        assert body["sections"][2] == res["explanation"]["sections"][2]
        # the stored result still carries the template
        again = client.get(f"/api/attempts/{res['attempt']['id']}").json()
        assert again["explanation"] == res["explanation"]


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (ollama.LlmUnavailable("down"), "unavailable"),
        (ollama.LlmTimeout("slow"), "timeout"),
        (ollama.LlmError("HTTP 500"), "error"),
        (ValueError("a bug"), "error"),
    ],
)
def test_model_failures_never_5xx(db_url, factory, exc, reason):
    def broken(*_a: Any) -> str:
        raise exc

    s = _settings(db_url)
    with _app_client(db_url, factory, Explainer(s, generate=broken), s) as client:
        res = _submit(client)
        r = client.get(f"/api/attempts/{res['attempt']['id']}/explanation")
        assert r.status_code == 200
        assert r.json() == {**res["explanation"], "fallback": reason}


def test_guardrail_rejection(db_url, factory):
    def liar(*_a: Any) -> str:
        return json.dumps({"headline": "You win 99 bb.", "hand": "x", "verdict": "y"})

    s = _settings(db_url)
    with _app_client(db_url, factory, Explainer(s, generate=liar), s) as client:
        res = _submit(client)
        body = client.get(f"/api/attempts/{res['attempt']['id']}/explanation").json()
        assert body == {**res["explanation"], "fallback": "guardrail"}


def test_not_found_rules(client, sessions):
    assert client.get("/api/attempts/999/explanation").status_code == 404
    assert client.get("/api/attempts/0/explanation").status_code == 404
    assert client.get("/api/attempts/x/explanation").status_code == 422
    res = _submit(client)
    aid = res["attempt"]["id"]
    assert client.get(f"/api/attempts/{aid}/explanation").status_code == 200
    with sessions() as db:
        db.add(User(id=2, name="other"))
        db.flush()
        db.execute(update(PuzzleRow).values(user_id=2))
        db.execute(update(AttemptRow).where(AttemptRow.id == aid).values(user_id=2))
        db.commit()
    r = client.get(f"/api/attempts/{aid}/explanation")
    assert r.status_code == 404 and r.json() == {"detail": "attempt not found"}


def test_provider_none_needs_no_network(db_url, factory, monkeypatch):
    """Review Focus 5: with provider none nothing calls Ollama, on any route."""

    def no_network(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network call with provider none")

    monkeypatch.setattr(ollama, "generate", no_network)
    monkeypatch.setattr(ollama, "probe", no_network)
    monkeypatch.setattr(ollama, "_opener", no_network)
    # every LLM variable set, as on a dev machine that tried Ollama once
    s = _settings(db_url, "none", ollama_model="mistral")
    with TestClient(create_app(s, puzzle_factory=factory)) as client:
        res = _submit(client)
        aid = res["attempt"]["id"]
        assert client.get(f"/api/attempts/{aid}").status_code == 200
        body = client.get(f"/api/attempts/{aid}/explanation").json()
        assert body == {**res["explanation"], "fallback": "off"}
        settings = client.get("/api/settings").json()
        assert settings["llm_provider"] == "none"
        assert settings["llm_status"] == "off"
        assert settings["llm_model"] is None and settings["llm_detail"] is None
        patched = client.patch("/api/settings", json={"daily_goal": 12}).json()
        assert patched["llm_status"] == "off" and patched["llm_model"] is None


# ---------------------------------------------------------------------------
# Settings: llm_status
# ---------------------------------------------------------------------------


def _probe(answer):
    calls = []

    def probe(url: str, model: str, timeout: float = 1.5):
        calls.append((url, model))
        return answer

    return probe, calls


def test_settings_ready(db_url, factory):
    s = _settings(db_url)
    probe, calls = _probe(("ready", None))
    with _app_client(db_url, factory, Explainer(s, probe=probe), s) as client:
        body = client.get("/api/settings").json()
        assert body["llm_provider"] == "ollama"
        assert body["llm_status"] == "ready"
        assert body["llm_model"] == "llama3.2:3b"
        assert body["llm_detail"] is None
        assert calls == [("http://127.0.0.1:1", "llama3.2:3b")]


def test_settings_unavailable_with_detail(db_url, factory):
    s = _settings(db_url)
    detail = "Ollama isn't answering at http://127.0.0.1:1."
    probe, _ = _probe(("unavailable", detail))
    with _app_client(db_url, factory, Explainer(s, probe=probe), s) as client:
        body = client.get("/api/settings").json()
        assert (body["llm_status"], body["llm_detail"]) == ("unavailable", detail)
        assert body["llm_model"] == "llama3.2:3b"


def test_settings_patch_reports_the_cached_probe_without_probing(db_url, factory):
    s = _settings(db_url)
    probe, calls = _probe(("ready", None))
    with _app_client(db_url, factory, Explainer(s, probe=probe), s) as client:
        body = client.patch("/api/settings", json={"daily_goal": 12}).json()
        assert (body["llm_status"], body["llm_detail"]) == ("unavailable", "Not checked yet.")
        assert calls == []
        client.get("/api/settings")
        body = client.patch("/api/settings", json={"daily_goal": 13}).json()
        assert (body["llm_status"], body["llm_detail"]) == ("ready", None)
        assert len(calls) == 1
