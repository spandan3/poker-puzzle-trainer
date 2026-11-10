"""Weighted hand ranges over the 1326 combos."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from poker_trainer.engine.cards import RANKS, SUITS, parse_card
from poker_trainer.engine.combos import (
    COMBOS,
    HAND_CLASSES,
    combo_index,
    combos_of_class,
    grid_position,
)

# A Range is a float64 array of shape (1326,), indexed like COMBOS, values in [0, 1].
Range = np.ndarray

_RANK_IDX = {r: i for i, r in enumerate(RANKS)}


def empty_range() -> Range:
    return np.zeros(len(COMBOS), dtype=np.float64)


def full_range() -> Range:
    return np.ones(len(COMBOS), dtype=np.float64)


def _bad(token: str) -> ValueError:
    return ValueError(f"invalid range token: {token!r}")


def _class_parts(s: str, token: str) -> tuple[int, int, str]:
    """Parse 'AK', 'AKs', 'QQ' into (high_idx, low_idx, kind); kind in 's','o','' ."""
    if len(s) not in (2, 3):
        raise _bad(token)
    a, b = s[0].upper(), s[1].upper()
    if a not in _RANK_IDX or b not in _RANK_IDX:
        raise _bad(token)
    kind = s[2].lower() if len(s) == 3 else ""
    if kind not in ("", "s", "o"):
        raise _bad(token)
    hi, lo = sorted((_RANK_IDX[a], _RANK_IDX[b]), reverse=True)
    if hi == lo and kind:
        raise _bad(token)
    return hi, lo, kind


def _labels(hi: int, lo: int, kind: str) -> list[str]:
    h, lw = RANKS[hi], RANKS[lo]
    if hi == lo:
        return [h + lw]
    if kind:
        return [h + lw + kind]
    return [h + lw + "s", h + lw + "o"]


def _expand_classes(body: str, token: str) -> list[str]:
    if "-" in body:
        parts = body.split("-")
        if len(parts) != 2:
            raise _bad(token)
        h1, l1, k1 = _class_parts(parts[0], token)
        h2, l2, k2 = _class_parts(parts[1], token)
        if (h1 == l1) != (h2 == l2):
            raise _bad(token)
        if h1 == l1:
            lo, hi = sorted((h1, h2))
            return [RANKS[i] * 2 for i in range(lo, hi + 1)]
        if h1 != h2 or k1 != k2:
            raise _bad(token)
        lo, hi = sorted((l1, l2))
        out: list[str] = []
        for i in range(lo, hi + 1):
            out.extend(_labels(h1, i, k1))
        return out
    plus = body.endswith("+")
    if plus:
        body = body[:-1]
    hi, lo, kind = _class_parts(body, token)
    if not plus:
        return _labels(hi, lo, kind)
    out = []
    if hi == lo:
        for i in range(hi, 13):
            out.extend(_labels(i, i, ""))
    else:
        for i in range(lo, hi):
            out.extend(_labels(hi, i, kind))
    return out


def _specific_combo(body: str) -> int | None:
    if len(body) != 4:
        return None
    try:
        c1 = parse_card(body[0].upper() + body[1].lower())
        c2 = parse_card(body[2].upper() + body[3].lower())
    except ValueError:
        return None
    if body[1].lower() not in SUITS or body[3].lower() not in SUITS:
        return None
    if c1 == c2:
        return None
    return combo_index(c1, c2)


def parse_range(text: str) -> Range:
    r = empty_range()
    for raw in text.split(","):
        token = "".join(raw.split())
        if not token:
            continue
        body, sep, wtxt = token.partition(":")
        weight = 1.0
        if sep:
            try:
                weight = float(wtxt)
            except ValueError:
                raise _bad(token) from None
            if not 0.0 <= weight <= 1.0:  # also rejects NaN
                raise ValueError(f"weight out of range [0, 1] in token: {token!r}")
        idx = _specific_combo(body)
        if idx is not None:
            r[idx] = weight
            continue
        for label in _expand_classes(body, token):
            for i in combos_of_class(label):
                r[i] = weight
    return r


def remove_blocked(r: Range, dead: Iterable[int]) -> Range:
    out = np.array(r, dtype=np.float64, copy=True)
    dead_set = set(dead)
    for i, (a, b) in enumerate(COMBOS):
        if a in dead_set or b in dead_set:
            out[i] = 0.0
    return out


def total_weight(r: Range) -> float:
    return float(np.sum(r))


def class_grid(r: Range) -> np.ndarray:
    grid = np.zeros((13, 13), dtype=np.float64)
    for label in HAND_CLASSES:
        row, col = grid_position(label)
        grid[row, col] = float(np.mean(r[list(combos_of_class(label))]))
    return grid
