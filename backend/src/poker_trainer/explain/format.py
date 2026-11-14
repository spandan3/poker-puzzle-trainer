"""Number and label formats for explanations: the same text the frontend helpers produce.

JS ``Number.prototype.toFixed`` rounds the float's exact binary value and breaks exact ties away
from zero, so the helpers here quantize ``Decimal(y)`` (the exact value of the same float JS
formats) with ``ROUND_HALF_UP``. ``Decimal(repr(y))`` would be wrong: ``0.15.toFixed(1)`` is
``"0.1"`` because the float 0.15 is a little below 0.15.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from poker_trainer.engine.cards import RANKS, SUITS

MINUS = "−"
_SUIT_SYMBOLS = dict(zip(SUITS, "♣♦♥♠", strict=True))  # c d h s


def to_fixed(y: float, digits: int) -> str:
    """JS ``y.toFixed(digits)`` for finite ``y`` below 1e21."""
    if y == 0:  # -0 formats as "0" in JS
        y = 0.0
    return str(Decimal(y).quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP))


def bb(chips: int) -> str:
    """Chips as bb, like ``formatBb``: ``5`` -> ``"2.5 bb"``, ``200`` -> ``"100 bb"``."""
    chips = int(chips)
    whole = int(chips / 2)  # truncates toward zero, like Math.trunc
    half = chips % 2 != 0
    sign = "-" if half and chips < 0 and whole == 0 else ""
    return f"{sign}{whole}{'.5' if half else ''} bb"


def ev_bb(x: float) -> str:
    """An EV in bb, like ``formatEvBb``: two decimals, trailing zeros dropped, U+2212 for
    negatives, ``"0 bb"`` when it rounds to zero."""
    q = Decimal(to_fixed(float(x), 2))
    text = format(abs(q).normalize(), "f")
    return f"{MINUS if q < 0 else ''}{text} bb"


def pct(x: float, digits: int = 0) -> str:
    """A fraction as a percentage, like ``formatPct``: ``0.256`` -> ``"26%"``."""
    return f"{to_fixed(float(x) * 100, digits)}%"


def card(text: str) -> str:
    """An API card string as rank + suit symbol: ``"Ks"`` -> ``"K♠"``; tens stay ``"T"``."""
    if len(text) != 2 or text[0] not in RANKS or text[1] not in _SUIT_SYMBOLS:
        raise ValueError(f"invalid card: {text!r}")
    return text[0] + _SUIT_SYMBOLS[text[1]]


def cards(texts: list[str]) -> str:
    return " ".join(card(t) for t in texts)


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


def option_label(label: str) -> str:
    """Like the frontend's ``optionLabel``: ``"bet 100%"`` -> ``"Bet pot"``,
    ``"all-in"`` -> ``"All-in"``."""
    return capitalise(re.sub(r"\b100%", "pot", label, count=1, flags=re.ASCII))


def custom_label(kind: str, to: int) -> str:
    """A custom size in bb, like ``chosenLabel``: ``"Bet 7 bb"``, ``"Raise to 20 bb"``."""
    return f"Raise to {bb(to)}" if kind == "raise" else f"Bet {bb(to)}"


_GERUNDS = {
    "Fold": "folding",
    "Call": "calling",
    "Check": "checking",
    "Bet": "betting",
    "Raise": "raising",
}


def gerund(label: str) -> str:
    """A play's label as the headline writes it after a semicolon: ``"Bet 33%"`` ->
    ``"betting 33%"``, ``"All-in"`` -> ``"going all-in"``."""
    if label == "All-in":
        return "going all-in"
    first, _, rest = label.partition(" ")
    verb = _GERUNDS.get(first)
    if verb is None:
        return label
    return f"{verb} {rest}" if rest else verb


_BB_LABEL = re.compile(r"\b(to|bets?) (\d+)(?![\d%])", re.ASCII)
_HERO_VERB = re.compile(r"\bHero (fold|call)s\b", re.ASCII)


def bb_label(label: str) -> str:
    """Like the frontend's ``bbLabel``: chips in a server label shown in bb.

    ``"Pre-flop: opens to 5"`` -> ``"Pre-flop: opens to 2.5 bb"``.
    """
    out = _BB_LABEL.sub(lambda m: f"{m.group(1)} {bb(int(m.group(2)))}", label)
    return _HERO_VERB.sub(r"you \1", out)
