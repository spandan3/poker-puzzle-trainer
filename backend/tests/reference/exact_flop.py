"""Exact flop equity by full turn+river enumeration (test reference).

Uses ``poker_trainer.engine.evaluator.evaluate`` (lower is stronger), so it checks the
equity sampling/weighting logic rather than the evaluator itself.
"""

import itertools
from collections.abc import Sequence

from poker_trainer.engine.combos import COMBOS
from poker_trainer.engine.evaluator import evaluate


def exact_flop_reference(
    hero: Sequence[int], board: Sequence[int], villain: Sequence[float]
) -> float:
    """Independent exact flop equity: enumerate turn+river for every unblocked combo,
    excluding Hero, board and that combo's cards; average weighted by the range."""
    hero, board = tuple(hero), tuple(board)
    dead = set(hero) | set(board)
    num = den = 0.0
    for i, (a, b) in enumerate(COMBOS):
        w = float(villain[i])
        if w == 0.0 or a in dead or b in dead:
            continue
        rest = [c for c in range(52) if c not in dead and c != a and c != b]
        share = n = 0
        for t, r in itertools.combinations(rest, 2):
            h = evaluate(hero + board + (t, r))
            v = evaluate((a, b) + board + (t, r))
            share += 2 if h < v else 1 if h == v else 0  # in half-pot units
            n += 2
        num += w * share / n
        den += w
    return num / den
