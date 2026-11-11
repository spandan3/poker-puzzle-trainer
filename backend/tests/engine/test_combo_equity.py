import math
import random

import numpy as np
import pytest
from reference.exact_flop import exact_flop_reference

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import COMBOS, combo_index
from poker_trainer.engine.equity import (
    ComboEquity,
    UnsampledRange,
    combo_equity,
    equity_by_combo,
    equity_vs_range,
)
from poker_trainer.engine.ranges import empty_range, parse_range


def hand(s: str) -> tuple[int, int]:
    a, b = parse_cards(s)
    return (a, b)


def one_hot(*combos: str) -> np.ndarray:
    r = empty_range()
    for s in combos:
        r[combo_index(*parse_cards(s))] = 1.0
    return r


def _pinned_range() -> np.ndarray:
    d = parse_range("22+,A2s+,KTs+,QTs+,JTs,ATo+,KJo+")
    d[::3] *= 0.5
    return d


def test_vs_base_matches_equity_vs_range():
    # Values recorded from equity_vs_range BEFORE the ComboEquity refactor (seed 2026).
    hero, board, d = hand("AhKh"), parse_cards("Qh7c2d"), _pinned_range()
    pinned = (0.49497500000000005, 0.465475, 0.059, 0.0024998737436868687)

    res = combo_equity(hero, board, d, rng=random.Random(2026)).vs(d)
    assert (res.equity, res.win, res.tie, res.std_error) == pinned
    assert res.exact is False

    old = equity_vs_range(hero, board, d, rng=random.Random(2026))
    assert (old.equity, old.win, old.tie, old.std_error) == pinned


def test_vs_base_matches_equity_vs_range_preflop():
    # Recorded pre-refactor, seed 2026, 5000 samples.
    hero, d = hand("AhKh"), _pinned_range()
    res = combo_equity(hero, (), d, rng=random.Random(2026), samples=5000).vs(d)
    assert (res.equity, res.win, res.tie, res.std_error) == (
        0.6175999999999999,
        0.5838,
        0.0676,
        0.006872703107220623,
    )


def test_combo_equity_shape_and_read_only():
    hero, board, d = hand("AhKh"), parse_cards("Qh7c2d"), _pinned_range()
    ce = combo_equity(hero, board, d, rng=random.Random(1), samples=2000)
    assert isinstance(ce, ComboEquity)
    assert ce.hero == hero and ce.board == board and ce.exact is False
    for arr in (ce.base, ce.wins, ce.ties, ce.count):
        assert arr.shape == (len(COMBOS),)
        assert not arr.flags.writeable
        with pytest.raises(ValueError):
            arr[0] = 1.0
    assert ce.count.sum() == 2000
    # Blocked combos are removed from the base.
    assert ce.base[combo_index(*parse_cards("QsQh"))] == 0.0


def test_river_exact_subrange():
    hero, board = hand("KhQh"), parse_cards("Ks7h2c4d9s")
    d = one_hot("AsKd", "JcTc")
    ce = combo_equity(hero, board, d)
    assert ce.exact is True
    assert ce.vs(d).equity == 0.5
    assert ce.vs(one_hot("AsKd")).equity == 0.0
    assert ce.vs(one_hot("JcTc")).equity == 1.0
    assert ce.vs(d).std_error == 0.0


def test_turn_exact_matches_equity_by_combo():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d9h")
    d = parse_range("QQ:0.7, 77, 98s:0.3, T9s, AQo:0.5")
    ce = combo_equity(hero, board, d)
    by_combo = equity_by_combo(hero, board, d)
    live = np.flatnonzero(ce.base > 0)
    assert len(live) > 10
    for i in live:
        w = empty_range()
        w[i] = 0.25  # the scale of a one-combo range does not matter
        assert ce.vs(w).equity == pytest.approx(by_combo[i], abs=1e-12)
    # Base equals the weighted average of the per-combo table.
    b = ce.base
    expected = float(np.nansum(b * by_combo) / b.sum())
    assert ce.vs(d).equity == pytest.approx(expected, abs=1e-12)
    assert ce.vs(d) == equity_vs_range(hero, board, d)


def test_flop_subrange_within_4se():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    d = parse_range("QQ:0.7, 77, 98s:0.3, AJs, KQo:0.5")
    ce = combo_equity(hero, board, d, rng=random.Random(2026))
    live = np.flatnonzero(ce.base > 0)
    keep = np.zeros(len(COMBOS), dtype=bool)
    keep[live[::2]] = True  # about half the range
    # Indicator weights over a non-uniform base: r = 1 / base varies (1/0.3 .. 1).
    w = keep.astype(float)
    assert len(set(ce.base[keep].tolist())) > 1
    res = ce.vs(w)
    expected = exact_flop_reference(hero, board, w)
    assert res.exact is False
    assert abs(res.equity - expected) < 4 * res.std_error


def test_outside_base_raises():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    d = parse_range("QQ")
    ce = combo_equity(hero, board, d, rng=random.Random(3), samples=500)
    with pytest.raises(ValueError, match="weights outside base range"):
        ce.vs(parse_range("QQ, JJ"))
    # Weights on blocked combos are ignored, even outside the base range.
    w = parse_range("QQ")
    w[combo_index(*parse_cards("AcAs"))] = 1.0
    assert ce.vs(w).equity == ce.vs(d).equity


def test_empty_weights_raise():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    ce = combo_equity(hero, board, parse_range("QQ"), rng=random.Random(3), samples=500)
    with pytest.raises(ValueError, match="empty range"):
        ce.vs(empty_range())
    with pytest.raises(ValueError, match="empty range"):
        ce.vs(one_hot("AcAs"))  # only a blocked combo: ignored, leaving nothing


def test_unsampled_subrange_raises():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    d = parse_range("QQ")
    tiny = combo_index(*parse_cards("JcJd"))
    d[tiny] = 1e-9
    ce = combo_equity(hero, board, d, rng=random.Random(5), samples=2000)
    assert ce.count[tiny] == 0
    with pytest.raises(UnsampledRange):
        ce.vs(one_hot("JcJd"))
    assert issubclass(UnsampledRange, ValueError)


def test_n_eff_shrinks_for_subrange():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    d = parse_range("QQ, 77, 98s, AJs, KQo")
    ce = combo_equity(hero, board, d, rng=random.Random(11))
    base = ce.vs(d)
    sub = ce.vs(parse_range("98s"))
    assert sub.std_error > base.std_error
    # Kish n_eff for an indicator sub-range is the number of samples that landed in it.
    n = float(ce.count[parse_range("98s") > 0].sum())
    p = sub.equity
    assert sub.std_error == pytest.approx(math.sqrt(p * (1 - p) / n), rel=1e-12)


def test_invalid_weights_checked_on_live_combos_only():
    hero, board = hand("AhKd"), parse_cards("Ac7s2d")
    d = parse_range("QQ")
    ce = combo_equity(hero, board, d, rng=random.Random(3), samples=500)
    blocked = combo_index(*parse_cards("AcAs"))
    for bad in (-1.0, np.nan, np.inf):
        w = d.copy()
        w[blocked] = bad
        assert ce.vs(w).equity == ce.vs(d).equity
        w = d.copy()
        w[combo_index(*parse_cards("JcJd"))] = bad
        with pytest.raises(ValueError, match="finite and non-negative"):
            ce.vs(w)
