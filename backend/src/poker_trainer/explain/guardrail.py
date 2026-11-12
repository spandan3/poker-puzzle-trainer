"""The "no new numbers" check for explanation text.

``numbers(text)`` finds every number in a text:

- digit runs with an optional decimal part (``\\d+(?:[.,]\\d+)?``; a comma counts as a decimal
  point only before 1-2 digits), normalised (``"12.50"`` = ``"12.5"``, ``"4.0"`` = ``"4"``), with
  the unit that follows: ``%`` (or "percent") or ``bb`` (or "big blinds"). A sign is ignored;
- number words (``two`` ... ``twenty``, ``thirty`` ... ``ninety``, ``hundred``, ``half``,
  ``third``, ``twice``, ``double`` ...; plural ``s`` allowed, case-insensitive). ``one`` is not
  counted: it is too common in plain English;
- any other character Unicode gives a numeric value (``½``, ``²``, Roman numerals, non-ASCII
  digits).

``check(output, allowed_text)`` is true when every number of ``output`` is in ``allowed_text``,
the facts' values (never the instructions or the fact names). A number with a unit must appear
with the same unit (``"25%"`` is not ``"25 bb"``); a bare number may match the same number with
any unit. Number words and numeric characters must appear as such.

Known limit: a number swapped for another number from the facts, or a flipped sign, passes.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

_NUMBER = re.compile(r"\d+(?:\.\d+|,\d{1,2}(?!\d))?", re.ASCII)
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
]
_ALIASES = {
    "halves": "half",
    "halve": "half",
    "halved": "half",
    "doubled": "double",
    "tripled": "triple",
}
_WORD = re.compile(r"\b(" + "|".join([*_ALIASES, *_WORDS]) + r")s?\b", re.IGNORECASE | re.ASCII)

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


def numbers(text: str) -> set[str]:
    """Every number token: ``"12.5"``, ``"25%"``, ``"2.5 bb"``, ``"word:half"``, ``"char:½"``."""
    return {v + u for v, u in _digit_tokens(text)} | _word_tokens(text) | _char_tokens(text)


def unknown_numbers(output: str, allowed_text: str) -> set[str]:
    """The tokens of ``output`` that ``allowed_text`` does not allow (empty when it passes)."""
    allowed = numbers(allowed_text)
    allowed_values = {v for v, _ in _digit_tokens(allowed_text)}
    bad = set()
    for v, u in _digit_tokens(output):
        if (u == _BARE and v not in allowed_values) or (u != _BARE and v + u not in allowed):
            bad.add(v + u)
    bad |= (_word_tokens(output) | _char_tokens(output)) - allowed
    return bad


def check(output: str, allowed_text: str) -> bool:
    """True when every number in ``output`` appears in ``allowed_text`` (see the module doc)."""
    return not unknown_numbers(output, allowed_text)
