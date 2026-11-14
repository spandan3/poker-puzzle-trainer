import json

import pytest

from poker_trainer.api.dev_fixtures import (
    find_never_continues,
    search,
    write_fixtures,
    write_llm_fixture,
)
from poker_trainer.explain.guardrail import unknown_numbers
from poker_trainer.explain.service import Explainer

ATTEMPTS = ("bet", "fold", "call", "raise_preflop", "fold_preflop", "check_river", "custom")


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
    assert last["is_chosen"] is True and last["is_best"] is False
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
