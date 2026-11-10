"""Equity cross-checks: pinned reference values, brute force, pokerkit, error bounds, speed."""

import math
import random
import time

import pytest
from pokerkit import Card, Deck, StandardHighHand, calculate_equities
from pokerkit import parse_range as pk_parse_range
from reference.exact_flop import exact_flop_reference
from reference.naive_equity import naive_turn_equity
from reference.naive_eval import best_hand_key

from poker_trainer.engine.cards import card_str, parse_cards
from poker_trainer.engine.combos import COMBOS, combo_index
from poker_trainer.engine.equity import equity_vs_range
from poker_trainer.engine.ranges import empty_range, parse_range


def hand(s: str) -> tuple[int, int]:
    a, b = parse_cards(s)
    return (a, b)


def pokerkit_equity(
    hero: str, villain: str, board: str = "", samples: int = 20_000, seed: int = 0
) -> float:
    """Hero equity vs a villain range via pokerkit (villain is pokerkit range syntax).

    pokerkit samples with the module-level ``random``. Seeding it is harmless (global state
    is restored afterwards) but does NOT make pokerkit reproducible across processes or
    platforms: it iterates hash-ordered collections, so results depend on PYTHONHASHSEED.
    Callers must therefore use a statistical tolerance, never a fixed expected value.
    """
    state = random.getstate()
    random.seed(seed)
    try:
        eq = calculate_equities(
            (pk_parse_range(hero), pk_parse_range(villain)),
            Card.parse(board),
            2,
            5,
            Deck.STANDARD,
            (StandardHighHand,),
            sample_count=samples,
        )
    finally:
        random.setstate(state)
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

# Expected values below are the pokerkit-confirmed numbers.
# pokerkit 0.7 (200k samples) / ours (400k samples, seed 1), hero equity:
#   AhAs vs KdKc: 0.8136 / 0.8132   (plan said 0.82)
#   AhKh vs QQ:   0.4608 / 0.4603   (plan said 0.46)
#   2c2d vs AKo:  0.5251 / 0.5270   (plan said 0.52)
#   AhKd vs AsQc: 0.7391 / 0.7398   (plan said 0.74)
REFERENCE = [
    # (hero, villain range text, expected equity)
    ("AhAs", "KdKc", 0.814),
    ("AhKh", "QQ", 0.461),
    ("2c2d", "AKo", 0.525),
    ("AhKd", "AsQc", 0.739),
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
    # Both estimates are seeded. Multi-combo pokerkit ranges (QQ, AKo) are hash-ordered,
    # so pokerkit-vs-ours uses 4x the combined standard error rather than a fixed value.
    n_pk, n_ours = 60_000, 200_000
    pk = pokerkit_equity(hero_s, villain_s, samples=n_pk, seed=11)
    assert abs(pk - expected) <= 0.01, (hero_s, villain_s, pk)
    ours = equity_vs_range(
        hand(hero_s), [], parse_range(villain_s), rng=random.Random(7), samples=n_ours
    )
    se = math.sqrt(pk * (1 - pk) / n_pk + ours.std_error**2)
    assert abs(ours.equity - pk) <= 4 * se, (hero_s, villain_s, ours.equity, pk)


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
    for spot in range(50):
        cards = rng.sample(range(52), 5)
        hero_s = "".join(card_str(c) for c in cards[:2])
        board_s = "".join(card_str(c) for c in cards[2:])
        # Villain: one random combo not blocked by hero or board.
        dead = set(cards)
        a, b = rng.choice([cb for cb in COMBOS if cb[0] not in dead and cb[1] not in dead])
        villain_s = card_str(a) + card_str(b)
        villain = empty_range()
        villain[combo_index(a, b)] = 1.0
        exact = exact_flop_reference((cards[0], cards[1]), cards[2:], villain)
        res = equity_vs_range(
            (cards[0], cards[1]),
            cards[2:],
            villain,
            rng=random.Random(rng.random()),
            samples=100_000,
        )
        # Primary check: our seeded Monte Carlo vs the exact enumeration, at 4 sigma.
        assert abs(res.equity - exact) <= 4 * res.std_error, (
            hero_s,
            board_s,
            villain_s,
            res.equity,
            exact,
        )
        # Independent sanity check: pokerkit (not hash-seed deterministic) vs exact, 4 sigma
        # of its own sampling error.
        n_pk = 20_000
        pk = pokerkit_equity(hero_s, villain_s, board_s, samples=n_pk, seed=spot)
        pk_se = math.sqrt(exact * (1 - exact) / n_pk)
        assert abs(pk - exact) <= 4 * pk_se, (hero_s, board_s, villain_s, pk, exact)


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
