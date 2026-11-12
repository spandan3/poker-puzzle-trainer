"""The explain formats match the frontend helpers' output exactly.

The expected strings are literals produced once with ``node -e`` from the frontend's
``formatPct``, ``formatEvBb``, ``formatBb`` and ``bbLabel`` (lib/format.ts).
"""

import pytest

from poker_trainer.explain import format as fmt

# (x, digits, formatPct(x, digits))
PCT = [
    (0.0015, 1, "0.1%"),
    (0.0015, 0, "0%"),
    (0.005, 0, "1%"),
    (0.125, 0, "13%"),
    (0.375, 1, "37.5%"),
    (0.2142857142857143, 1, "21.4%"),
    (0.0005, 1, "0.1%"),
    (0.00149, 1, "0.1%"),
    (0.3749999, 1, "37.5%"),
    (0.995, 0, "100%"),
    (0.9995, 1, "100.0%"),
    (1.0000000000000007, 0, "100%"),
    (0, 1, "0.0%"),
    (-0.0004, 0, "-0%"),
    (-0.004, 1, "-0.4%"),
    (0.0105, 0, "1%"),
    (0.00125, 1, "0.1%"),
    (0.4634146341463415, 1, "46.3%"),
    (0.3492590615185275, 0, "35%"),
    (0.6065, 1, "60.7%"),
    (0.285, 0, "28%"),
    (0.565, 0, "56%"),
    (0.515, 0, "52%"),
    (0.555, 0, "56%"),
]

# (x, formatEvBb(x))
EV = [
    (0, "0 bb"),
    (-0.0, "0 bb"),
    (0.004, "0 bb"),
    (-0.004, "0 bb"),
    (0.005, "0.01 bb"),
    (-0.005, "−0.01 bb"),
    (0.015, "0.01 bb"),
    (0.025, "0.03 bb"),
    (1.005, "1 bb"),
    (2.675, "2.67 bb"),
    (2.2549, "2.25 bb"),
    (-17.780092228369558, "−17.78 bb"),
    (1.5940043676689566, "1.59 bb"),
    (0.125, "0.13 bb"),
    (-0.125, "−0.13 bb"),
    (2.5, "2.5 bb"),
    (100, "100 bb"),
    (0.1, "0.1 bb"),
    (-2.25, "−2.25 bb"),
    (1.0049999, "1 bb"),
    (0.0049999, "0 bb"),
]

# (chips, formatBb(chips))
BB = [
    (0, "0 bb"),
    (1, "0.5 bb"),
    (2, "1 bb"),
    (5, "2.5 bb"),
    (9, "4.5 bb"),
    (200, "100 bb"),
    (-1, "-0.5 bb"),
    (-3, "-1.5 bb"),
    (-4, "-2 bb"),
    (195, "97.5 bb"),
]

# (label, bbLabel(label))
BB_LABEL = [
    ("Pre-flop: opens to 5", "Pre-flop: opens to 2.5 bb"),
    ("Pre-flop: 3-bets to 15", "Pre-flop: 3-bets to 7.5 bb"),
    ("Turn: bets 8 (80% pot)", "Turn: bets 4 bb (80% pot)"),
    ("Flop: raises to 9", "Flop: raises to 4.5 bb"),
    ("Villain raises to 40 — Hero folds", "Villain raises to 20 bb — you fold"),
    ("Villain bets 12 — Hero calls", "Villain bets 6 bb — you call"),
    ("River: goes all-in", "River: goes all-in"),
    ("Flop: checks", "Flop: checks"),
    ("bet 100%", "bet 100%"),
]


@pytest.mark.parametrize(("x", "digits", "expected"), PCT)
def test_pct_matches_format_pct(x, digits, expected):
    assert fmt.pct(x, digits) == expected


@pytest.mark.parametrize(("x", "expected"), EV)
def test_ev_bb_matches_format_ev_bb(x, expected):
    assert fmt.ev_bb(x) == expected


@pytest.mark.parametrize(("chips", "expected"), BB)
def test_bb_matches_format_bb(chips, expected):
    assert fmt.bb(chips) == expected


@pytest.mark.parametrize(("label", "expected"), BB_LABEL)
def test_bb_label_matches_frontend(label, expected):
    assert fmt.bb_label(label) == expected


def test_to_fixed_uses_the_exact_float():
    assert fmt.to_fixed(0.15, 1) == "0.1"  # 0.15 is a little below 0.15
    assert fmt.to_fixed(2.5, 0) == "3"  # exact tie: away from zero, not to even
    assert fmt.to_fixed(-2.5, 0) == "-3"


def test_cards_and_labels():
    assert fmt.card("Ks") == "K♠"
    assert fmt.card("Td") == "T♦"
    assert fmt.cards(["Ah", "2c"]) == "A♥ 2♣"
    with pytest.raises(ValueError):
        fmt.card("10s")
    assert fmt.option_label("bet 100%") == "Bet pot"
    assert fmt.option_label("bet 33%") == "Bet 33%"
    assert fmt.option_label("all-in") == "All-in"
    assert fmt.option_label("raise 2.5x") == "Raise 2.5x"
    assert fmt.custom_label("bet", 14) == "Bet 7 bb"
    assert fmt.custom_label("raise", 41) == "Raise to 20.5 bb"
