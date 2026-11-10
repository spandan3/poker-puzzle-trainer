import itertools
import random
from collections import Counter

import pytest
from reference.naive_eval import best_hand_key

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.evaluator import HandClass, evaluate, hand_class


def test_encoding_matches_phevaluator():
    assert evaluate(parse_cards("AhKhQhJhTh")) == 1
    assert hand_class(evaluate(parse_cards("5c4d3h2sAs"))) == HandClass.STRAIGHT
    assert evaluate(parse_cards("7c5d4h3s2c")) == 7462


def test_returns_plain_int():
    assert type(evaluate(parse_cards("AhKhQhJhTh"))) is int


def test_lower_is_stronger():
    quads = evaluate(parse_cards("AcAdAhAsKc"))
    full_house = evaluate(parse_cards("AcAdAhKsKc"))
    assert quads < full_house
    assert hand_class(quads) == HandClass.FOUR_OF_A_KIND
    assert hand_class(full_house) == HandClass.FULL_HOUSE


def test_hand_class_boundaries():
    for rank, cls in [
        (1, HandClass.STRAIGHT_FLUSH), (10, HandClass.STRAIGHT_FLUSH),
        (11, HandClass.FOUR_OF_A_KIND), (166, HandClass.FOUR_OF_A_KIND),
        (167, HandClass.FULL_HOUSE), (322, HandClass.FULL_HOUSE),
        (323, HandClass.FLUSH), (1599, HandClass.FLUSH),
        (1600, HandClass.STRAIGHT), (1609, HandClass.STRAIGHT),
        (1610, HandClass.THREE_OF_A_KIND), (2467, HandClass.THREE_OF_A_KIND),
        (2468, HandClass.TWO_PAIR), (3325, HandClass.TWO_PAIR),
        (3326, HandClass.PAIR), (6185, HandClass.PAIR),
        (6186, HandClass.HIGH_CARD), (7462, HandClass.HIGH_CARD),
    ]:  # fmt: skip
        assert hand_class(rank) == cls


@pytest.mark.slow
def test_five_card_census():
    counts = Counter(hand_class(evaluate(h)) for h in itertools.combinations(range(52), 5))
    assert dict(counts) == {
        HandClass.STRAIGHT_FLUSH: 40,
        HandClass.FOUR_OF_A_KIND: 624,
        HandClass.FULL_HOUSE: 3744,
        HandClass.FLUSH: 5108,
        HandClass.STRAIGHT: 10200,
        HandClass.THREE_OF_A_KIND: 54912,
        HandClass.TWO_PAIR: 123552,
        HandClass.PAIR: 1098240,
        HandClass.HIGH_CARD: 1302540,
    }


def _sign(x):
    return (x > 0) - (x < 0)


def test_matches_naive_on_random_7card():
    rng = random.Random(12345)
    for _ in range(20_000):
        a = rng.sample(range(52), 7)
        b = rng.sample(range(52), 7)
        key_a, key_b = best_hand_key(a), best_hand_key(b)
        expected = _sign((key_a > key_b) - (key_a < key_b))
        assert _sign(evaluate(b) - evaluate(a)) == expected


def test_six_card_evaluate():
    assert evaluate(parse_cards("AhKhQhJhTh2c")) == 1
