import dataclasses
import json

import numpy as np
import pytest

from poker_trainer.engine.combos import combo_index
from poker_trainer.engine.equity import ComboEquity
from poker_trainer.engine.ranges import full_range
from poker_trainer.game.state import Action, ActionKind, Street, apply, deal, new_hand
from poker_trainer.puzzle.model import (
    SIMPLIFICATIONS,
    Branch,
    CategoryRow,
    Option,
    OptionEV,
    Puzzle,
    RangeView,
    Solution,
    Spot,
    load_config,
    puzzle_from_dict,
    puzzle_to_dict,
    realisation_text,
    visible_range,
)


def _arr(seed):
    a = np.random.default_rng(seed).random(1326)
    a.setflags(write=False)
    return a


def _puzzle():
    s = new_hand(0)
    s = apply(s, Action(0, ActionKind.RAISE, Street.PREFLOP, 5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    s = deal(s, (4, 9, 20))
    steps = (
        RangeView("Opens", Street.PREFLOP, _arr(1)),
        RangeView("Calls", Street.PREFLOP, _arr(2)),
    )
    spot = Spot(7, 3, s, 1, (0, 1), (30, 31), (4, 9, 20, 40, 45), "tag", 1, 1, 3, steps)
    ce = ComboEquity((0, 1), (4, 9, 20), _arr(3), _arr(4), _arr(5), _arr(6), False)
    act = Action(1, ActionKind.BET, Street.FLOP, 4)
    ev = OptionEV(
        Option("bet 33%", act),
        1.5,
        0.4,
        0.55,
        None,
        0.01,
        0.3,
        4,
        _arr(8),
        (Branch("Villain folds", 0.4, None, 10.0),),
        ("realisation",),
    )
    check = Option("check", Action(1, ActionKind.CHECK, Street.FLOP))
    ev0 = OptionEV(check, 0.0, None, None, None, None, None, 0, None, (), ())
    sol = Solution(
        0.5,
        0.002,
        False,
        0.6,
        0.25,
        (ev0, ev),
        1,
        ce,
        (CategoryRow("nuts", 0.1, 0.9, 0.8, 0.85, 0.1, 0.05),),
        ("realisation",),
    )
    return Puzzle(spot, sol)


def _same(a, b):
    if isinstance(a, np.ndarray):
        assert isinstance(b, np.ndarray) and np.array_equal(a, b) and not b.flags.writeable
    elif hasattr(a, "__dataclass_fields__"):
        assert type(a) is type(b)
        for f in a.__dataclass_fields__:
            _same(getattr(a, f), getattr(b, f))
    elif isinstance(a, tuple):
        assert type(a) is type(b) and len(a) == len(b)
        for x, y in zip(a, b, strict=True):
            _same(x, y)
    else:
        assert a == b and type(a) is type(b)


def test_round_trip():
    p = _puzzle()
    d = puzzle_to_dict(p)
    assert d["format"] == 1
    q = puzzle_from_dict(json.loads(json.dumps(d)))
    _same(p, q)
    assert q.spot.range is q.spot.steps[-1].range
    assert d["spot"]["config_version"] == 3
    row = d["solution"]["category_breakdown"][0]
    assert (row["win"], row["tie"], row["lose"]) == (0.85, 0.1, 0.05)


def test_unknown_format_rejected():
    d = puzzle_to_dict(_puzzle())
    d["format"] = 2
    with pytest.raises(ValueError):
        puzzle_from_dict(d)


def test_visible_range_removes_hero_and_board():
    r = visible_range(full_range(), (0, 1), (4, 9, 20))
    assert r[combo_index(0, 1)] == 0.0 and r[combo_index(4, 30)] == 0.0
    assert r[combo_index(30, 31)] == 1.0
    assert not r.flags.writeable


def test_config_and_simplifications():
    c = load_config()
    assert c.samples == 40000 and c.verdict.best_bb == 0.25 and c.max_attempts == 200
    assert c.street_weights["flop"] == 0.30
    assert c.version == 4 and c.intent.semi_bluff_equity == 0.30
    assert c.verdict.min_pot == 10
    assert dict(c.realisation) == {
        Street.PREFLOP: (1.0, 0.80),
        Street.FLOP: (1.0, 0.88),
        Street.TURN: (1.0, 0.94),
    }
    assert set(SIMPLIFICATIONS) == {
        "realisation",
        "realisation_position",
        "reraise_reply",
        "preflop_size",
        "check_reply",
    }
    # Pre-M9 puzzles store "realisation": its text stays what they were graded with.
    assert SIMPLIFICATIONS["realisation"] == (
        "Before the river, Hero is assumed to realise full equity."
    )
    assert SIMPLIFICATIONS["realisation_position"] == (
        "Before the river, Hero is assumed to realise a share of equity set by position: "
        "in position 100%; out of position 80% pre-flop, 88% on the flop, 94% on the turn. "
        "All-in pots realise 100%."
    )


def test_realisation_text_per_street_when_ip_differs():
    r = {Street.PREFLOP: (0.95, 0.8), Street.FLOP: (1.0, 0.8), Street.TURN: (1.0, 0.8)}
    assert realisation_text(r) == (
        "Before the river, Hero is assumed to realise a share of equity set by position: "
        "in position 95% pre-flop, 100% on the flop, 100% on the turn; out of position 80%. "
        "All-in pots realise 100%."
    )


def test_solution_roundtrip_defaults_realisation():
    """A stored pre-M9 puzzle (no "realisation" keys) reads as graded: r = 1.0 everywhere."""
    p = _puzzle()
    d = json.loads(json.dumps(puzzle_to_dict(p)))
    for o in d["solution"]["options"]:
        assert o["realisation"] == 1.0
        del o["realisation"]
        for b in o["branches"]:
            assert b["realisation"] == 1.0
            del b["realisation"]
    q = puzzle_from_dict(d)
    for o in q.solution.options:
        assert o.realisation == 1.0 and type(o.realisation) is float
        assert all(b.realisation == 1.0 for b in o.branches)
    assert q.solution.options[1].simplifications == ("realisation",)
    assert q.solution.simplifications == ("realisation",)


def test_realisation_round_trips():
    p = _puzzle()
    ev = dataclasses.replace(
        p.solution.options[1],
        branches=(
            Branch("Villain folds", 0.4, None, 10.0),
            Branch("Villain calls", 0.6, 0.5, 3.2, 0.88),
        ),
        realisation=0.94,
    )
    sol = dataclasses.replace(p.solution, options=(p.solution.options[0], ev))
    q = puzzle_from_dict(json.loads(json.dumps(puzzle_to_dict(Puzzle(p.spot, sol)))))
    o = q.solution.options[1]
    assert o.realisation == 0.94
    assert [b.realisation for b in o.branches] == [1.0, 0.88]


def test_numpy_scalars_serialise():
    p = _puzzle()
    ev = p.solution.options[1]
    ev2 = dataclasses.replace(
        ev,
        ev_chips=np.float64(1.5),
        fold_freq=np.float64(0.4),
        put=np.int64(4),
        branches=(Branch("Villain folds", np.float64(0.4), None, np.float64(10.0)),),
    )
    sol = dataclasses.replace(
        p.solution,
        options=(p.solution.options[0], ev2),
        best=np.int64(1),
        equity=np.float64(0.5),
        equity_exact=np.bool_(False),
        category_breakdown=(
            CategoryRow(
                "nuts",
                np.float64(0.1),
                np.float64(0.9),
                np.float64(0.8),
                np.float64(0.85),
                np.float64(0.1),
                np.float64(0.05),
            ),
        ),
    )
    q = puzzle_from_dict(json.loads(json.dumps(puzzle_to_dict(Puzzle(p.spot, sol)))))
    assert q.solution.best == 1 and type(q.solution.best) is int
    assert q.solution.options[1].put == 4 and type(q.solution.options[1].put) is int
    assert q.solution.equity_exact is False
    assert q.solution.options[1].ev_chips == 1.5
