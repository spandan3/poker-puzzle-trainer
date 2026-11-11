import pytest

from poker_trainer.game.state import (
    Action,
    ActionKind,
    Street,
    apply,
    deal,
    legal_actions,
    new_hand,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.strategy import allin, raise_to


def labels(s):
    return [o.label for o in hero_options(s)]


def by_label(s):
    return {o.label: o.action for o in hero_options(s)}


def test_btn_first_in_options():
    s = new_hand(0)
    assert labels(s) == ["fold", "raise 2.5x", "raise 3x", "all-in"]
    o = by_label(s)
    assert (o["raise 2.5x"].to, o["raise 3x"].to, o["all-in"].to) == (5, 6, 200)


def test_bb_vs_open_options():
    s0 = new_hand(0)
    s = apply(s0, raise_to(s0, 2.5))
    assert labels(s) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    o = by_label(s)
    assert (o["raise 2.5x"].to, o["raise 3x"].to) == (12, 15)


def test_btn_vs_3bet_options():
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, raise_to(s, 3.0))
    assert labels(s) == ["fold", "call", "all-in"]


def test_facing_jam_options():
    s = new_hand(0)
    s = apply(s, allin(s))
    assert labels(s) == ["fold", "call"]
    assert by_label(s)["call"].to == 200


def _flop(stacks=(200, 200)):
    s = new_hand(0, stacks)
    s = apply(s, Action(0, ActionKind.CALL, Street.PREFLOP, 2))
    s = apply(s, Action(1, ActionKind.CHECK, Street.PREFLOP))
    return deal(s, (4, 9, 20))


def test_postflop_options_merge_allin():
    s = _flop((6, 6))
    opts = hero_options(s)
    assert [o.label for o in opts].count("all-in") == 1
    assert opts[0].label == "check"
    assert len({o.action for o in opts}) == len(opts)
    for o in opts:
        apply(s, o.action)
    assert opts[-1].action.to == legal_actions(s).max_to


def test_postflop_unopened_and_facing_labels():
    s = _flop()
    # pot 4: 33% and 50% both round to the minimum bet of 2, so "bet 50%" merges away
    assert labels(s) == ["check", "bet 33%", "bet 75%", "bet 100%", "all-in"]
    s2 = apply(s, by_label(s)["bet 75%"])
    assert labels(s2) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    for o in hero_options(s2):
        apply(s2, o.action)


def test_custom_action_rejected_preflop():
    with pytest.raises(ValueError):
        custom_action(new_hand(0), 5)


def test_custom_action_postflop():
    s = _flop((6, 6))
    a = custom_action(s, 3)
    assert a == Action(1, ActionKind.BET, Street.FLOP, 3)
    apply(s, a)
    for bad in (1, 5):
        with pytest.raises(ValueError):
            custom_action(s, bad)
