import json

import pytest

from poker_trainer.api.dev_fixtures import find_never_continues, search, write_fixtures

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
    custom = json.loads((tmp_path / "attempt_custom.json").read_text(encoding="utf-8"))
    last = custom["options"][-1]
    assert last["is_chosen"] is True and last["is_best"] is False
    raise_pf = json.loads((tmp_path / "attempt_raise_preflop.json").read_text(encoding="utf-8"))
    assert raise_pf["answer"]["action"]["kind"] == "raise"
    assert raise_pf["grade"]["intent"] == "value"
