import random

import pytest

from poker_trainer.engine.cards import (
    Deck,
    card_str,
    ensure_distinct,
    parse_card,
    parse_cards,
)


def test_roundtrip_all_52():
    strings = [card_str(c) for c in range(52)]
    assert len(set(strings)) == 52
    for c, s in enumerate(strings):
        assert parse_card(s) == c


def test_parse_card_ids():
    assert parse_card("2c") == 0
    assert parse_card("As") == 51
    assert parse_card("ah") == parse_card("Ah") == 50


def test_parse_cards_separators():
    assert parse_cards("Ah Ks") == parse_cards("ah,ks") == parse_cards("AhKs")


@pytest.mark.parametrize("s", ["1h", "Ax", "A"])
def test_parse_invalid(s):
    with pytest.raises(ValueError):
        parse_card(s)


def test_parse_cards_duplicate_raises():
    with pytest.raises(ValueError):
        parse_cards("AhAh")


def test_deck_respects_dead():
    dead = parse_cards("AhKs")
    for seed in range(100):
        deck = Deck(random.Random(seed), dead)
        assert len(deck.remaining()) == 50
        dealt = deck.deal(50)
        assert not set(dealt) & set(dead)


def test_deck_deterministic():
    a = Deck(random.Random(7)).deal(5)
    b = Deck(random.Random(7)).deal(5)
    assert a == b


def test_ensure_distinct():
    with pytest.raises(ValueError, match="Ah"):
        ensure_distinct((50,), (50, 1))
    ensure_distinct((1,), (2, 3))
