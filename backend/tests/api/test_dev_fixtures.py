import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from poker_trainer.api import service
from poker_trainer.api.dev_fixtures import (
    _dump,
    find_never_continues,
    search,
    write_fixtures,
    write_llm_fixture,
    write_play5_fixtures,
    write_play_fixtures,
)
from poker_trainer.api.schemas import (
    HandAnalysis,
    PlayHandSummary,
    PlaySessionSummary,
    PlaySessionView,
)
from poker_trainer.explain.guardrail import unknown_numbers
from poker_trainer.explain.service import Explainer

ATTEMPTS = ("bet", "fold", "call", "raise_preflop", "fold_preflop", "check_river", "custom")


def test_dump_rounds_floats(tmp_path):
    path = tmp_path / "x.json"
    _dump(path, {"a": 0.1 + 0.2, "b": [1, 2.0000000000004], "c": True, "d": "x", "e": 1e-20})
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == {"a": 0.3, "b": [1, 2.0], "c": True, "d": "x", "e": 1e-20}
    assert "1e-20" in text and "0.30000000000000004" not in text


def test_find_never_continues_raises_when_none_found():
    with pytest.raises(RuntimeError, match="always folds to within 1 seeds"):
        find_never_continues(max_seed=1)


@pytest.mark.slow  # search() takes a few minutes
def test_write_fixtures_writes_all_attempts(tmp_path):
    write_fixtures(tmp_path, search())  # no never-continues option: that file is skipped
    for name in ATTEMPTS:
        assert (tmp_path / f"attempt_{name}.json").is_file(), name
    assert not (tmp_path / "attempt_never_continues.json").exists()
    assert (tmp_path / "explanation_llm.json").is_file()
    custom = json.loads((tmp_path / "attempt_custom.json").read_text(encoding="utf-8"))
    last = custom["options"][-1]
    assert last["is_chosen"] is True
    # a custom size that beats every listed option is the one best row
    beats = last["ev_chips"] > max(o["ev_chips"] for o in custom["options"][:-1])
    assert last["is_best"] is beats
    assert sum(o["is_best"] for o in custom["options"]) == 1
    raise_pf = json.loads((tmp_path / "attempt_raise_preflop.json").read_text(encoding="utf-8"))
    assert raise_pf["answer"]["action"]["kind"] == "raise"
    assert raise_pf["grade"]["intent"] == "value"


def test_write_llm_fixture(client, tmp_path):
    pid = client.post("/api/puzzles", json={"street": "flop"}).json()["id"]
    res = client.post(f"/api/puzzles/{pid}/attempts", json={"option": 0, "equity_guess": 0.4})
    template = res.json()["explanation"]
    real = client.app.state.explainer
    write_llm_fixture(tmp_path, client.app, client, res.json()["attempt"]["id"])
    assert client.app.state.explainer is real and isinstance(real, Explainer)
    body = json.loads((tmp_path / "explanation_llm.json").read_text(encoding="utf-8"))
    assert body["source"] == "llm" and body["fallback"] is None
    assert body["headline"] == "In short: " + template["headline"]
    assert body["sections"][2] == template["sections"][2]
    # the rewording adds no number: every number is one of the template's
    text = "\n".join([body["headline"], *(p for s in body["sections"] for p in s["paragraphs"])])
    template_text = "\n".join(
        [template["headline"], *(p for s in template["sections"] for p in s["paragraphs"])]
    )
    assert unknown_numbers(text, template_text) == set()


PLAY_FILES = {
    "play_session_hero_to_act.json": PlaySessionView,
    "play_session_hand_over_fold.json": PlaySessionView,
    "play_session_hand_over_showdown.json": PlaySessionView,
    "play_hand_analysis.json": HandAnalysis,
    "play_sessions.json": TypeAdapter(list[PlaySessionSummary]),
    "play_hands.json": TypeAdapter(list[PlayHandSummary]),
}
FIXTURES_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "test" / "fixtures"


def _validate(model, data):
    if isinstance(model, TypeAdapter):
        return model.validate_python(data)
    return model.model_validate(data)


