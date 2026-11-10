import time

import numpy as np
import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import Action, ActionKind, Street, apply, deal, new_hand
from poker_trainer.villain.features import (
    HandCategory,
    board_texture,
    categorize,
    load_thresholds,
    range_features,
    street_spr,
)


def idx(s: str) -> int:
    a, b = parse_cards(s)
    return combo_index(a, b)


def probe(board: str, hand: str):
    f = range_features(parse_cards(board))
    i = idx(hand)
    cat = int(categorize(f, load_thresholds())[i])
    return f.strength[i], f.beaten_by[i], int(f.outs[i]), cat


def test_blocked_combos_marked():
    f = range_features(parse_cards("AhKd7c"))
    i = idx("AhAs")
    assert np.isnan(f.strength[i]) and np.isnan(f.beaten_by[i])
    assert f.outs[i] == -1
    assert categorize(f, load_thresholds())[i] == -1


def test_flush_draw_overs_is_strong_draw():
    _, _, outs, cat = probe("Kh7h2c", "AhQh")
    assert outs == 9
    assert cat == HandCategory.STRONG_DRAW


# Brief used 7h6h, but 7h is on the board (blocked); 6h2h = bottom pair + flush draw.
def test_pair_plus_flush_draw_is_strong_draw():
    assert probe("Kh7h2c", "6h2h")[3] == HandCategory.STRONG_DRAW


def test_gutshot_weak_draw():
    _, _, outs, cat = probe("Kh9d2c", "QsJc")
    assert outs == 4
    assert cat == HandCategory.WEAK_DRAW


def test_top_set_is_nuts():
    assert probe("Kd7s2c", "KhKc")[3] == HandCategory.NUTS


def test_overpair_not_nuts():
    assert probe("Kd7s2c", "AsAc")[3] == HandCategory.STRONG


def test_tptk_not_nuts():
    assert probe("Kd7s2c", "KsQc")[3] != HandCategory.NUTS


def test_board_straight_not_out():
    assert probe("9c8d7h6s", "2c2d")[2] == 0


def test_river_has_no_outs():
    f = range_features(parse_cards("Kh9d2c4s5h"))
    assert (f.outs[~np.isnan(f.strength)] == 0).all()


def test_strength_bounds():
    f = range_features(parse_cards("Kh9d2c"))
    live = ~np.isnan(f.strength)
    s = f.strength[live]
    assert s.min() >= 0 and s.max() <= 1
    assert abs(s.mean() - 0.5) < 0.01


def test_beaten_by_plus_strength_le_one():
    f = range_features(parse_cards("Kh9d2c4s"))
    live = ~np.isnan(f.strength)
    assert (f.strength[live] + f.beaten_by[live] <= 1 + 1e-9).all()


def test_texture():
    t = board_texture(parse_cards("Kh7h2c"))
    assert t.two_tone and t.wet
    t = board_texture(parse_cards("Kd7s2c"))
    assert not t.wet and not t.paired
    assert board_texture(parse_cards("9c8d7h")).connected
    assert board_texture(parse_cards("KhKd2c")).paired
    assert board_texture(parse_cards("Ah5h3h")).monotone
    assert board_texture(parse_cards("Ah5c4d3s")).connected


def test_street_spr():
    s = new_hand(0)
    s = apply(s, Action(0, ActionKind.RAISE, Street.PREFLOP, 5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP))
    s = deal(s, parse_cards("Kh7h2c"))
    assert street_spr(s) == 195 / 10
    with pytest.raises(ValueError):
        street_spr(new_hand(0))


def test_bad_board_length():
    with pytest.raises(ValueError):
        range_features(parse_cards("Kh7h"))


def test_features_fast():
    range_features.cache_clear()
    t0 = time.perf_counter()
    range_features(parse_cards("Qs8d3h"))
    assert time.perf_counter() - t0 < 0.5
