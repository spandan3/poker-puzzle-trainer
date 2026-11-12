"""Hero's own hand category on the decision board, in the ``CategoryCode`` vocabulary."""

from __future__ import annotations

from collections.abc import Sequence

from poker_trainer.engine.combos import combo_index
from poker_trainer.puzzle.model import Puzzle
from poker_trainer.villain.features import (
    HandCategory,
    categorize,
    load_thresholds,
    range_features,
)


def hero_category_on(hero: tuple[int, int], board: Sequence[int]) -> str | None:
    """Hero's category (``HandCategory`` name lower-cased) under the live category thresholds,
    the same ``categorize`` call the Villain model uses for every combo. None pre-flop."""
    if not board:
        return None
    cats = categorize(range_features(board), load_thresholds())
    return HandCategory(int(cats[combo_index(*hero)])).name.lower()


def hero_category(p: Puzzle) -> str | None:
    """Hero's category on the puzzle's decision board. None pre-flop, and None when the puzzle was
    made with other category thresholds than the live ones (no approximate value is stored)."""
    if p.spot.categories_version != load_thresholds().version:
        return None
    return hero_category_on(p.spot.hero, p.spot.state.board)
