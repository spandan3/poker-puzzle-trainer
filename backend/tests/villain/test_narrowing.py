import random

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from poker_trainer.engine.cards import Deck
from poker_trainer.engine.combos import combo_index
from poker_trainer.engine.ranges import full_range
from poker_trainer.game.state import (
    Action,
    ActionKind,
    Street,
    apply,
    deal,
    is_terminal,
    needs_board,
    new_hand,
)
from poker_trainer.villain.narrowing import RangeTracker, describe, narrow
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import (
    HERO_PROFILE,
    OPEN_MULT,
    UnsupportedSpot,
    action_distribution,
    bet_to,
    raise_to,
    sample_action,
)


@given(st.integers(0, 2**32 - 1))
@settings(max_examples=30, deadline=None)
def test_narrow_never_increases(seed):
    g = np.random.default_rng(seed)
    r_arr, p_arr = g.random(1326), g.random(1326)
    a = Action(0, ActionKind.CALL, 0, 2)
    out = narrow(r_arr, {a: p_arr}, a)
    assert np.all(out <= r_arr)
    assert out is not r_arr and out is not p_arr


def test_narrow_zero_raises():
    a = Action(0, ActionKind.CALL, 0, 2)
    with pytest.raises(ValueError, match="zero probability"):
        narrow(full_range(), {a: np.zeros(1326)}, a)


def test_narrow_unknown_action_raises():
    a = Action(0, ActionKind.CALL, 0, 2)
    b = Action(0, ActionKind.FOLD, 0)
    with pytest.raises(ValueError, match="action not available"):
        narrow(full_range(), {a: np.ones(1326)}, b)


def test_tracker_matches_strategy():
    tag = load_profile(HERO_PROFILE)
    s = new_hand(0)
    t = RangeTracker(tag, 0)
    step = t.observe(s, raise_to(s, OPEN_MULT))
    assert np.array_equal(t.current, tag.preflop.open)
    assert t.steps[-1] is step
    assert step.range is t.current


def test_tracker_wrong_seat():
    s = new_hand(0)
    with pytest.raises(ValueError):
        RangeTracker(load_profile("tag"), 1).observe(s, raise_to(s, OPEN_MULT))


def test_tracker_guards_seat_and_street():
    s = new_hand(0)
    t = RangeTracker(load_profile("tag"), 0)
    with pytest.raises(ValueError, match="action seat"):
        t.observe(s, Action(1, ActionKind.RAISE, 0, 5))
    with pytest.raises(ValueError, match="action street"):
        t.observe(s, Action(0, ActionKind.RAISE, 1, 5))


def test_range_history_read_only():
    s = new_hand(0)
    t = RangeTracker(load_profile("tag"), 0)
    with pytest.raises(ValueError):
        t.current[0] = 0.5
    step = t.observe(s, raise_to(s, OPEN_MULT))
    with pytest.raises(ValueError):
        step.range[0] = 0.5
    with pytest.raises(ValueError):
        t.current[0] = 0.5


def test_labels():
    tag = load_profile("tag")
    s = new_hand(0)
    t = RangeTracker(tag, 0)
    a = raise_to(s, OPEN_MULT)
    t.observe(s, a)
    s = apply(s, a)
    s = apply(s, Action(1, ActionKind.CALL, 0, a.to))
    s = deal(s, (0, 5, 10))
    s = apply(s, Action(1, ActionKind.CHECK, 1))
    t.observe(s, bet_to(s, 0.75))
    assert [x.label for x in t.steps] == [
        "Start",
        "Pre-flop: opens to 5",
        "Flop: bets 8 (80% pot)",
    ]  # 8 / pot 10


