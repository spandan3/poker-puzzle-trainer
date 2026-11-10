import random

import numpy as np

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.equity import ahead_now, equity_vs_range
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.engine.ranges import parse_range


def _np(cards):
    return np.array(list(cards), dtype=np.int64)


def test_evaluate_accepts_numpy_ids():
    cards = parse_cards("AhKhQhJhThAs2c")
    assert evaluate(_np(cards)) == evaluate(cards) == 1
    assert isinstance(evaluate(_np(cards)), int)


def test_equity_turn_exact_numpy_matches_int():
    hero, board = parse_cards("AhKd"), parse_cards("7c8d2sJh")
    rng_ = parse_range("22+,AJs+,KQs")
    assert equity_vs_range(_np(hero), _np(board), rng_) == equity_vs_range(tuple(hero), board, rng_)


def test_equity_flop_mc_numpy_matches_int():
    hero, board = parse_cards("AhKd"), parse_cards("7c8d2s")
    rng_ = parse_range("22+,AJs+,KQs")
    a = equity_vs_range(_np(hero), _np(board), rng_, rng=random.Random(3), samples=2000)
    b = equity_vs_range(tuple(hero), board, rng_, rng=random.Random(3), samples=2000)
    assert a == b


def test_ahead_now_numpy_matches_int():
    hero, board = parse_cards("AhKd"), parse_cards("7c8d2s")
    rng_ = parse_range("22+,AJs+,KQs")
    assert ahead_now(_np(hero), _np(board), rng_) == ahead_now(tuple(hero), board, rng_)
    assert ahead_now(_np(hero), _np([]), rng_) == ahead_now(tuple(hero), [], rng_)
