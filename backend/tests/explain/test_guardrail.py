import pytest

from poker_trainer.explain.guardrail import check, check_fields, numbers


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
    assert numbers("fourth, fifths, Twelfth, twentieth, ninetieths, hundredth, thousandth") == {
        "word:fourth",
        "word:fifth",
        "word:twelfth",
        "word:twentieth",
        "word:ninetieth",
        "word:hundredth",
        "word:thousandth",
    }


def test_cards_are_their_own_tokens():
    assert numbers("K♠ 7♦ 2♣ and 2 more") == {"card:K♠", "card:7♦", "card:2♣", "2"}
    assert numbers("T♥9♣") == {"card:T♥", "card:9♣"}


def test_leading_dot_decimals():
    assert numbers(".5 bb and .25") == {"0.5 bb", "0.25"}
    assert numbers("12.5") == {"12.5"}


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
        # cards are their own tokens: their ranks are not numbers, and a card must be in the facts
        ("about 2/7 equity", "Flop: 7♦ 2♣ K♠", False),
        ("the 2nd barrel", "Flop: 7♦ 2♣ K♠", False),
        ("x2 the pot", "Flop: 7♦ 2♣ K♠", False),
        ("the 7♦ pairs you", "Flop: 7♦ 2♣ K♠", True),
        ("the 7♣ pairs you", "Flop: 7♦ 2♣ K♠", False),
        ("the 7 pairs you", "Flop: 7♦ 2♣ K♠", False),
        ("7♦ with 7 bb behind", "Flop: 7♦ 2♣ K♠\nPot: 7 bb", True),
        # ordinals and fraction words
        ("a fifth of the time", "Fold frequency: 20%", False),
        ("the seventh hand", "", False),
        ("three tenths", "three", False),
        ("a fifth", "a fifth", True),
        # leading-dot decimals
        (".5 bb", "Pot: 5 bb", False),
        (".5 bb", "Pot: 0.5 bb", True),
        ("one more card", "", True),
        ("Villain folds 35% of the time", "Fold frequency: 35%", True),
        # Task 3: the LLM table (spec §9, Review Focus 1)
        ("Calling loses 12.50 bb", "EV lost: 12.5 bb", True),
        ("Calling loses 12.5 bb", "EV lost: 12.50 bb", True),
        ("Calling loses 12.51 bb", "EV lost: 12.5 bb", False),
        ("about 1,5 bb", "Call: 1.5 bb", True),
        ("about 1,5 bb", "Call: 2.5 bb", False),
        ("an EV of −2.25 bb", "Check: -2.25 bb", True),
        ("an EV of −2.25 bb", "Check: -2.5 bb", False),
        ("about half the pot", "Pot: 10 bb\nBet: 5 bb", False),
        ("about half the pot", "Bet half pot", True),
        ("the halves of the range", "Pot: 10 bb", False),
        ("Villain folds twice as often", "Fold frequency: 40%", False),
        ("you made two pair", "Your cards: K♠ 7♦\nBoard: K♣ 7♣ 2♦", False),
        ("a ½ pot bet", "Bet 50% pot", False),
        ("x² more often", "Fold frequency: 20%", False),
        ("needs 25%", "Call: 25 bb", False),
        ("needs 25 bb", "Pot odds: 25%", False),
        ("the T♠ helps", "Board: T♠ 9♥ 2♣", True),
        ("the T♠ helps", "Board: T♥ 9♥ 2♣", False),
        ("Ten percent of the time", "Fold frequency: 10%", False),
    ],
)
def test_check(output, allowed, ok):
    assert check(output, allowed) is ok


def test_check_fields_names_each_failing_field():
    allowed = "Equity: 42.5%\nEV lost: 1.25 bb"
    fields = {"headline": "You lost 1.25 bb.", "hand": "Two streets went by.", "verdict": "42.5%"}
    assert check_fields(fields, allowed) == {"hand": {"word:two"}}
    assert check_fields({"headline": "Fine.", "verdict": "42.5% equity"}, allowed) == {}
