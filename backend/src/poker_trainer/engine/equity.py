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

    Equivalent to ``combo_equity(hero, board, villain, ...).vs(villain)``. Negative or
    non-finite weights on live (unblocked) combos raise ``ValueError``; weights on
    blocked combos are ignored.
    """
    return combo_equity(hero, board, villain, rng=rng, samples=samples).vs(villain)


class UnsampledRange(ValueError):
    """A Monte Carlo sub-range none of whose positive-weight combos was ever sampled."""


@dataclass(frozen=True, eq=False)
class ComboEquity:
    """Per-combo outcome table from one equity run, re-weightable to sub-ranges of ``base``.

    All arrays are read-only float64, shape (1326,), indexed like ``COMBOS``.

    - ``base``: the villain range of the run, blocked combos set to 0.
    - Exact (turn/river): ``wins``/``ties`` are each combo's exact win/tie fractions and
      ``count`` is 1 on every combo with ``base > 0`` (0 elsewhere).
    - Monte Carlo (pre-flop/flop): ``count`` is how many samples drew the combo, and
      ``wins``/``ties`` how many of those Hero won/tied.
    """

    hero: tuple[int, int]
    board: tuple[int, ...]
    base: np.ndarray
    wins: np.ndarray
    ties: np.ndarray
    count: np.ndarray
    exact: bool

    def vs(self, weights: Range) -> EquityResult:
        """Hero's equity against the sub-range ``weights`` of ``base``.

        Weights on combos blocked by Hero or the board are ignored. With ``r = weights``
        (exact) or ``r = weights / base`` (Monte Carlo importance ratio),
        ``win = sum(r*wins) / sum(r*count)``, ``tie`` likewise, ``equity = win + tie/2``.
        Monte Carlo ``std_error = sqrt(p(1-p)/n_eff)`` with Kish
        ``n_eff = sum(r*count)**2 / sum(r*r*count)``.

        Raises ``ValueError("empty range")`` if no unblocked weight is positive,
        ``ValueError("weights outside base range")`` for a positive unblocked weight
        where ``base == 0``, and ``UnsampledRange`` if ``sum(r*count) == 0``.
        """
        w = np.asarray(weights, dtype=np.float64)
        if w.shape != (len(COMBOS),):
            raise ValueError(f"weights must have shape ({len(COMBOS)},), got {w.shape}")
        live = _live_mask(self.hero, self.board)
        if not np.all(np.isfinite(w[live])) or np.any(w[live] < 0.0):
            raise ValueError("weights must be finite and non-negative")
        w = np.where(live, w, 0.0)
        if not np.any(w > 0.0):
            raise ValueError("empty range")
        in_base = self.base > 0.0
        if np.any((w > 0.0) & ~in_base):
            raise ValueError("weights outside base range")
        if self.exact:
            r = w
        else:
            r = np.zeros_like(w)
            np.divide(w, self.base, out=r, where=in_base)
        n = math.fsum(r * self.count)
        if n == 0.0:
            raise UnsampledRange("no sampled combo of the sub-range has positive weight")
        win = math.fsum(r * self.wins) / n
        tie = math.fsum(r * self.ties) / n
        p = win + tie / 2
        if self.exact:
            return EquityResult(equity=p, win=win, tie=tie, exact=True, std_error=0.0)
        n_eff = n * n / math.fsum(r * r * self.count)
        return EquityResult(
            equity=p, win=win, tie=tie, exact=False, std_error=math.sqrt(p * (1 - p) / n_eff)
        )


def _live_mask(hero: tuple[int, int], board: tuple[int, ...]) -> np.ndarray:
    """Boolean (1326,): combos sharing no card with Hero or the board."""
    mask = np.zeros(len(COMBOS), dtype=bool)
    mask[_unblocked(set(hero) | set(board))] = True
    return mask


def _read_only(a: np.ndarray) -> np.ndarray:
    a.setflags(write=False)
    return a


def combo_equity(
    hero: tuple[int, int],
    board: Sequence[int],
    villain: Range,
    *,
    rng: random.Random | None = None,
    samples: int = 40_000,
) -> ComboEquity:
    """Run one equity computation against ``villain`` and keep the per-combo outcomes.

    Turn/river: exact per-combo fractions for every unblocked positive-weight combo.
    Pre-flop/flop: Monte Carlo with the same draws as ``equity_vs_range``. Re-weight to
    any sub-range of ``villain`` with ``ComboEquity.vs``.
    Deterministic for a seeded ``rng``; ``None`` uses a fresh unseeded ``random.Random()``.
    """
    hero_t, board_t = _validate(hero, board)
    dead = set(hero_t) | set(board_t)
    idx, weights = _weighted_live(villain, dead)
    base = np.zeros(len(COMBOS), dtype=np.float64)
    base[idx] = weights

    if len(board_t) >= 4:
        wins_l, ties_l = _exact_win_tie(hero_t, board_t, idx)
        wins = np.zeros(len(COMBOS), dtype=np.float64)
        ties = np.zeros(len(COMBOS), dtype=np.float64)
        count = np.zeros(len(COMBOS), dtype=np.float64)
        wins[idx] = wins_l
        ties[idx] = ties_l
        count[idx] = 1.0
        exact = True
    else:
        if samples <= 0:
            raise ValueError("samples must be positive")
        if rng is None:
            rng = random.Random()
        wins, ties, count = _monte_carlo(hero_t, board_t, idx, weights, rng, samples)
        exact = False
    return ComboEquity(
        hero=hero_t,
        board=board_t,
        base=_read_only(base),
        wins=_read_only(wins),
        ties=_read_only(ties),
        count=_read_only(count),
        exact=exact,
    )


def _monte_carlo(
    hero: tuple[int, int],
    board: tuple[int, ...],
    idx: list[int],
    weights: list[float],
    rng: random.Random,
    samples: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-combo sample tallies (wins, ties, count), each float64 of shape (1326,)."""
    dead = set(hero) | set(board)
    live = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    # Choosing over the index list consumes the RNG exactly as choosing over the combos.
    picks = rng.choices(idx, cum_weights=list(accumulate(weights)), k=samples)
    sample = rng.sample
    # On the flop Hero's rank depends only on the unordered (turn, river) pair: cache it.
    hero_cache: dict[tuple[int, ...], int] = {}
    n_combos = len(COMBOS)
    wins = [0] * n_combos
    ties = [0] * n_combos
    count = [0] * n_combos
    for i in picks:
        a, b = COMBOS[i]
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
        count[i] += 1
        if h < v:
            wins[i] += 1
        elif h == v:
            ties[i] += 1
    return (
        np.asarray(wins, dtype=np.float64),
        np.asarray(ties, dtype=np.float64),
        np.asarray(count, dtype=np.float64),
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
