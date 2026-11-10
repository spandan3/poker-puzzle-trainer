"""Hand features for the Villain strategy: strength, outs, categories, texture, SPR."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
from importlib.resources import files

import numpy as np

from poker_trainer.engine.cards import rank_of, suit_of
from poker_trainer.engine.combos import COMBOS
from poker_trainer.engine.evaluator import HandClass, evaluate, hand_class
from poker_trainer.game.state import HandState, Street

_STRAIGHT_MAX_RANK = max(r for r in range(1, 8000) if hand_class(r) >= HandClass.STRAIGHT)


class HandCategory(IntEnum):
    AIR = 0
    WEAK_DRAW = 1
    WEAK = 2
    MEDIUM = 3
    STRONG_DRAW = 4
    STRONG = 5
    NUTS = 6


@dataclass(frozen=True)
class RangeFeatures:
    board: tuple[int, ...]
    strength: np.ndarray
    beaten_by: np.ndarray
    outs: np.ndarray


def range_features(board: Sequence[int]) -> RangeFeatures:
    b = tuple(int(c) for c in board)
    if len(b) not in (3, 4, 5):
        raise ValueError(f"board must have 3, 4 or 5 cards, got {len(b)}")
    return _range_features(b)


@lru_cache(maxsize=256)
def _range_features(board: tuple[int, ...]) -> RangeFeatures:
    n = len(COMBOS)
    on_board = set(board)
    live = [i for i, (a, b) in enumerate(COMBOS) if a not in on_board and b not in on_board]
    ranks = np.array([evaluate((*COMBOS[i], *board)) for i in live])

    # Lower rank is stronger: "worse" hands are those with a strictly higher rank.
    srt = np.sort(ranks)
    left = np.searchsorted(srt, ranks, side="left")
    right = np.searchsorted(srt, ranks, side="right")
    total = len(srt) - 1  # exclude the combo itself
    worse = len(srt) - right
    ties = right - left - 1
    better = left
    strength = np.full(n, np.nan)
    beaten_by = np.full(n, np.nan)
    strength[live] = (worse + ties / 2) / total
    beaten_by[live] = better / total

    outs = np.full(n, -1, dtype=np.int64)
    if len(board) == 5:
        outs[live] = 0
    else:
        unseen = [x for x in range(52) if x not in on_board]
        board_best = {x: evaluate((*board, x)) if len(board) + 1 >= 5 else None for x in unseen}
        for i, r in zip(live, ranks, strict=True):
            if r <= _STRAIGHT_MAX_RANK:
                outs[i] = 0
                continue
            hole = COMBOS[i]
            count = 0
            for x in unseen:
                if x in hole:
                    continue
                full = evaluate((*hole, *board, x))
                if full > _STRAIGHT_MAX_RANK:
                    continue
                bb = board_best[x]
                if bb is not None and not full < bb:
                    continue
                count += 1
            outs[i] = count
    return RangeFeatures(board, strength, beaten_by, outs)


@dataclass(frozen=True)
class CategoryThresholds:
    version: int
    nuts_max_beaten: float
    strong_min: float
    strong_draw_outs: int
    medium_min: float
    weak_draw_outs: int
    weak_min: float


def load_thresholds() -> CategoryThresholds:
    raw = json.loads(
        files("poker_trainer.villain").joinpath("categories.json").read_text(encoding="utf-8")
    )
    return CategoryThresholds(**raw)


def categorize(f: RangeFeatures, t: CategoryThresholds) -> np.ndarray:
    s, bb, o = f.strength, f.beaten_by, f.outs
    live = ~np.isnan(s)
    with np.errstate(invalid="ignore"):
        conds = [
            bb <= t.nuts_max_beaten,
            s >= t.strong_min,
            o >= t.strong_draw_outs,
            s >= t.medium_min,
            o >= t.weak_draw_outs,
            s >= t.weak_min,
        ]
    cats = [
        HandCategory.NUTS,
        HandCategory.STRONG,
        HandCategory.STRONG_DRAW,
        HandCategory.MEDIUM,
        HandCategory.WEAK_DRAW,
        HandCategory.WEAK,
    ]
    out = np.select(conds, [int(c) for c in cats], default=int(HandCategory.AIR))
    return np.where(live, out, -1).astype(np.int8)


@dataclass(frozen=True)
class BoardTexture:
    paired: bool
    monotone: bool
    two_tone: bool
    connected: bool
    wet: bool


def board_texture(board: Sequence[int]) -> BoardTexture:
    b = [int(c) for c in board]
    ranks = [rank_of(c) for c in b]
    suit_counts = [sum(1 for c in b if suit_of(c) == s) for s in range(4)]
    paired = len(set(ranks)) < len(ranks)
    monotone = max(suit_counts) >= 3
    two_tone = not monotone and 2 in suit_counts
    uniq = set(ranks)
    if 12 in uniq:
        uniq.add(-1)
    srt = sorted(uniq)
    connected = any(srt[i + 2] - srt[i] <= 4 for i in range(len(srt) - 2))
    return BoardTexture(paired, monotone, two_tone, connected, monotone or two_tone or connected)


def street_spr(s: HandState) -> float:
    if s.street == Street.PREFLOP:
        raise ValueError("SPR is undefined pre-flop")
    return min(s.stacks[i] + s.street_bets[i] for i in (0, 1)) / s.pot


range_features.cache_clear = _range_features.cache_clear  # type: ignore[attr-defined]
