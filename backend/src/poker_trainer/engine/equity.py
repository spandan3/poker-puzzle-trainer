"""Hero equity against a weighted villain range, and the "ahead right now" fraction.

Conventions:
- Card ids as in ``cards`` (0..51); ``evaluate`` ranks are LOWER = STRONGER.
- A villain combo is *blocked* if it shares a card with Hero's hole cards or the board.
  Blocked combos are dropped; the remaining combos are weighted by their range weight,
  normalised over the unblocked combos.
- ``equity = win + tie / 2``: a split pot counts half.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

import numpy as np

from poker_trainer.engine.cards import ensure_distinct
from poker_trainer.engine.combos import COMBOS
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.engine.ranges import Range

_VALID_BOARD_LENGTHS = (0, 3, 4, 5)
_EMPTY_MSG = "range is empty after removing blocked combos"


@dataclass(frozen=True)
class EquityResult:
    """Fractions in [0, 1]. ``equity = win + tie / 2``; ``std_error == 0.0`` when exact."""

    equity: float
    win: float
    tie: float
    exact: bool
    std_error: float


def _validate(hero: Sequence[int], board: Sequence[int]) -> tuple[tuple[int, int], tuple[int, ...]]:
    hero_t = tuple(int(c) for c in hero)
    board_t = tuple(int(c) for c in board)
    if len(hero_t) != 2:
        raise ValueError(f"hero must have exactly 2 cards, got {len(hero_t)}")
    if len(board_t) not in _VALID_BOARD_LENGTHS:
        raise ValueError(f"board must have 0, 3, 4 or 5 cards, got {len(board_t)}")
    for c in hero_t + board_t:
        if not 0 <= c < 52:
            raise ValueError(f"invalid card id: {c}")
    ensure_distinct(hero_t, board_t)
    return (hero_t[0], hero_t[1]), board_t


def _unblocked(dead: set[int]) -> list[int]:
    """Indices of combos sharing no card with ``dead``."""
    return [i for i, (a, b) in enumerate(COMBOS) if a not in dead and b not in dead]


def _weighted_live(villain: Range, dead: set[int]) -> tuple[list[int], list[float]]:
    """Unblocked combos with positive weight, and their weights. Raises if none."""
    idx = [i for i in _unblocked(dead) if villain[i] > 0.0]
    if not idx:
        raise ValueError(_EMPTY_MSG)
    return idx, [float(villain[i]) for i in idx]


def _exact_win_tie(
    hero: tuple[int, int], board: tuple[int, ...], combo_ids: Sequence[int]
) -> tuple[list[float], list[float]]:
    """Exact per-combo (win, tie) fractions for a turn or river board.

    Turn: enumerates every river card not in hero, board or the villain combo (44 cards).
    Hero's 7-card rank depends only on the river, so it is evaluated once per river.
    """
    wins: list[float] = []
    ties: list[float] = []
    if len(board) == 5:
        h = evaluate(hero + board)
        for i in combo_ids:
            v = evaluate(COMBOS[i] + board)
            wins.append(1.0 if h < v else 0.0)
            ties.append(1.0 if h == v else 0.0)
        return wins, ties
    if len(board) != 4:
        raise ValueError("exact equity requires a turn or river board")
    dead = set(hero) | set(board)
    rivers = [c for c in range(52) if c not in dead]
    hero_rank = {r: evaluate(hero + board + (r,)) for r in rivers}
    for i in combo_ids:
        a, b = COMBOS[i]
        w = t = n = 0
        for r in rivers:
            if r == a or r == b:
                continue
            h = hero_rank[r]
            v = evaluate((a, b) + board + (r,))
            n += 1
            if h < v:
                w += 1
            elif h == v:
                t += 1
        wins.append(w / n)
        ties.append(t / n)
    return wins, ties


def equity_vs_range(
    hero: tuple[int, int],
    board: Sequence[int],
    villain: Range,
    *,
    rng: random.Random | None = None,
    samples: int = 40_000,
) -> EquityResult:
    """Hero's equity against ``villain`` (weights 0..1 indexed like ``COMBOS``).

    Turn/river: exact — every unblocked positive-weight combo, weighted by its range
    weight (normalised), against every remaining runout card.
    Pre-flop/flop: Monte Carlo — each sample draws a villain combo with probability
    proportional to its weight among unblocked combos, then the missing board cards
    uniformly from the cards not held by Hero, the board or that combo.
    ``std_error = sqrt(p(1-p)/n)`` with ``p`` the estimated equity and ``n`` = ``samples``.
    Deterministic for a seeded ``rng``; ``None`` uses a fresh unseeded ``random.Random()``.
    """
    hero_t, board_t = _validate(hero, board)
    dead = set(hero_t) | set(board_t)
    idx, weights = _weighted_live(villain, dead)

    if len(board_t) >= 4:
        wins, ties = _exact_win_tie(hero_t, board_t, idx)
        total = math.fsum(weights)
        win = math.fsum(w * x for w, x in zip(weights, wins, strict=True)) / total
        tie = math.fsum(w * x for w, x in zip(weights, ties, strict=True)) / total
        return EquityResult(equity=win + tie / 2, win=win, tie=tie, exact=True, std_error=0.0)

    if samples <= 0:
        raise ValueError("samples must be positive")
    if rng is None:
        rng = random.Random()
    return _monte_carlo(hero_t, board_t, idx, weights, rng, samples)


def _monte_carlo(
    hero: tuple[int, int],
    board: tuple[int, ...],
    idx: list[int],
    weights: list[float],
    rng: random.Random,
    samples: int,
) -> EquityResult:
    dead = set(hero) | set(board)
    live = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    picks = rng.choices([COMBOS[i] for i in idx], cum_weights=list(accumulate(weights)), k=samples)
    sample = rng.sample
    # On the flop Hero's rank depends only on the unordered (turn, river) pair: cache it.
    hero_cache: dict[tuple[int, ...], int] = {}
    wins = ties = 0
    for a, b in picks:
        # The first `need` cards of a uniform ordered draw, after deleting the villain's
        # (at most 2) cards, are a uniform draw from the cards not held by anyone.
        drawn = sample(live, need + 2)
        runout = tuple(c for c in drawn if c != a and c != b)[:need]
        full = board + runout
        if need == 2:
            key = (runout[0], runout[1]) if runout[0] < runout[1] else (runout[1], runout[0])
            h = hero_cache.get(key)
            if h is None:
                h = hero_cache[key] = evaluate(hero + full)
        else:
            h = evaluate(hero + full)
        v = evaluate((a, b) + full)
        if h < v:
            wins += 1
        elif h == v:
            ties += 1
    win = wins / samples
    tie = ties / samples
    p = win + tie / 2
    return EquityResult(
        equity=p, win=win, tie=tie, exact=False, std_error=math.sqrt(p * (1 - p) / samples)
    )


def equity_by_combo(hero: tuple[int, int], board: Sequence[int], villain: Range) -> np.ndarray:
    """Exact equity of Hero against each villain combo, shape (1326,), turn/river only.

    Entries are NaN only for combos blocked by Hero's cards or the board (no range can
    contain them). Every unblocked combo gets its equity regardless of its weight in
    ``villain`` (so callers can show equity for any hand class); ``villain`` is used only
    to check that the range is not empty after blockers.
    """
    hero_t, board_t = _validate(hero, board)
    if len(board_t) not in (4, 5):
        raise ValueError("equity_by_combo requires a turn or river board")
    dead = set(hero_t) | set(board_t)
    _weighted_live(villain, dead)
    idx = _unblocked(dead)
    wins, ties = _exact_win_tie(hero_t, board_t, idx)
    out = np.full(len(COMBOS), np.nan, dtype=np.float64)
    out[idx] = np.asarray(wins) + np.asarray(ties) / 2
    return out


def _preflop_key(a: int, b: int) -> tuple[int, int, int]:
    """Strength of a 2-card hand; larger is stronger. Pair > unpaired; suits ignored."""
    ra, rb = a // 4, b // 4
    hi, lo = (ra, rb) if ra >= rb else (rb, ra)
    return (1 if hi == lo else 0, hi, lo)


def ahead_now(hero: tuple[int, int], board: Sequence[int], villain: Range) -> float:
    """Weighted fraction of unblocked villain combos Hero currently beats (ties count half).

    Flop/turn: best hand made with the board. Pre-flop: the two hole cards as a 2-card
    hand (pair beats unpaired, higher pair beats lower pair, unpaired compares high card
    then low card). Not defined on the river.
    """
    hero_t, board_t = _validate(hero, board)
    if len(board_t) == 5:
        raise ValueError("ahead_now is not used on the river")
    dead = set(hero_t) | set(board_t)
    idx, weights = _weighted_live(villain, dead)
    score = 0.0
    if board_t:
        h = evaluate(hero_t + board_t)
        for i, w in zip(idx, weights, strict=True):
            v = evaluate(COMBOS[i] + board_t)
            if h < v:
                score += w
            elif h == v:
                score += w / 2
    else:
        hk = _preflop_key(*hero_t)
        for i, w in zip(idx, weights, strict=True):
            vk = _preflop_key(*COMBOS[i])
            if hk > vk:
                score += w
            elif hk == vk:
                score += w / 2
    return score / math.fsum(weights)
