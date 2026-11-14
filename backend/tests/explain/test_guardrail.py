from dataclasses import replace

import pytest
from explain_cases import facts, puzzle, result

from poker_trainer.explain.guardrail import check, check_claims, check_fields, numbers
from poker_trainer.explain.ollama import fields_of


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


def test_composites_are_their_own_tokens():
    assert numbers("1/3 and 3:1 and 2 to 1 and 3 in 10 and 2 out of 5 and 1e3") == {
        "ratio:1/3",
        "ratio:3:1",
        "ratio:2 to 1",
        "ratio:3 in 10",
        "ratio:2 out of 5",
        "ratio:1e3",
    }
    assert numbers("1 bb / (3 bb + 1 bb) = 25%") == {"1 bb", "3 bb", "25%"}
    assert numbers("Thirties, thrice, Quadrupled, threefold") == {
        "word:thirty",
        "word:thrice",
        "word:quadruple",
        "word:threefold",
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
        # ratios, fractions and scientific notation need the same composite in the facts
        ("1/3 of the time", "Pot: 3 bb\nCall: 1 bb", False),
        ("3:1", "Pot: 3 bb\nCall: 1 bb", False),
        ("2 to 1", "Pot: 2 bb\nCall: 1 bb", False),
        ("50/50", "Fold frequency: 50%", False),
        ("1e3", "Pot: 1 bb\nCall: 3 bb", False),
        ("3 in 10", "Pot: 10 bb\nCall: 3 bb", False),
        ("2 out of 5", "Pot: 5 bb\nCall: 2 bb", False),
        ("1 / 3 of the time", "Odds: 1/3", True),
        ("2 To 1", "Odds: 2 to 1", True),
        (
            "you need 1 bb / (3 bb + 1 bb) = 25%",
            "Pot odds formula: 1 bb / (3 bb + 1 bb) = 25%",
            True,
        ),
        # digits glued to letters count as their digits (the swap limit)
        ("a 3bet pot", "Raise: 3 bb", True),
        ("1.5x the pot", "Bet: 1.5 bb", True),
        # more number words
        ("in the twenties", "Pot: 20 bb", False),
        ("thrice", "3", False),
        ("quadrupled", "4", False),
        ("a fourfold rise", "4", False),
        ("twofold", "twofold", True),
    ],
)
def test_check(output, allowed, ok):
    assert check(output, allowed) is ok


def test_check_fields_names_each_failing_field():
    allowed = "Equity: 42.5%\nEV lost: 1.25 bb"
    fields = {"headline": "You lost 1.25 bb.", "hand": "Two streets went by.", "verdict": "42.5%"}
    assert check_fields(fields, allowed) == {"hand": {"word:two"}}
    assert check_fields({"headline": "Fine.", "verdict": "42.5% equity"}, allowed) == {}


# ---------------------------------------------------------------------------
# check_claims
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lost():
    """attempt_check_river's facts: Check chosen, Bet 33% the top play, verdict Mistake."""
    p = puzzle(1, "river")
    return facts(result(p, option=0), p)


def _fields(headline, verdict="It was a Mistake.", hand="You held a draw."):
    return {"headline": headline, "hand": hand, "verdict": verdict}


LOST_HEADLINE = "Bet 33% was the top play; checking cost you."


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        (_fields(LOST_HEADLINE), {}),
        # verdict words: only the actual verdict's, case-insensitive, whole words
        (_fields(LOST_HEADLINE, "It was a mistake."), {}),
        (_fields(LOST_HEADLINE, "Not the best, a Mistake."), {"verdict": "Best"}),
        (_fields(LOST_HEADLINE, "FINE, or a blunder?"), {"verdict": "Blunder, Fine"}),
        (_fields(LOST_HEADLINE, "Finesse and bestow are no verdicts."), {}),
        # the headline names the top play and, after a loss, the choice (label or gerund)
        (_fields("Bet 33% was the top play; Check cost you."), {}),
        (_fields("bet 33% beats checking here."), {}),
        (_fields("Checking cost you."), {"headline": "missing Bet 33%"}),
        (_fields("Bet 33% was the top play."), {"headline": "missing Check"}),
        (
            _fields("Bet 3% was the top play; checks cost you."),
            {"headline": "missing Bet 33%, Check"},
        ),
        (_fields("Betting 33% beats checking."), {}),
        # nothing about the result of the hand
        (_fields(LOST_HEADLINE, hand="Villain had a flush."), {"result": "villain had a"}),
        (_fields(LOST_HEADLINE, hand="Villain held K♠."), {"result": "villain held k♠"}),
        # a retelling of the line before the decision is not about Villain's cards
        (_fields(LOST_HEADLINE, hand="Villain had opened and then checked."), {}),
        (_fields(LOST_HEADLINE, hand="Villain's hand was weak."), {"result": "villain's hand was"}),
        (_fields(LOST_HEADLINE, hand="Villain’s hand was weak."), {"result": "villain’s hand was"}),
        (_fields(LOST_HEADLINE, hand="You won."), {"result": "won"}),
        (
            _fields(LOST_HEADLINE, hand="You lost the hand at showdown."),
            {"result": "lost the hand, showdown"},
        ),
        (
            _fields(LOST_HEADLINE, hand="Villain wins the hand, you win at showdown."),
            {"result": "villain wins the hand, you win at showdown"},
        ),
        # winning the pot when Villain folds is a faithful paraphrase, not a result
        (_fields(LOST_HEADLINE, hand="You win the pot when Villain folds."), {}),
        (_fields(LOST_HEADLINE, hand="A window, a winner, a lost hand: none of them banned."), {}),
    ],
)
def test_check_claims(lost, fields, expected):
    assert check_claims(fields, lost) == expected


def test_check_claims_when_the_top_play_was_found(lost):
    top = replace(lost, verdict="Best", loss_case="top", chosen_label="Bet 33%")
    assert check_claims(_fields("Bet 33% was right.", "Best."), top) == {}
    assert check_claims(_fields("You found it.", "Best."), top) == {"headline": "missing Bet 33%"}
    # a custom size that matched the top play: the headline names the choice, as the template's
    custom = replace(top, chosen_label="Bet 1 bb")
    assert check_claims(_fields("Bet 1 bb was the top play.", "Best."), custom) == {}
    assert check_claims(_fields("Bet 33% was the top play.", "Best."), custom) == {
        "headline": "missing Bet 1 bb"
    }


def test_check_claims_close_needs_both_plays(lost):
    close = replace(
        lost, verdict="Fine", loss_case="close", chosen_label="Fold", best_label="Raise 2.5x"
    )
    assert check_claims(_fields("Fold was close to Raise 2.5x.", "Fine."), close) == {}
    assert check_claims(_fields("Folding was close.", "Fine."), close) == {
        "headline": "missing Raise 2.5x"
    }


def test_the_template_passes_its_own_claim_checks(lost):
    p = puzzle(1, "river")
    template = result(p, option=0)["explanation"]
    assert check_claims(fields_of(template), lost) == {}
