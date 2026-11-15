"""Property tests for the play engine: every hand finishes with chips conserved, and the bot's
decisions follow the policy's frequencies."""

import math
import random
from collections import Counter
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import Action, ActionKind, Street, legal_actions
from poker_trainer.play.hand import (
    BOT_SEAT,
    HERO_SEAT,
    HandRecord,
    advance,
    bot_cards,
    hero_act,
    outcome,
    replay,
)
from poker_trainer.play.session import new_record
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import action_distribution

_CUSTOM_PROB = 0.2
_MAX_ACTIONS = 60  # far beyond any real heads-up hand; guards against a loop that never ends

hands = st.tuples(
    st.sampled_from(PROFILE_NAMES),
    st.integers(0, 1),
    st.integers(10, 600),
    st.integers(80, 300),
    st.integers(0, 2**32),
)


def check_hand(name: str, button: int, hero_stack: int, bot_stack: int, seed: int) -> None:
    profile = load_profile(name)
    hero_rng = random.Random(f"hero:{seed}")
    start = (hero_stack, bot_stack)
    r = advance(new_record(button, start, random.Random(seed)), profile)
    while (o := outcome(r)) is None:
        assert len(r.actions) < _MAX_ACTIONS
        s = replay(r)
        lg = legal_actions(s)
        if (
            s.street >= Street.FLOP
            and lg.min_to is not None
            and lg.max_to is not None
            and hero_rng.random() < _CUSTOM_PROB
        ):
            action = custom_action(s, hero_rng.randint(lg.min_to, lg.max_to))
        else:
            action = hero_rng.choice(hero_options(s)).action
        r = hero_act(r, profile, action)
    assert sum(o.stacks) == sum(start)
    assert o.hero_delta == o.stacks[HERO_SEAT] - hero_stack
    assert o.ended_by in ("fold", "showdown")


@settings(max_examples=200, deadline=None)
@given(hands)
def test_every_hand_finishes_with_chips_conserved(hand):
    check_hand(*hand)


@pytest.mark.slow
@settings(max_examples=3000, deadline=None)
@given(hands)
def test_every_hand_finishes_with_chips_conserved_slow(hand):
    check_hand(*hand)


def _flop_lead_record() -> tuple[HandRecord, dict[Action, float]]:
    """Hero opens the button, the bot calls; the bot leads the flop with a mixed strategy."""
    profile = load_profile("tag")
    for seed in range(500):
        r = new_record(HERO_SEAT, (200, 200), random.Random(seed))
        r = replace(
            r,
            actions=(
                Action(HERO_SEAT, ActionKind.RAISE, Street.PREFLOP, 5),
                Action(BOT_SEAT, ActionKind.CALL, Street.PREFLOP, 5),
            ),
        )
        s = replay(r)
        assert s.to_act == BOT_SEAT and s.street == Street.FLOP
        i = combo_index(*bot_cards(r))
        probs = {a: float(arr[i]) for a, arr in action_distribution(profile, s).items()}
        if sum(1 for p in probs.values() if 0.1 <= p <= 0.9) >= 2:
            return r, probs
    raise AssertionError("no mixed flop spot found")


def test_bot_frequencies_match_the_policy():
    profile = load_profile("tag")
    base, probs = _flop_lead_record()
    n = 2000
    seen = Counter(advance(replace(base, bot_seed=k), profile).actions[2] for k in range(n))
    assert set(seen) <= {a for a, p in probs.items() if p > 0}
    for a, p in probs.items():
        bound = 5 * math.sqrt(n * p * (1 - p))
        assert abs(seen[a] - n * p) <= bound, (a, seen[a], n * p)
