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

- composites, taken out before the digit runs: a ratio or fraction ``A / B``, ``A:B``,
  ``A to B``, ``A in B``, ``A out of B`` (each number with an optional decimal part, spaces
  optional around ``/`` and ``:``), normalised (``"1 / 3"`` = ``"1/3"``, ``"2 To 1"`` =
  ``"2 to 1"``), and scientific notation (``"1e3"``, ``"2.5E-1"``). A composite passes only when
  the same normalised composite is in the allowed text: ``"1/3"`` or ``"3 in 10"`` never passes
  just because ``1``, ``3`` and ``10`` are facts. The pot-odds formula ``"1 bb / (3 bb + 1 bb)"``
  is no composite (a unit or a bracket sits between the numbers), so its numbers are checked
  one by one.

``check(output, allowed_text)`` is true when every number of ``output`` is in ``allowed_text``,
the facts' values (never the instructions or the fact names). A number with a unit must appear
with the same unit (``"25%"`` is not ``"25 bb"``); a bare number may match the same number with
any unit. Cards, number words and numeric characters must appear as such.

``check_claims(fields, facts)`` checks a few claims in words (a language model's text only;
the template passes them by construction, which a test checks on every fixture spot):

- ``verdict``: no verdict word (Best, Fine, Mistake, Blunder; case-insensitive, whole word)
  other than the actual verdict's word;
- ``headline``: the headline names the top play as the template's headline does (the choice's
  label when it matched or beat the top play, else the top play's label) and, when the choice
  lost EV (``loss_case`` is not ``"top"``), the choice too. A label matches as written or in
  the headline's gerund form (``"Fold"`` or ``"folding"``), case-insensitive, as whole words;
- ``result``: nothing about how the hand ended. Banned: the words ``won``, ``win``, ``wins``,
  ``winning``, ``showdown`` and the phrase ``lost the hand``, and Villain's actual hand
  ("Villain had", "Villain held", "Villain's hand was"). The template's own wording avoids all
  of them ("takes the pot uncontested", "profit on folds alone").

Known limits: a number swapped for another number from the facts, or a flipped sign, passes.
So does a digit run glued to letters, when its digits are in the facts: ``"3bet"``, ``"1st"``,
``"x2"`` and ``"1.5x"`` count as ``3``, ``1``, ``2`` and ``1.5`` (the same swap limit). Any
other claim in words that the model paraphrases wrongly (which play beats which, who is ahead,
"Villain folds more often than needed" turned around) is not checked.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal

from poker_trainer.explain.facts import Facts
from poker_trainer.explain.format import gerund

_CARD = re.compile(r"[2-9TJQKA][♣♦♥♠]")
_NUMBER = re.compile(r"\d+(?:\.\d+|,\d{1,2}(?!\d))?|(?<!\d)\.\d+", re.ASCII)
_NUM = r"(?:\d+(?:\.\d+|,\d{1,2}(?!\d))?|\.\d+)"
_COMPOSITE = re.compile(
    r"(?<![\d.,])(?:"
    rf"(?P<sci>{_NUM}[eE][+-]?\d+)"
    rf"|(?P<a>{_NUM})(?P<sep>\s*[/:]\s*|\s+(?:to|in|out\s+of)\s+)(?P<b>{_NUM})"
    r")(?![\d])",
    re.IGNORECASE | re.ASCII,
)
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
    "thrice",
    "double",
    "triple",
    "quadruple",
    "twofold",
    "threefold",
    "fourfold",
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
    "quadrupled": "quadruple",
    "twenties": "twenty",
    "thirties": "thirty",
    "forties": "forty",
    "fifties": "fifty",
    "sixties": "sixty",
    "seventies": "seventy",
    "eighties": "eighty",
    "nineties": "ninety",
}
_WORD = re.compile(
    r"\b(" + "|".join(sorted([*_ALIASES, *_WORDS], key=len, reverse=True)) + r")s?\b",
    re.IGNORECASE | re.ASCII,
)

_BARE = ""


def _normalise(token: str) -> str:
    d = Decimal(token.replace(",", "."))
    return format(d.normalize(), "f") if d != 0 else "0"


def _composite(m: re.Match[str]) -> str:
    if m.group("sci"):
        mantissa, exponent = re.split("[eE]", m.group("sci"))
        return f"ratio:{_normalise(mantissa)}e{int(exponent)}"
    sep = " ".join(m.group("sep").split()).lower()  # "/", ":", "to", "in", "out of"
    sep = sep if sep in ("/", ":") else f" {sep} "
    return f"ratio:{_normalise(m.group('a'))}{sep}{_normalise(m.group('b'))}"


def _split_composites(text: str) -> tuple[set[str], str]:
    """The composite tokens of ``text``, and ``text`` with each replaced by a space."""
    found = {_composite(m) for m in _COMPOSITE.finditer(text)}
    return found, _COMPOSITE.sub(" ", text)


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
    ``"char:½"``, ``"ratio:1/3"``."""
    cards, rest = _split_cards(text)
    composites, rest = _split_composites(rest)
    return cards | composites | {v + u for v, u in _digit_tokens(rest)} | _other_tokens(rest)


def unknown_numbers(output: str, allowed_text: str) -> set[str]:
    """The tokens of ``output`` that ``allowed_text`` does not allow (empty when it passes)."""
    allowed = numbers(allowed_text)
    allowed_values = {v for v, _ in _digit_tokens(_split_cards(allowed_text)[1])}
    out_cards, rest = _split_cards(output)
    out_composites, rest = _split_composites(rest)
    bad = (out_cards | out_composites) - allowed
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


# ---------------------------------------------------------------------------
# Claims in words
# ---------------------------------------------------------------------------

_VERDICT_WORD = re.compile(r"\b(best|fine|mistake|blunder)\b", re.IGNORECASE)
_RESULT = re.compile(
    r"\b(?:won|showdown|lost the hand)\b"
    r"|\b(?:you|Villain) (?:wins?|winning) (?:the hand|at showdown)\b"
    r"|\bVillain (?:had|held) (?:an?|the)\b|\bVillain (?:had|held) [2-9TJQKA][♣♦♥♠]"
    r"|\bVillain['’]s hand was\b",
    re.IGNORECASE,
)


def _names(text: str, label: str) -> bool:
    """True when ``text`` names the play ``label``, as written or as a gerund (whole words)."""
    return any(
        re.search(rf"(?<!\w){re.escape(form)}(?!\w)", text, re.IGNORECASE)
        for form in (label, gerund(label))
    )


def check_claims(fields: Mapping[str, str], facts: Facts) -> dict[str, str]:
    """``{rule: what hit}`` for every rule of the module doc a model's fields break (empty when
    they pass): ``verdict``, ``headline``, ``result``."""
    out: dict[str, str] = {}
    text = "\n".join(fields.values())
    wrong = sorted(
        {m.group(1).capitalize() for m in _VERDICT_WORD.finditer(text)} - {facts.verdict}
    )
    if wrong:
        out["verdict"] = ", ".join(wrong)
    headline = fields.get("headline", "")
    top = facts.chosen_label if facts.loss_case == "top" else facts.best_label
    needed = [top] if facts.loss_case == "top" else [top, facts.chosen_label]
    missing = [label for label in needed if not _names(headline, label)]
    if missing:
        out["headline"] = "missing " + ", ".join(missing)
    said = sorted({m.group().lower() for m in _RESULT.finditer(text)})
    if said:
        out["result"] = ", ".join(said)
    return out
