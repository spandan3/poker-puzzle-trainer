from poker_trainer.api.text import (
    CATEGORY_NAMES,
    HAND_CLASS_NAMES,
    JUDGED_ON_RANGE,
    simplification_text,
)
from poker_trainer.engine.evaluator import HandClass
from poker_trainer.puzzle.model import SIMPLIFICATIONS
from poker_trainer.villain.features import HandCategory


def test_text_covers_all_codes():
    for cat in HandCategory:
        assert CATEGORY_NAMES[cat.name.lower()]
    assert set(CATEGORY_NAMES) == {c.name.lower() for c in HandCategory}
    for cls in HandClass:
        assert HAND_CLASS_NAMES[cls]
    for code in SIMPLIFICATIONS:
        assert simplification_text(code) == SIMPLIFICATIONS[code]
    assert CATEGORY_NAMES["strong_draw"] == "Strong draw"
    assert HAND_CLASS_NAMES[HandClass.TWO_PAIR] == "Two pair"
    assert "whole range" in JUDGED_ON_RANGE
