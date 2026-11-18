"""The pot-odds tie cases shared with the frontend (``tests/data/tie_cases.json``).

The Why text (``template._pot_odds``) and the Maths tab (``frontend/src/lib/maths.ts``) must agree on
when equity and pot odds tie (the same formatted text) and which way the decision goes (the
unrounded comparison). ``frontend/src/lib/tieCases.test.ts`` reads the same file.
"""

import copy
import json
from pathlib import Path

import pytest
from explain_cases import puzzle, result

from poker_trainer.api import views
from poker_trainer.explain.facts import build_facts
from poker_trainer.explain.template import _pot_odds

CASES = json.loads((Path(__file__).parent.parent / "data" / "tie_cases.json").read_text("utf-8"))[
    "cases"
]

# attempt_call's puzzle: a flop call against a raise, so the result has a call option
_P = puzzle(17, "flop")
_BASE = result(_P, option=1)


def _facts(case):
    res = copy.deepcopy(_BASE)
    res["grade"]["equity"] = case["equity"]
    res["grade"]["pot_odds"] = case["pot_odds"]
    for o in res["options"]:
        if o["kind"] == "call":
            o["realisation"] = case["realisation"]
    return build_facts(res, _P, views.action_log(_P.spot))


def test_the_file_covers_every_kind_of_case():
    assert len(CASES) >= 8
    for realised in (False, True):
        group = [c for c in CASES if (c["realisation"] != 1) == realised]
        kinds = {(c["expected_tie"], c["expected_beats"]) for c in group}
        assert kinds == {(True, True), (True, False), (False, True), (False, False)}


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_tie_and_direction_match_the_shared_cases(case):
    f = _facts(case)
    assert f.call_amount is not None and f.pot_odds is not None
    # the compared texts: realised equity out of position, else the equity
    shown = f.realised_equity if f.realisation is not None else f.equity
    assert (f.realisation is not None) == (case["realisation"] != 1)
    assert (shown == f.pot_odds) == case["expected_tie"]
    assert f.equity_beats_pot_odds is case["expected_beats"]

    text = _pot_odds(f)
    outcome = "calling beats folding" if case["expected_beats"] else "folding beats calling"
    assert f"so {outcome}." in text
    if case["expected_tie"]:
        assert ("exactly what it needs" if case["expected_beats"] else "just short") in text
        assert "above" not in text and "below" not in text
    else:
        assert ("above" if case["expected_beats"] else "below") in text
        assert "exactly" not in text and "just short" not in text
