"""All 1326 starting-hand combos and the 169 hand classes (13x13 grid)."""

from itertools import combinations

from poker_trainer.engine.cards import RANKS, rank_of, suit_of

# (hi, lo) with hi > lo, lexicographic order; index space for 1326-length arrays.
COMBOS: tuple[tuple[int, int], ...] = tuple((b, a) for a, b in combinations(range(52), 2))

_INDEX: dict[tuple[int, int], int] = {c: i for i, c in enumerate(COMBOS)}

# Grid index 0 = ace, 12 = deuce. Grid index g <-> RANKS index 12 - g.
_GRID_CHARS = RANKS[::-1]


def combo_index(a: int, b: int) -> int:
    if a == b:
        raise ValueError(f"identical cards: {a}")
    hi, lo = (a, b) if a > b else (b, a)
    try:
        return _INDEX[(hi, lo)]
    except KeyError:
        raise ValueError(f"invalid card ids: {a}, {b}") from None


def _label(r: int, c: int) -> str:
    """Label for grid cell (row, col)."""
    if r == c:
        return _GRID_CHARS[r] * 2
    if r < c:
        return _GRID_CHARS[r] + _GRID_CHARS[c] + "s"
    return _GRID_CHARS[c] + _GRID_CHARS[r] + "o"


HAND_CLASSES: tuple[str, ...] = tuple(_label(r, c) for r in range(13) for c in range(13))

_CLASS_OF: list[str] = []
_BY_CLASS: dict[str, list[int]] = {label: [] for label in HAND_CLASSES}
for _i, (_hi, _lo) in enumerate(COMBOS):
    _rh, _rl = rank_of(_hi), rank_of(_lo)
    _r, _c = 12 - _rh, 12 - _rl  # _r <= _c since _rh >= _rl
    if _rh != _rl and suit_of(_hi) != suit_of(_lo):
        _r, _c = _c, _r  # offsuit sits below the diagonal
    _lab = _label(_r, _c)
    _CLASS_OF.append(_lab)
    _BY_CLASS[_lab].append(_i)
_COMBOS_OF_CLASS: dict[str, tuple[int, ...]] = {k: tuple(v) for k, v in _BY_CLASS.items()}
_GRID_POS: dict[str, tuple[int, int]] = {_label(r, c): (r, c) for r in range(13) for c in range(13)}


def class_of_combo(i: int) -> str:
    return _CLASS_OF[i]


def combos_of_class(label: str) -> tuple[int, ...]:
    try:
        return _COMBOS_OF_CLASS[label]
    except KeyError:
        raise ValueError(f"invalid hand class: {label!r}") from None


def grid_position(label: str) -> tuple[int, int]:
    try:
        return _GRID_POS[label]
    except KeyError:
        raise ValueError(f"invalid hand class: {label!r}") from None
