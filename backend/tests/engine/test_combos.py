import pytest

from poker_trainer.engine.cards import rank_of, suit_of
from poker_trainer.engine.combos import (
    COMBOS,
    HAND_CLASSES,
    class_of_combo,
    combo_index,
    combos_of_class,
    grid_position,
)


def test_combos_count_unique_ordered():
    assert len(COMBOS) == 1326
    assert len(set(COMBOS)) == 1326
    assert all(hi > lo for hi, lo in COMBOS)


def test_combo_index_round_trip_and_order_insensitive():
    for i, (hi, lo) in enumerate(COMBOS):
        assert combo_index(hi, lo) == i
        assert combo_index(lo, hi) == i


def test_combo_index_rejects_identical():
    with pytest.raises(ValueError):
        combo_index(5, 5)


def test_hand_classes_count_and_labels():
    assert len(HAND_CLASSES) == 169
    assert len(set(HAND_CLASSES)) == 169
    assert "AKs" in HAND_CLASSES and "AKo" in HAND_CLASSES and "KAs" not in HAND_CLASSES


def test_class_combo_counts():
    total = 0
    for label in HAND_CLASSES:
        n = len(combos_of_class(label))
        expected = 6 if len(label) == 2 else 4 if label[2] == "s" else 12
        assert n == expected
        total += n
    assert total == 1326


def test_class_of_combo_consistent():
    for label in HAND_CLASSES:
        for i in combos_of_class(label):
            assert class_of_combo(i) == label
    assert class_of_combo(0) in HAND_CLASSES


def test_suitedness_matches_cards():
    for i in combos_of_class("AKs"):
        a, b = COMBOS[i]
        assert suit_of(a) == suit_of(b)
        assert {rank_of(a), rank_of(b)} == {12, 11}
    for i in combos_of_class("AKo"):
        a, b = COMBOS[i]
        assert suit_of(a) != suit_of(b)


def test_grid_position():
    assert grid_position("AA") == (0, 0)
    assert grid_position("AKs") == (0, 1)
    assert grid_position("AKo") == (1, 0)
    assert grid_position("22") == (12, 12)
    assert grid_position("32s") == (11, 12)
    assert grid_position("32o") == (12, 11)


def test_hand_classes_grid_order():
    assert HAND_CLASSES[0] == "AA"
    assert HAND_CLASSES[1] == "AKs"
    assert HAND_CLASSES[13] == "AKo"
    assert HAND_CLASSES[-1] == "22"
    for idx, label in enumerate(HAND_CLASSES):
        r, c = grid_position(label)
        assert idx == r * 13 + c
