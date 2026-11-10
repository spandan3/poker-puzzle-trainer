"""Card encoding: id = rank_index * 4 + suit_index (matches phevaluator)."""

import random
import re
from collections.abc import Iterable

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def parse_card(s: str) -> int:
    if len(s) != 2:
        raise ValueError(f"invalid card: {s!r}")
    r = RANKS.find(s[0].upper())
    u = SUITS.find(s[1].lower())
    if r < 0 or u < 0:
        raise ValueError(f"invalid card: {s!r}")
    return r * 4 + u


def card_str(c: int) -> str:
    if not 0 <= c < 52:
        raise ValueError(f"invalid card id: {c}")
    return RANKS[c // 4] + SUITS[c % 4]


def rank_of(c: int) -> int:
    return c // 4


def suit_of(c: int) -> int:
    return c % 4


def ensure_distinct(*groups: Iterable[int]) -> None:
    seen: set[int] = set()
    for group in groups:
        for c in group:
            if c in seen:
                raise ValueError(f"duplicate card: {card_str(c)}")
            seen.add(c)


def parse_cards(s: str) -> tuple[int, ...]:
    compact = re.sub(r"[\s,]+", "", s)
    if len(compact) % 2:
        raise ValueError(f"invalid cards: {s!r}")
    cards = tuple(parse_card(compact[i : i + 2]) for i in range(0, len(compact), 2))
    ensure_distinct(cards)
    return cards


class Deck:
    def __init__(self, rng: random.Random, dead: Iterable[int] = ()):
        self._rng = rng
        dead_set = set(dead)
        self._cards = [c for c in range(52) if c not in dead_set]

    def deal(self, n: int) -> tuple[int, ...]:
        if n > len(self._cards):
            raise ValueError("not enough cards in deck")
        dealt = self._rng.sample(self._cards, n)
        taken = set(dealt)
        self._cards = [c for c in self._cards if c not in taken]
        return tuple(dealt)

    def remaining(self) -> list[int]:
        return list(self._cards)
