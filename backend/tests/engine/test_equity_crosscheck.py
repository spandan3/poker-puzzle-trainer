"""Equity cross-checks: pinned reference values, brute force, pokerkit, error bounds, speed."""

import random
import time

import pytest
from pokerkit import Card, Deck, StandardHighHand, calculate_equities
from pokerkit import parse_range as pk_parse_range
from reference.naive_equity import naive_turn_equity
from reference.naive_eval import best_hand_key

from poker_trainer.engine.cards import card_str, parse_cards
from poker_trainer.engine.combos import COMBOS, combo_index
from poker_trainer.engine.equity import equity_vs_range
from poker_trainer.engine.ranges import empty_range, parse_range


def hand(s: str) -> tuple[int, int]:
    a, b = parse_cards(s)
    return (a, b)


def pokerkit_equity(hero: str, villain: str, board: str = "", samples: int = 20_000) -> float:
    """Hero equity vs a villain range via pokerkit (villain is pokerkit range syntax)."""
    eq = calculate_equities(
        (pk_parse_range(hero), pk_parse_range(villain)),
        Card.parse(board),
        2,
        5,
        Deck.STANDARD,
        (StandardHighHand,),
        sample_count=samples,
    )
    return eq[0]


# --- the oracle itself must be pinned ---------------------------------------------------


def key(s: str) -> tuple:
    return best_hand_key(parse_cards(s))


def test_naive_eval_pinned():
    # Wheel is the lowest straight.
    assert key("5c4d3h2sAs") < key("6c5d4h3s2s")
    # Steel wheel beats an ace-high flush.
    assert key("5s4s3s2sAs") > key("AhKhQhJh9h")
    # Seven cards: best hand is aces and kings with a queen kicker (not the 2c).
    two_pair = key("AhAdKhKdQhQd2c")
    assert two_pair == key("AhAdKhKdQc")
    assert two_pair[:3] == (2, 12, 11)
    assert two_pair > key("AhAdKhKdJc")


# --- reference pre-flop matchups ---------------------------------------------------------

# pokerkit 0.7 (200k samples) / ours (400k samples, seed 1), hero equity:
#   AhAs vs KdKc: 0.8136 / 0.8132   (brief 0.82)
#   AhKh vs QQ:   0.4608 / 0.4603   (brief 0.46)
#   2c2d vs AKo:  0.5251 / 0.5270   (brief 0.52)
#   AhKd vs AsQc: 0.7391 / 0.7398   (brief 0.74)
REFERENCE = [
    # (hero, villain range text, expected equity); pokerkit numbers: pokerkit numbers in the comment above
    ("AhAs", "KdKc", 0.82),
    ("AhKh", "QQ", 0.46),
    ("2c2d", "AKo", 0.52),
    ("AhKd", "AsQc", 0.74),
]


@pytest.mark.parametrize(("hero_s", "villain_s", "expected"), REFERENCE)
def test_reference_preflop_matchups(hero_s, villain_s, expected):
    res = equity_vs_range(
        hand(hero_s), [], parse_range(villain_s), rng=random.Random(2024), samples=100_000
    )
    assert abs(res.equity - expected) <= 0.01, (hero_s, villain_s, res.equity)


@pytest.mark.slow
@pytest.mark.parametrize(("hero_s", "villain_s", "expected"), REFERENCE)
def test_reference_values_confirmed_by_pokerkit(hero_s, villain_s, expected):
    pk = pokerkit_equity(hero_s, villain_s, samples=60_000)
    assert abs(pk - expected) <= 0.01, (hero_s, villain_s, pk)
    ours = equity_vs_range(
        hand(hero_s), [], parse_range(villain_s), rng=random.Random(7), samples=60_000
    )
    assert abs(ours.equity - pk) <= 0.01


# --- brute force ------------------------------------------------------------------------


def _random_turn_spot(rng: random.Random):
    cards = rng.sample(range(52), 6)
    hero, board = (cards[0], cards[1]), cards[2:]
    n_combos = rng.randint(3, 10)
    rng_weights = empty_range()
    for i in rng.sample(range(len(COMBOS)), n_combos):
        rng_weights[i] = rng.choice([1.0, 0.5, 0.25])
    return hero, board, rng_weights


def test_matches_naive_bruteforce():
    rng = random.Random(12345)
    checked = 0
    while checked < 30:
        hero, board, villain = _random_turn_spot(rng)
        dead = set(hero) | set(board)
        if all(a in dead or b in dead for (a, b), w in zip(COMBOS, villain, strict=True) if w > 0):
            continue  # every combo blocked: not a valid spot
        ours = equity_vs_range(hero, board, villain).equity
        ref = naive_turn_equity(hero, board, villain)
        assert ours == pytest.approx(ref, abs=1e-9), (
            [card_str(c) for c in hero],
            [card_str(c) for c in board],
        )
        checked += 1


# --- pokerkit ---------------------------------------------------------------------------


@pytest.mark.slow
def test_matches_pokerkit_random_flops():
    rng = random.Random(99)
    for _ in range(50):
        cards = rng.sample(range(52), 5)
        hero_s = "".join(card_str(c) for c in cards[:2])
        board_s = "".join(card_str(c) for c in cards[2:])
        # Villain: one random combo not blocked by hero or board.
        dead = set(cards)
        a, b = rng.choice([cb for cb in COMBOS if cb[0] not in dead and cb[1] not in dead])
        villain_s = card_str(a) + card_str(b)
        villain = empty_range()
        villain[combo_index(a, b)] = 1.0
        ours = equity_vs_range(
            (cards[0], cards[1]),
            cards[2:],
            villain,
            rng=random.Random(rng.random()),
            samples=20_000,
        ).equity
        pk = pokerkit_equity(hero_s, villain_s, board_s, samples=20_000)
        assert abs(ours - pk) <= 0.01, (hero_s, board_s, villain_s, ours, pk)


# --- honesty of the standard error --------------------------------------------------------


def test_mc_error_bound_honest():
    villain = parse_range("KdKc")
    hero = hand("AhAs")
    results = [
        equity_vs_range(hero, [], villain, rng=random.Random(s), samples=2_000) for s in range(20)
    ]
    mean = sum(r.equity for r in results) / len(results)
    inside = sum(abs(r.equity - mean) <= 2 * r.std_error for r in results)
    assert inside >= 18


# --- benchmark ----------------------------------------------------------------------------


@pytest.mark.slow
def test_benchmark_under_one_second():
    villain = parse_range("22+, A2s+, KTs+, QTs+, JTs, ATo+, KJo+")
    hero = hand("AhKd")
    for board in (parse_cards("Qs7d2c"), []):
        start = time.perf_counter()
        equity_vs_range(hero, board, villain, rng=random.Random(1))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, (len(board), elapsed)
