from dataclasses import replace

import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import combo_index
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.stats.hero import hero_category, hero_category_on
from poker_trainer.villain.features import (
    HandCategory,
    categorize,
    load_thresholds,
    range_features,
)

# The CategoryCode vocabulary (api.schemas), spelled out so a renamed category fails here.
CODES = {"nuts", "strong", "strong_draw", "medium", "weak_draw", "weak", "air"}

# The same seeds as tests/api/conftest.py.
SEEDS = {"preflop": (1, "preflop"), "flop": (1, "flop"), "turn": (1, "turn"), "river": (1, "river")}


@pytest.fixture(scope="module")
def puzzles():
    return {k: generate_puzzle(seed, street=st) for k, (seed, st) in SEEDS.items()}


def test_codes_match_hand_categories():
    assert {c.name.lower() for c in HandCategory} == CODES


@pytest.mark.parametrize("street", ["flop", "turn", "river"])
def test_postflop_matches_categorize(puzzles, street):
    p = puzzles[street]
    board = p.spot.state.board
    cats = categorize(range_features(board), load_thresholds())
    expected = HandCategory(int(cats[combo_index(*p.spot.hero)])).name.lower()
    assert hero_category(p) == expected
    assert hero_category(p) in CODES


def test_preflop_is_none(puzzles):
    assert puzzles["preflop"].spot.state.board == ()
    assert hero_category(puzzles["preflop"]) is None


def test_hero_category_on_empty_board_is_none():
    a, b = parse_cards("AhKh")
    assert hero_category_on((a, b), ()) is None


@pytest.mark.parametrize(
    ("hole", "board", "expected"),
    [
        ("AhKh", "Qh7h2h", "nuts"),  # nut flush
        ("7c7d", "Ks7h2s", "nuts"),  # middle set on a dry board
        ("Kc3d", "Ks8h4c", "strong"),  # top pair, weak kicker
        ("AhQh", "Kh7h2c", "strong_draw"),  # nut flush draw and an overcard
        ("5c5d", "AsKhQc", "medium"),  # underpair on a high board
        ("JcTd", "Ks9h2c", "weak_draw"),  # gutshot
        ("3c2d", "AhKsTd8c", "air"),
    ],
)
def test_hand_built(hole, board, expected):
    assert hero_category_on(parse_cards(hole), parse_cards(board)) == expected


def test_stale_categories_version_is_none(puzzles):
    p = puzzles["flop"]
    stale = replace(p, spot=replace(p.spot, categories_version=p.spot.categories_version + 1))
    assert hero_category(p) is not None
    assert hero_category(stale) is None
