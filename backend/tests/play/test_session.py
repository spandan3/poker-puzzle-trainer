"""Session stack rules, applied at the start of each hand, and dealing a new hand record."""

import random

import pytest

from poker_trainer.play.session import (
    BOT_MAX,
    BOT_MIN,
    HERO_MIN,
    START,
    must_rebuy,
    new_record,
    next_stacks,
)


def test_constants():
    assert (START, BOT_MIN, BOT_MAX, HERO_MIN) == (200, 80, 300, 10)


@pytest.mark.parametrize(
    ("hero", "bot", "top_up", "want"),
    [
        (200, 200, False, (200, 200, 0)),
        (200, 200, True, (200, 200, 0)),
        (200, 79, False, (200, 200, 0)),
        (200, 80, False, (200, 80, 0)),
        (200, 301, False, (200, 200, 0)),
        (200, 300, False, (200, 300, 0)),
        (9, 200, False, (200, 200, 191)),
        (9, 200, True, (200, 200, 191)),
        (150, 200, True, (200, 200, 50)),
        (150, 200, False, (150, 200, 0)),
        (450, 200, True, (450, 200, 0)),
    ],
)
def test_next_stacks(hero, bot, top_up, want):
    assert next_stacks(hero, bot, top_up=top_up) == want


def test_must_rebuy():
    assert must_rebuy(9)
    assert must_rebuy(0)
    assert not must_rebuy(10)


def test_new_record_is_a_fresh_seeded_deal():
    r = new_record(1, (150, 250), random.Random(3))
    assert (r.button, r.start_stacks, r.actions, r.abandoned) == (1, (150, 250), (), False)
    assert sorted(r.deck) == list(range(52))
    assert 0 <= r.bot_seed < 2**62
    assert new_record(1, (150, 250), random.Random(3)) == r
    assert new_record(1, (150, 250), random.Random(4)) != r
