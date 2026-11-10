"""Thin wrapper over phevaluator. Lower rank is stronger (1 = royal flush, 7462 = 7-5-4-3-2)."""

from collections.abc import Sequence
from enum import IntEnum

from phevaluator import evaluate_cards


class HandClass(IntEnum):
    HIGH_CARD = 0
    PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


# (inclusive upper bound on rank, class), checked in order.
_BOUNDARIES = (
    (10, HandClass.STRAIGHT_FLUSH),
    (166, HandClass.FOUR_OF_A_KIND),
    (322, HandClass.FULL_HOUSE),
    (1599, HandClass.FLUSH),
    (1609, HandClass.STRAIGHT),
    (2467, HandClass.THREE_OF_A_KIND),
    (3325, HandClass.TWO_PAIR),
    (6185, HandClass.PAIR),
)


def evaluate(cards: Sequence[int]) -> int:
    """Rank of the best 5-card hand among 5, 6 or 7 card ids; lower is stronger."""
    return int(evaluate_cards(*map(int, cards)))


def hand_class(rank: int) -> HandClass:
    for upper, cls in _BOUNDARIES:
        if rank <= upper:
            return cls
    return HandClass.HIGH_CARD