def _check_play_fixtures(out):
    """Each file is LF-only, valid for its response model, and covers what the UI needs."""
    data = {}
    for name, model in PLAY_FILES.items():
        raw = (out / name).read_bytes()
        assert raw.endswith(b"\n") and b"\r" not in raw, name
        data[name] = json.loads(raw)
        _validate(model, data[name])
    to_act = data["play_session_hero_to_act.json"]["hand"]
    assert to_act["status"] == "in_progress" and to_act["options"]
    fold = data["play_session_hand_over_fold.json"]["hand"]
    assert fold["outcome"]["ended_by"] == "fold" and fold["decision_count"] >= 1
    showdown = data["play_session_hand_over_showdown.json"]["hand"]
    assert showdown["outcome"]["ended_by"] == "showdown" and showdown["decision_count"] >= 2
    analysis = data["play_hand_analysis.json"]
    graded = [d for d in analysis["decisions"] if d is not None and d["status"] == "graded"]
    assert None not in analysis["decisions"] and len(graded) >= 2
    assert analysis["summary"] is not None
    assert any(h["analysed"] for h in data["play_hands.json"])
    return data


def test_write_play_fixtures_deterministic(tmp_path):
    real_clock = service.utcnow
    write_play_fixtures(tmp_path / "a", samples=500)
    write_play_fixtures(tmp_path / "b", samples=500)
    assert service.utcnow is real_clock  # the scripted clock is put back
    for name in PLAY_FILES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    _check_play_fixtures(tmp_path / "a")


def test_committed_play_fixtures_match_the_models():
    _check_play_fixtures(FIXTURES_DIR)


PLAY5_FILES = {
    "play5_session_hero_to_act.json": PlaySessionView,
    "play5_session_hero_folded.json": PlaySessionView,
    "play5_session_side_pot.json": PlaySessionView,
    "play5_hands.json": TypeAdapter(list[PlayHandSummary]),
    "play5_sessions.json": TypeAdapter(list[PlaySessionSummary]),
}


def _check_play5_fixtures(out):
    """Each 5-max file is LF-only, valid for its model, and shows what the UI needs."""
    data = {}
    for name, model in PLAY5_FILES.items():
        raw = (out / name).read_bytes()
        assert raw.endswith(b"\n") and b"\r" not in raw, name
        data[name] = json.loads(raw)
        _validate(model, data[name])
    for name in PLAY5_FILES:
        if name.startswith("play5_session_"):
            v = data[name]
            assert v["table_size"] == 5 and v["profile"] is None and v["bot_stack"] is None
            assert len(v["hand"]["table"]["seats"]) == 5
    to_act = data["play5_session_hero_to_act.json"]["hand"]
    assert to_act["status"] == "in_progress" and to_act["options"]
    assert to_act["table"]["board"] and sum(not s["folded"] for s in to_act["table"]["seats"]) >= 3
    folded = data["play5_session_hero_folded.json"]["hand"]
    assert folded["status"] == "complete" and folded["table"]["seats"][0]["folded"]
    assert folded["outcome"]["winner"] == "villain"
    side = data["play5_session_side_pot.json"]["hand"]["outcome"]
    assert side["ended_by"] == "showdown" and len(side["pots"]) >= 2
    assert len({tuple(p["winners"]) for p in side["pots"]}) >= 2
    assert [p["label"] for p in side["pots"]][:2] == ["main pot", "side pot 1"]
    hands = data["play5_hands.json"]
    assert hands and all(h["table_size"] == 5 and not h["analysed"] for h in hands)
    sessions = data["play5_sessions.json"]
    assert [s["table_size"] for s in sessions] == [2, 5]
    assert sessions[1]["profile_label"] == "5-max"
    return data


def test_write_play5_fixtures_deterministic(tmp_path):
    """One run reproduces the committed files byte for byte (no clock, no random seed)."""
    real_clock = service.utcnow
    write_play5_fixtures(tmp_path)
    assert service.utcnow is real_clock
    for name in PLAY5_FILES:
        assert (tmp_path / name).read_bytes() == (FIXTURES_DIR / name).read_bytes(), name
    _check_play5_fixtures(tmp_path)


def test_committed_play5_fixtures_match_the_models():
    _check_play5_fixtures(FIXTURES_DIR)
