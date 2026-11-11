"""Display text for the codes the API returns (categories, hand classes, simplifications)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from poker_trainer.engine.evaluator import HandClass
from poker_trainer.puzzle.model import SIMPLIFICATIONS

# Keyed by the lower-case codes ``CategoryRow.category`` holds (``HandCategory.X.name.lower()``).
CATEGORY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "nuts": "Nuts / near-nuts",
        "strong": "Strong value",
        "strong_draw": "Strong draw",
        "medium": "Medium made hand",
        "weak_draw": "Weak draw",
        "weak": "Weak made hand",
        "air": "Air",
    }
)

HAND_CLASS_NAMES: Mapping[HandClass, str] = MappingProxyType(
    {
        HandClass.HIGH_CARD: "High card",
        HandClass.PAIR: "Pair",
        HandClass.TWO_PAIR: "Two pair",
        HandClass.THREE_OF_A_KIND: "Three of a kind",
        HandClass.STRAIGHT: "Straight",
        HandClass.FLUSH: "Flush",
        HandClass.FULL_HOUSE: "Full house",
        HandClass.FOUR_OF_A_KIND: "Four of a kind",
        HandClass.STRAIGHT_FLUSH: "Straight flush",
    }
)

JUDGED_ON_RANGE = "Graded against Villain's whole range, not this run-out."


def category_name(code: str) -> str:
    return CATEGORY_NAMES[code]


def simplification_text(code: str) -> str:
    return SIMPLIFICATIONS[code]
