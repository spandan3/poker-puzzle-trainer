import pytest

from poker_trainer.explain.guardrail import check, numbers


def test_numbers_are_normalised():
    assert numbers("12.50 and 4.0 and 100 and 007") == {"12.5", "4", "100", "7"}
    assert numbers("EV −2.25 bb, -3%") == {"2.25 bb", "3%"}
    assert numbers("1,5 then 1,500") == {"1.5", "1", "500"}


def test_numbers_carry_their_unit():
    assert numbers("25% and 25 bb and 25bb and 25 percent and 3 big blinds") == {
        "25%",
        "25 bb",
        "3 bb",
    }


def test_number_words_and_unicode_numerals():
    assert numbers("Two pair, halves, Twice, a third") == {
        "word:two",
        "word:half",
        "word:twice",
        "word:third",
    }
    assert numbers("one hand") == set()  # "one" is too common to count
    assert numbers("½ and x² and Ⅷ") == {"char:½", "char:²", "char:Ⅷ"}
    assert numbers("٣") == {"char:٣"}  # an Arabic-Indic three


@pytest.mark.parametrize(
    ("output", "allowed", "ok"),
    [
        ("EV 12.50 bb", "EV: 12.5 bb", True),
        ("1,5 bb", "1.5 bb", True),
        ("−2.25 bb", "-2.25 bb", True),  # the sign is not checked (known limit)
        ("2.26 bb", "2.25 bb", False),
        ("25%", "25 bb", False),
        ("25 bb", "25%", False),
        ("25", "25%", True),  # a bare number may drop its unit
        ("25 percent", "25%", True),
        ("half the time", "50%", False),
        ("halves", "half", True),
        ("twice", "2", False),
        ("two pair", "Pair", False),
        ("½ pot", "0.5", False),
        ("x²", "x2", False),
        ("T♠ and 9♥", "Board: T♠ 9♥", True),
        ("one more card", "", True),
        ("Villain folds 35% of the time", "Fold frequency: 35%", True),
    ],
)
def test_check(output, allowed, ok):
    assert check(output, allowed) is ok
