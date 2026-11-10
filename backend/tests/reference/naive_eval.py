"""Independent slow poker evaluator used only as a test cross-check.

Card id = rank_index * 4 + suit_index; rank_index 0..12 means 2..A.
"""

from collections import Counter
from collections.abc import Sequence
from itertools import combinations


def _five_key(cards: Sequence[int]) -> tuple:
    ranks = sorted((c // 4 for c in cards), reverse=True)
    flush = len({c % 4 for c in cards}) == 1
    distinct = sorted(set(ranks), reverse=True)

    straight_high = None
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_high = distinct[0]
        elif distinct == [12, 3, 2, 1, 0]:  # wheel A-5-4-3-2
            straight_high = 3

    # Groups ordered by (count, rank) descending.
    groups = sorted(Counter(ranks).items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    counts = [n for _, n in groups]
    by_group = tuple(r for r, _ in groups)

    if straight_high is not None and flush:
        return (8, straight_high)
    if counts == [4, 1]:
        return (7, *by_group)
    if counts == [3, 2]:
        return (6, *by_group)
    if flush:
        return (5, *ranks)
    if straight_high is not None:
        return (4, straight_high)
    if counts == [3, 1, 1]:
        return (3, *by_group)
    if counts == [2, 2, 1]:
        return (2, *by_group)
    if counts == [2, 1, 1, 1]:
        return (1, *by_group)
    return (0, *ranks)


def best_hand_key(cards: Sequence[int]) -> tuple:
    """Comparable key of the best 5-card subset; larger is stronger."""
    return max(_five_key(five) for five in combinations(cards, 5))