def test_describe_variants():
    s = new_hand(0)
    assert describe(Action(0, ActionKind.FOLD, 0), s) == "Pre-flop: folds"
    assert describe(Action(0, ActionKind.CALL, 0, 2), s) == "Pre-flop: calls"
    a = raise_to(s, OPEN_MULT)
    assert describe(a, s) == "Pre-flop: opens to 5"
    s2 = apply(s, a)
    assert describe(raise_to(s2, 3.0), s2) == "Pre-flop: 3-bets to 15"
    ai = Action(1, ActionKind.RAISE, 0, s2.stacks[1] + s2.street_bets[1])
    assert describe(ai, s2) == "Pre-flop: goes all-in"


def _flop(stacks=(200, 200)):
    s = new_hand(0, stacks)
    s = apply(s, Action(0, ActionKind.CALL, 0, 2))
    s = apply(s, Action(1, ActionKind.CHECK, 0))
    return deal(s, (0, 5, 10))


def test_describe_postflop_labels_and_street():
    s = _flop()
    s = apply(s, Action(1, ActionKind.CHECK, 1))
    s = apply(s, Action(0, ActionKind.CHECK, 1))
    s = deal(s, (20,))
    assert describe(Action(1, ActionKind.CHECK, 2), s) == "Turn: checks"
    s = apply(s, Action(1, ActionKind.BET, 2, 4))
    assert describe(Action(0, ActionKind.RAISE, 2, 12), s) == "Turn: raises to 12"
    assert describe(Action(0, ActionKind.RAISE, 2, 198), s) == "Turn: goes all-in"
    s = _flop()
    s = apply(s, Action(1, ActionKind.CHECK, 1))
    assert describe(Action(0, ActionKind.BET, 1, 198), s) == "Flop: goes all-in"
    # RangeStep.street follows the street of each observed action
    t = RangeTracker(load_profile("tag"), 1)
    assert t.steps[0].street == Street.PREFLOP
    s = _flop()
    assert t.observe(s, Action(1, ActionKind.CHECK, 1)).street == Street.FLOP


def test_all_in_uses_actor_stack_not_max_to():
    s = new_hand(0, (200, 100))
    s = apply(s, Action(0, ActionKind.RAISE, 0, 5))
    s = apply(s, Action(1, ActionKind.CALL, 0, 5))
    s = deal(s, (0, 5, 10))
    s = apply(s, Action(1, ActionKind.CHECK, 1))
    # effective max bet is 95 (short stack's remaining chips)
    assert describe(Action(0, ActionKind.BET, 1, 95), s) == "Flop: bets 95 (950% pot)"
    s2 = apply(s, Action(0, ActionKind.BET, 1, 30))
    assert describe(Action(1, ActionKind.RAISE, 1, 95), s2) == "Flop: goes all-in"
    short_btn = new_hand(0, (100, 200))
    assert describe(Action(0, ActionKind.RAISE, 0, 100), short_btn) == "Pre-flop: goes all-in"
    big = new_hand(0, (200, 100))
    assert describe(Action(0, ActionKind.RAISE, 0, 100), big) != "Pre-flop: goes all-in"


@given(st.integers(0, 2**32), st.integers(0, 1))
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_revealed_hand_in_range_property(seed, button):
    rng = random.Random(seed)
    profiles = [load_profile(rng.choice(PROFILE_NAMES)) for _ in range(2)]
    deck = Deck(rng)
    holes = [deck.deal(2), deck.deal(2)]
    ci = combo_index(*holes[1])
    t = RangeTracker(profiles[1], 1)
    expected = 1.0
    s = new_hand(button)
    while not is_terminal(s):
        if needs_board(s):
            s = deal(s, deck.deal(3 if s.board == () else 1))
            continue
        seat = s.to_act
        try:
            a = sample_action(profiles[seat], s, holes[seat], rng)
            if seat == 1:
                expected *= float(action_distribution(profiles[1], s)[a][ci])
        except UnsupportedSpot:
            break
        if seat == 1:
            t.observe(s, a)
        s = apply(s, a)
    assert t.current[ci] > 0
    assert t.current[ci] == pytest.approx(expected, rel=1e-9)
