"""Property tests over generated puzzles: the spec's consistency rules."""

import json

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import apply, total_pot
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.puzzle.grade import Answer, grade
from poker_trainer.puzzle.model import best_margin, load_config, puzzle_from_dict, puzzle_to_dict
from poker_trainer.puzzle.solve import evaluate_action, villain_respond
from poker_trainer.villain.profiles import load_profile

_TOL = 1e-12


def check_puzzle(seed: int) -> None:
    p = generate_puzzle(seed)
    spot, sol = p.spot, p.solution
    s = spot.state

    # Every puzzle has options to choose from and at least the Start range step.
    assert len(sol.options) > 0, seed
    assert len(spot.steps) >= 1, seed

    # Revealed hand is in the displayed range.
    assert spot.range[combo_index(*spot.villain_hole)] > 0, seed

    # Displayed equity is the graded equity.
    assert sol.equity == sol.combo_equity.vs(spot.range).equity, seed

    # Narrowing never increases a weight.
    for a, b in zip(spot.steps, spot.steps[1:], strict=False):
        assert np.all(np.asarray(b.range) <= np.asarray(a.range) + _TOL), seed

    # Chips are conserved, and every option applies cleanly.
    def conserved(st_) -> bool:
        return sum(st_.stacks) + st_.pot + sum(st_.street_bets) == st_.total_chips

    assert conserved(s), seed
    for o in sol.options:
        assert conserved(apply(s, o.option.action)), seed

    # Re-evaluating each stored option reproduces its EV.
    respond = villain_respond(load_profile(spot.profile))
    samples = load_config().samples
    for o in sol.options:
        again = evaluate_action(
            s,
            spot.hero,
            spot.range,
            sol.combo_equity,
            o.option.action,
            respond,
            label=o.option.label,
            samples=samples,
        )
        assert abs(again.ev_chips - o.ev_chips) <= _TOL, (seed, o.option.label)

    # Grade says "best" exactly for options within the best margin.
    v = load_config().verdict
    pot = total_pot(s)
    best = sol.options[sol.best]
    for o in sol.options:
        loss = max(0.0, best.ev_chips - o.ev_chips)
        within = loss <= best_margin(pot, v) + 1e-9
        g = grade(p, Answer(o.option.action, equity_guess=sol.equity))
        assert (g.verdict == "best") == within, (seed, o.option.label)

    # JSON round-trip.
    d = json.loads(json.dumps(puzzle_to_dict(p)))
    assert puzzle_to_dict(puzzle_from_dict(d)) == d, seed


@settings(max_examples=15, deadline=None)
@given(seed=st.integers(0, 10**6))
def test_puzzle_properties(seed):
    check_puzzle(seed)


@pytest.mark.slow
@settings(max_examples=150, deadline=None)
@given(seed=st.integers(0, 10**6))
def test_puzzle_properties_slow(seed):
    check_puzzle(seed)
