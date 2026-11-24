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
from poker_trainer.villain.strategy import UnsupportedSpot, allin, bet_to, raise_to


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


def test_preflop_unsupported_raises_unsupported_spot():
    s = new_hand(0)
    s = apply(s, Action(0, ActionKind.CALL, Street.PREFLOP, 2))  # limp
    with pytest.raises(UnsupportedSpot):
        hero_options(s)
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, raise_to(s, 3.0))
    s = apply(s, Action(0, ActionKind.RAISE, Street.PREFLOP, 40))  # non-all-in 4-bet
    with pytest.raises(UnsupportedSpot):
        hero_options(s)


def test_preflop_short_stack_raise_becomes_allin():
    s = new_hand(0, (10, 10))
    assert raise_to(s, 3.0).to == legal_actions(s).max_to  # 6 >= 0.6 * 10
    assert raise_to(s, 2.5).to == 5
    assert labels(s) == ["fold", "raise 2.5x", "all-in"]
    assert by_label(s)["all-in"].to == 10
    for o in hero_options(s):
        apply(s, o.action)


def test_postflop_options_merge_allin():
    s = _flop((6, 6))
    mx = legal_actions(s).max_to
    assert bet_to(s, 0.75).to == mx and bet_to(s, 1.0).to == mx  # both past 0.6 * max_to
    assert bet_to(s, 0.75).to >= 0.6 * mx
    opts = hero_options(s)
    assert [o.label for o in opts] == ["check", "bet 33%", "all-in"]
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


# ---------------------------------------------------------------------------
# 5 seats (pre-flop): button 0 -> SB 1, BB 2, UTG 3, CO 4
# ---------------------------------------------------------------------------


def _fold5(s):
    return apply(s, Action(s.to_act, ActionKind.FOLD, Street.PREFLOP))


def _call5(s):
    return apply(s, by_label(s)["call"])


def test_5max_unopened_options_every_position():
    s = new_hand(0, (200,) * 5)
    for seat in (3, 4, 0, 1):  # UTG, CO, BTN, SB
        assert s.to_act == seat
        assert labels(s) == ["fold", "raise 2.5x", "raise 3x", "all-in"]
        o = by_label(s)
        assert (o["raise 2.5x"].to, o["raise 3x"].to, o["all-in"].to) == (5, 6, 200)
        for opt in hero_options(s):
            apply(s, opt.action)
        s = _fold5(s)
    assert s.folded is not None  # a walk: the BB never gets an option


def test_5max_short_open_merges_into_allin():
    s = new_hand(0, (200, 200, 200, 8, 200))  # UTG has 8 chips
    assert labels(s) == ["fold", "all-in"]
    assert by_label(s)["all-in"].to == 8


def test_5max_vs_open_options_with_callers():
    s = new_hand(0, (200,) * 5)
    s = apply(s, raise_to(s, 2.5))  # UTG opens to 5
    assert labels(s) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    o = by_label(s)
    assert (o["call"].to, o["raise 2.5x"].to, o["raise 3x"].to) == (5, 12, 15)
    s = _call5(s)  # CO calls
    s = _call5(s)  # BTN calls
    s = _fold5(s)  # SB folds
    assert s.to_act == 2  # BB, facing an open and two callers
    assert labels(s) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    assert by_label(s)["call"].to == 5


def test_5max_vs_threebet_options():
    s = new_hand(0, (200,) * 5)
    s = apply(s, raise_to(s, 2.5))  # UTG
    s = _call5(s)  # CO
    s = apply(s, raise_to(s, 3.0))  # BTN 3-bets
    for _ in range(4):  # SB, BB (cold), UTG (opener), CO (caller)
        assert labels(s) == ["fold", "call", "all-in"]
        assert by_label(s)["all-in"].to == 200
        s = _fold5(s)


def test_5max_vs_jam_options():
    s = new_hand(0, (200,) * 5)
    s = apply(s, allin(s))  # UTG jams
    while s.to_act is not None:
        assert labels(s) == ["fold", "call"]
        s = _fold5(s)


def test_5max_jam_with_deeper_player_behind():
    s = new_hand(0, (300, 300, 300, 100, 300))
    s = apply(s, allin(s))  # UTG all-in for 100
    assert legal_actions(s).aggressive == ActionKind.RAISE  # CO could technically raise
    assert labels(s) == ["fold", "call"]
    s = _call5(s)
    assert labels(s) == ["fold", "call"]  # BTN, still facing the jam


def test_5max_vs_capped_fourbet_jam():
    # UTG (600) jams over a 3-bet; capped at the deepest other stack, it keeps chips behind.
    s = new_hand(0, (300, 300, 300, 600, 300))
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, raise_to(s, 3.0))
    for _ in range(3):
        s = _fold5(s)
    assert labels(s) == ["fold", "call", "all-in"]
    s = apply(s, by_label(s)["all-in"])
    assert s.stacks[3] == 300
    assert labels(s) == ["fold", "call"]


@pytest.mark.parametrize("n", [3, 4, 6])
def test_other_table_sizes_preflop_unsupported(n):
    with pytest.raises(UnsupportedSpot):
        hero_options(new_hand(0, (200,) * n))


def test_5max_limp_unsupported():
    s = new_hand(0, (200,) * 5)
    s = apply(s, Action(3, ActionKind.CALL, Street.PREFLOP, 2))
    with pytest.raises(UnsupportedSpot):
        hero_options(s)
