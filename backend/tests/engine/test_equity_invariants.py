import random

import pytest

from poker_trainer.engine.combos import combo_index
from poker_trainer.engine.equity import equity_vs_range
from poker_trainer.engine.ranges import empty_range


def _single(combo: tuple[int, int]):
    r = empty_range()
    r[combo_index(*combo)] = 1.0
    return r


def _spots(n: int = 30):
    rng = random.Random(20261110)
    out = []
    for k in range(n):
        board_len = 4 if k % 2 == 0 else 5  # alternate turn / river
        cards = rng.sample(range(52), 4 + board_len)
        out.append((tuple(cards[:2]), tuple(cards[2:4]), tuple(cards[4:])))
    return out


@pytest.mark.parametrize("hero,villain,board", _spots())
def test_symmetry_and_sum_invariants(hero, villain, board):
    a = equity_vs_range(hero, board, _single(villain))
    b = equity_vs_range(villain, board, _single(hero))
    assert a.equity + b.equity == pytest.approx(1.0, abs=1e-12)
    for res in (a, b):
        assert 0.0 <= res.win <= 1.0
        assert 0.0 <= res.tie <= 1.0
        assert 0.0 <= res.equity <= 1.0
        assert res.win + res.tie <= 1.0 + 1e-12
        assert res.equity == pytest.approx(res.win + res.tie / 2, abs=1e-12)
