import math
import random

import numpy as np
import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.equity import (
    EquityResult,
    ahead_now,
    equity_by_combo,
    equity_vs_range,
)
from poker_trainer.engine.ranges import parse_range


def hand(s: str) -> tuple[int, int]:
    a, b = parse_cards(s)
    return (a, b)


def test_river_exact_simple():
    # Hero has trip aces; KK (3 unblocked combos, Kd on board) has trip kings -> hero always wins.
    res = equity_vs_range(hand("AhAd"), parse_cards("AsKd7c3h2s"), parse_range("KK"))
    assert isinstance(res, EquityResult)
    assert res.equity == 1.0
    assert res.win == 1.0
    assert res.tie == 0.0
    assert res.exact is True
    assert res.std_error == 0.0


def test_river_split():
    # Board is a royal flush; both players play the board -> every 44 combo splits.
    res = equity_vs_range(hand("2c3d"), parse_cards("AhKhQhJhTh"), parse_range("44"))
    assert res.equity == 0.5
    assert res.tie == 1.0
    assert res.win == 0.0
    assert res.exact is True


def test_turn_exact_outs():
    # Villain holds 3c3s (set of threes with 3d on board). Unseen = 52 - 2 - 4 - 2 = 44.
    # Hero wins with a heart (flush) except 2h (villain fills up) and 3h (villain quads):
    #   Th 9h 8h 7h 6h 5h 4h = 7, plus non-heart tens Tc Td Ts (Broadway) = 3 -> 10/44.
    # No other river helps (pairing A or K still loses to a set); no ties possible.
    res = equity_vs_range(hand("AhKh"), parse_cards("QhJh2c3d"), parse_range("3c3s"))
    assert abs(res.equity - 10 / 44) < 1e-9
    assert abs(res.win - 10 / 44) < 1e-9
    assert res.tie == 0.0
    assert res.exact is True
    assert res.std_error == 0.0


def test_monte_carlo_reports_error():
    res = equity_vs_range(hand("AhAd"), (), parse_range("KK"), rng=random.Random(7))
    assert res.exact is False
    assert 0.0 < res.std_error <= 0.0025
    assert 0.80 < res.equity < 0.84
    assert math.isclose(res.equity, res.win + res.tie / 2)
    assert math.isclose(res.std_error, math.sqrt(res.equity * (1 - res.equity) / 40_000))


def test_deterministic_with_seed():
    hero, board, villain = hand("AhKd"), parse_cards("Ac7s2d"), parse_range("QQ, 77, AJs+")
    a = equity_vs_range(hero, board, villain, rng=random.Random(1), samples=5_000)
    b = equity_vs_range(hero, board, villain, rng=random.Random(1), samples=5_000)
    assert a == b


def test_duplicate_cards_raise():
    with pytest.raises(ValueError):
        equity_vs_range(hand("AhKd"), parse_cards("AhKc2d"), parse_range("QQ"))
    with pytest.raises(ValueError):
        ahead_now(hand("AhKd"), parse_cards("AhKc2d"), parse_range("QQ"))
    with pytest.raises(ValueError):
        equity_by_combo(hand("AhKd"), parse_cards("AhKc2d3s"), parse_range("QQ"))


def test_blocked_range_raises():
    with pytest.raises(ValueError, match="range is empty"):
        equity_vs_range(hand("AhAd"), parse_cards("AsAcKd"), parse_range("AA"))
    with pytest.raises(ValueError, match="range is empty"):
        ahead_now(hand("AhAd"), parse_cards("AsAcKd"), parse_range("AA"))


@pytest.mark.parametrize("board", ["Ac", "Ac7s", "Ac7s2d3d4d5d"])
def test_bad_board_length(board):
    with pytest.raises(ValueError):
        equity_vs_range(hand("KhKd"), parse_cards(board), parse_range("QQ"))
    with pytest.raises(ValueError):
        ahead_now(hand("KhKd"), parse_cards(board), parse_range("QQ"))


def test_ahead_now_flop():
    # Hero top pair beats QQ (6 combos), loses to 77 sets (7s on board -> 3 combos).
    result = ahead_now(hand("AhKd"), parse_cards("Ac7s2d"), parse_range("QQ, 77"))
    assert abs(result - 6 / 9) < 1e-9


def test_ahead_now_preflop():
    # 22 is a pair -> ahead of all 12 AKo, behind all 6 33 combos.
    assert abs(ahead_now(hand("2c2d"), (), parse_range("AKo, 33")) - 12 / 18) < 1e-9
    # Same ranks, suits ignored -> tie.
    assert ahead_now(hand("AhKd"), (), parse_range("AsKc")) == 0.5


def test_ahead_now_river_raises():
    with pytest.raises(ValueError, match="river"):
        ahead_now(hand("AhKd"), parse_cards("Ac7s2d3h9c"), parse_range("QQ"))


def test_equity_weights_respected():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d9h")
    villain = parse_range("KK, QQ:0.5")
    res = equity_vs_range(hero, board, villain)
    per = equity_by_combo(hero, board, villain)
    mask = ~np.isnan(per) & (villain > 0)
    expected = float(np.sum(per[mask] * villain[mask]) / np.sum(villain[mask]))
    assert res.exact is True
    assert abs(res.equity - expected) < 1e-12
    # KK has 3 unblocked combos (Kd held) at weight 1, QQ 6 combos at weight 0.5:
    # the weighting must differ from a plain average over the 9 combos.
    plain = float(np.mean(per[mask]))
    assert abs(res.equity - plain) > 1e-6


def test_equity_by_combo_nan_only_for_blocked():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d9h")
    per = equity_by_combo(hero, board, parse_range("QQ"))
    assert per.shape == (1326,)
    # 52 - 6 = 46 live cards -> C(46, 2) = 1035 unblocked combos, all with a value.
    assert int(np.count_nonzero(~np.isnan(per))) == 1035
    assert np.all((per[~np.isnan(per)] >= 0) & (per[~np.isnan(per)] <= 1))


def test_equity_by_combo_rejects_early_streets():
    with pytest.raises(ValueError):
        equity_by_combo(hand("AhKd"), parse_cards("Ac7s2d"), parse_range("QQ"))
