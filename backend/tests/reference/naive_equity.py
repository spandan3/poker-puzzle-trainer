"""Brute-force equity used only as a test cross-check (turn boards, exact).

Independent of ``poker_trainer.engine.evaluator`` and ``equity``: hands are compared
with ``naive_eval.best_hand_key`` (larger = stronger). Combo weights come from the range.
"""

from collections.abc import Sequence

from poker_trainer.engine.combos import COMBOS
from reference.naive_eval import best_hand_key


def naive_turn_equity(hero: Sequence[int], board: Sequence[int], villain: Sequence[float]) -> float:
    """Weighted exact equity (win + tie/2) over every unblocked combo and river card."""
    assert len(board) == 4
    dead = set(hero) | set(board)
    num = den = 0.0
    for i, (a, b) in enumerate(COMBOS):
        w = float(villain[i])
        if w <= 0.0 or a in dead or b in dead:
            continue
        score = n = 0
        for river in range(52):
            if river in dead or river == a or river == b:
                continue
            h = best_hand_key([*hero, *board, river])
            v = best_hand_key([a, b, *board, river])
            n += 1
            score += 1.0 if h > v else (0.5 if h == v else 0.0)
        num += w * score / n
        den += w
    return num / den
