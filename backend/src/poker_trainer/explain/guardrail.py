"""The "no new numbers" check for explanation text.

``numbers(text)`` finds every number in a text:

- cards (``"7♦"``: a rank ``2-9TJQKA`` and a suit symbol), their own kind of token. They are taken
  out of both texts before anything else, so a card's rank is never a number;
- digit runs with an optional decimal part (``\\d+(?:[.,]\\d+)?``; a comma counts as a decimal
  point only before 1-2 digits) or a leading-dot decimal (``".5"`` = ``"0.5"``), normalised
  (``"12.50"`` = ``"12.5"``, ``"4.0"`` = ``"4"``), with the unit that follows: ``%`` (or
  "percent") or ``bb`` (or "big blinds"). A sign is ignored;
- number words (``two`` ... ``twenty``, ``thirty`` ... ``ninety``, ``hundred``, ``half``,
  ``third``, ``twice``, ``double`` ...), ordinals and fraction words (``fourth`` ...
  ``twentieth``, ``thirtieth`` ... ``ninetieth``, ``hundredth``, ``thousandth``); plural ``s``
  allowed, case-insensitive. ``one`` is not counted: it is too common in plain English (nor are
  ``first`` and ``second``);
- any other character Unicode gives a numeric value (``½``, ``²``, Roman numerals, non-ASCII
  digits).

``check(output, allowed_text)`` is true when every number of ``output`` is in ``allowed_text``,
the facts' values (never the instructions or the fact names). A number with a unit must appear
with the same unit (``"25%"`` is not ``"25 bb"``); a bare number may match the same number with
any unit. Cards, number words and numeric characters must appear as such.

Known limit: a number swapped for another number from the facts, or a flipped sign, passes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal

_CARD = re.compile(r"[2-9TJQKA][♣♦♥♠]")
_NUMBER = re.compile(r"\d+(?:\.\d+|,\d{1,2}(?!\d))?|(?<!\d)\.\d+", re.ASCII)
_UNIT = re.compile(r"\s*(?:(%|percent\b|per cent\b)|(bbs?\b|big blinds?\b))", re.IGNORECASE)

_WORDS = [
    "zero",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "dozen",
    "half",
    "third",
    "quarter",
    "twice",
    "double",
    "triple",
    # ordinals and fraction words
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
    "twentieth",
    "thirtieth",
    "fortieth",
    "fiftieth",
    "sixtieth",
    "seventieth",
    "eightieth",
    "ninetieth",
    "hundredth",
    "thousandth",
]
_ALIASES = {
    "halves": "half",
    "halve": "half",
    "halved": "half",
    "doubled": "double",
    "tripled": "triple",
}
_WORD = re.compile(
    r"\b(" + "|".join(sorted([*_ALIASES, *_WORDS], key=len, reverse=True)) + r")s?\b",
    re.IGNORECASE | re.ASCII,
)

_BARE = ""


def _normalise(token: str) -> str:
    d = Decimal(token.replace(",", "."))
    return format(d.normalize(), "f") if d != 0 else "0"


def _digit_tokens(text: str) -> list[tuple[str, str]]:
    """``(value, unit)`` for every digit number; unit is ``"%"``, ``" bb"`` or ``""``."""
    out = []
    for m in _NUMBER.finditer(text):
        u = _UNIT.match(text, m.end())
        unit = _BARE if u is None else ("%" if u.group(1) else " bb")
        out.append((_normalise(m.group()), unit))
    return out


def _word_tokens(text: str) -> set[str]:
    out = set()
    for m in _WORD.finditer(text):
        w = m.group(1).lower()
        out.add("word:" + _ALIASES.get(w, w))
    return out


def _char_tokens(text: str) -> set[str]:
    return {
        "char:" + ch
        for ch in text
        if not ("0" <= ch <= "9") and unicodedata.numeric(ch, None) is not None
    }


def _split_cards(text: str) -> tuple[set[str], str]:
    """The card tokens of ``text``, and ``text`` with each card replaced by a space."""
    found = {"card:" + m.group() for m in _CARD.finditer(text)}
    return found, _CARD.sub(" ", text)


def _other_tokens(text: str) -> set[str]:
    """Word and numeric-character tokens of a text with its cards taken out."""
    return _word_tokens(text) | _char_tokens(text)


def numbers(text: str) -> set[str]:
    """Every number token: ``"12.5"``, ``"25%"``, ``"2.5 bb"``, ``"card:7♦"``, ``"word:half"``,
    ``"char:½"``."""
    found, rest = _split_cards(text)
    return found | {v + u for v, u in _digit_tokens(rest)} | _other_tokens(rest)


def unknown_numbers(output: str, allowed_text: str) -> set[str]:
    """The tokens of ``output`` that ``allowed_text`` does not allow (empty when it passes)."""
    allowed = numbers(allowed_text)
    allowed_values = {v for v, _ in _digit_tokens(_split_cards(allowed_text)[1])}
    out_cards, rest = _split_cards(output)
    bad = out_cards - allowed
    for v, u in _digit_tokens(rest):
        if (u == _BARE and v not in allowed_values) or (u != _BARE and v + u not in allowed):
            bad.add(v + u)
    bad |= _other_tokens(rest) - allowed
    return bad


def check(output: str, allowed_text: str) -> bool:
    """True when every number in ``output`` appears in ``allowed_text`` (see the module doc)."""
    return not unknown_numbers(output, allowed_text)


def check_fields(fields: Mapping[str, str], allowed_text: str) -> dict[str, set[str]]:
    """The unknown numbers of each field that fails (empty when every field passes). A language
    model's output is used only when this is empty: one failing field discards all of it."""
    out = {}
    for name, text in fields.items():
        bad = unknown_numbers(text, allowed_text)
        if bad:
            out[name] = bad
    return out
