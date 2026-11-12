"""``Facts``: every number an explanation may use, already formatted as text by code.

Built from the stored result dict (``views.attempt_result``, before ``explanation``), the
frozen puzzle and its action log (``views.action_log``, passed in by the view). Nothing is regraded: every number is a stored or frozen value, formatted like the
frontend view that shows the same quantity:

| Quantity                              | Format       | Matches                       |
|---------------------------------------|--------------|-------------------------------|
| equity vs the whole range, ahead now  | pct, 1 digit | the summary (``guessLines``)  |
| pot odds                              | pct, 1 digit | Maths                         |
| fold frequency of an option           | pct, 0 digit | Options table                 |
| fold equity a bet or raise needs      | pct, 1 digit | Maths                         |
| equity vs the continuing range        | pct, 1 digit | Options table                 |
| category share                        | pct, 1 digit | CategoryTable                 |
| Hero's equity against a category      | pct, 0 digit | CategoryTable                 |
| EV, EV lost                           | ``ev_bb``    | Options / summary             |

The run-out after the decision and Villain's hole cards are never read.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from poker_trainer.engine.cards import card_str
from poker_trainer.explain.format import (
    bb,
    bb_label,
    card,
    cards,
    custom_label,
    ev_bb,
    option_label,
    pct,
    to_fixed,
)
from poker_trainer.game.state import Street, amount_to_call, position_name, total_pot
from poker_trainer.puzzle.model import Puzzle

EV_EPSILON = 0.005  # bb; the frontend's EV_EPSILON (lib/result.ts)
FRACTION_TOL = 0.001  # a formula is shown only when it reproduces the API number this closely

VERDICT_WORDS = {"best": "Best", "fine": "Fine", "mistake": "Mistake", "blunder": "Blunder"}
STREET_WORDS = {"preflop": "Pre-flop", "flop": "Flop", "turn": "Turn", "river": "River"}

LossCase = Literal["top", "close", "lost"]


@dataclass(frozen=True)
class ActionFact:
    street: str  # "preflop" ... "river"
    actor: Literal["hero", "villain"]
    text: str  # "opened to 2.5 bb", "checked", "raised all-in to 97.5 bb"


@dataclass(frozen=True)
class OptionFact:
    label: str  # display label: "Bet pot", "Raise to 20 bb"
    kind: str
    ev: str
    fold_freq: str | None
    equity_vs_continue: str | None
    never_continues: bool  # a bet or raise Villain always folds to
    is_best: bool
    is_chosen: bool
    # a bet or raise: the fold equity it needs to profit on folds alone ("put / (pot + put)")
    required_fold_equity: str | None = None
    required_formula: str | None = None  # "1.5 bb / (5 bb + 1.5 bb)" when it reproduces it
    folds_pay: bool | None = None  # fold frequency >= required (Maths' "Folds alone pay")
    # how the shown strings compare: "more than", "less than", or "close to" when the rounded
    # strings disagree with the exact comparison (fold frequency has no decimal)
    fold_relation: str | None = None

    @property
    def aggressive(self) -> bool:
        return self.kind in ("bet", "raise")


@dataclass(frozen=True)
class CategoryFact:
    name: str
    share: str
    equity: str


@dataclass(frozen=True)
class Facts:
    street: str
    hero_position: str  # "BTN" / "BB"
    villain_position: str
    hero_cards: str
    flop: str | None  # the board at the decision, street by street
    turn: str | None
    river: str | None
    actions: tuple[ActionFact, ...]
    profile_label: str
    profile_description: str
    pot: str
    to_call: str | None
    facing_bet: bool  # a call option exists (Hero first in on the button has none)
    chosen_label: str
    best_label: str
    verdict: str
    loss_case: LossCase
    ev_loss: str
    best_is_chosen: bool
    equity: str
    ahead_now: str | None
    pot_odds: str | None
    pot_odds_formula: str | None  # "2 bb / (5 bb + 2 bb)" when it reproduces pot_odds
    call_amount: str | None
    equity_beats_pot_odds: bool | None
    options: tuple[OptionFact, ...]
    check_best: bool
    best_bet: OptionFact | None  # the highest-EV bet or raise
    categories: tuple[CategoryFact, ...]  # the largest two by share
    range_steps: tuple[str, ...]  # without "Start", in bb

    @property
    def chosen(self) -> OptionFact:
        return next(o for o in self.options if o.is_chosen)

    @property
    def best(self) -> OptionFact:
        return next(o for o in self.options if o.is_best)

    def pairs(self) -> list[tuple[str, str]]:
        """``(name, value)`` for every fact, in a fixed order."""
        out: list[tuple[str, str]] = [
            ("Street", STREET_WORDS[self.street]),
            ("Your position", self.hero_position),
            ("Villain's position", self.villain_position),
            ("Your cards", self.hero_cards),
        ]
        for name, value in (("Flop", self.flop), ("Turn", self.turn), ("River", self.river)):
            if value is not None:
                out.append((name, value))
        for a in self.actions:
            who = "you" if a.actor == "hero" else "Villain"
            out.append((f"{STREET_WORDS[a.street]} action", f"{who} {a.text}"))
        out += [
            ("Villain's profile", self.profile_label),
            ("Profile description", self.profile_description),
            ("Pot", self.pot),
        ]
        if self.to_call is not None:
            out.append(("To call", self.to_call))
        out += [
            ("Your choice", self.chosen_label),
            ("Top play", self.best_label),
            ("Verdict", self.verdict),
            ("EV lost", self.ev_loss),
            ("Your equity against the whole range", self.equity),
        ]
        if self.ahead_now is not None:
            out.append(("Share of the range you are ahead of now", self.ahead_now))
        if self.pot_odds is not None:
            out.append(("Pot odds", self.pot_odds))
        if self.pot_odds_formula is not None:
            out.append(("Pot odds formula", f"{self.pot_odds_formula} = {self.pot_odds}"))
        if self.call_amount is not None:
            out.append(("Call amount", self.call_amount))
        for o in self.options:
            parts = [f"EV {o.ev}"]
            if o.fold_freq is not None:
                parts.append(f"Villain folds {o.fold_freq}")
            if o.required_fold_equity is not None:
                needed = o.required_fold_equity
                if o.required_formula is not None:
                    needed = f"{o.required_formula} = {needed}"
                parts.append(f"fold equity needed {needed}")
            if o.equity_vs_continue is not None:
                parts.append(f"equity against the continuing range {o.equity_vs_continue}")
            out.append(("Option", f"{o.label}: {', '.join(parts)}"))
        for c in self.categories:
            out.append(
                (
                    "Range category",
                    f"{c.name}: {c.share} of the range, your equity {c.equity}",
                )
            )
        for step in self.range_steps:
            out.append(("Range step", step))
        return out

    def as_lines(self) -> list[str]:
        """``"Name: value"`` lines: the facts block given to a language model."""
        return [f"{name}: {value}" for name, value in self.pairs()]

    def values_text(self) -> str:
        """The facts' values only (no names): the text a guardrail checks numbers against."""
        return "\n".join(value for _, value in self.pairs())


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


STREET_KEYS = {
    Street.PREFLOP: "preflop",
    Street.FLOP: "flop",
    Street.TURN: "turn",
    Street.RIVER: "river",
}


def _position(puzzle: Puzzle, seat: int) -> str:
    return position_name(puzzle.spot.state, seat)


def _board_strs(puzzle: Puzzle) -> list[str]:
    """The board at the decision (never the run-out after it)."""
    return [card_str(int(c)) for c in puzzle.spot.state.board]


def _hero_strs(puzzle: Puzzle) -> list[str]:
    return [card_str(int(c)) for c in puzzle.spot.hero]


def _action_text(entry: dict[str, Any], raises_before: int) -> str:
    kind = entry["kind"]
    if kind == "bet" and entry["all_in"]:
        return f"went all-in for {bb(entry['to'])}"
    if kind == "raise" and entry["all_in"]:
        return f"raised all-in to {bb(entry['to'])}"
    if kind == "bet":
        return f"bet {bb(entry['to'])}"
    if kind == "raise":
        if entry["street"] == "preflop":
            verb = "opened" if raises_before == 0 else "re-raised"
            return f"{verb} to {bb(entry['to'])}"
        return f"raised to {bb(entry['to'])}"
    if kind == "call":
        return "called all-in" if entry["all_in"] else "called"
    return {"check": "checked", "fold": "folded"}[kind]


def _actions(log: list[dict[str, Any]]) -> tuple[ActionFact, ...]:
    out = []
    raises = 0
    for e in log:  # kind / to / all_in only, never the text (in chips)
        out.append(ActionFact(e["street"], e["actor"], _action_text(e, raises)))
        if e["street"] == "preflop" and e["kind"] == "raise":
            raises += 1
    return tuple(out)


def _chosen_label(result: dict[str, Any]) -> str:
    answer = result["answer"]
    if answer["custom_to"] is not None:
        return custom_label(answer["action"]["kind"], int(answer["action"]["to"]))
    return option_label(answer["chosen_label"])


def _opt_pct(x: float | None, digits: int) -> str | None:
    return None if x is None else pct(x, digits)


def _fold_relation(fold_freq: float, required: float) -> str:
    """``"more than"`` / ``"less than"`` when the shown strings (fold frequency with no decimal,
    the requirement with one) agree with the exact comparison, else ``"close to"``."""
    shown = Decimal(to_fixed(fold_freq * 100, 0)) - Decimal(to_fixed(required * 100, 1))
    if fold_freq >= required and shown > 0:
        return "more than"
    if fold_freq < required and shown < 0:
        return "less than"
    return "close to"


def _option(o: dict[str, Any], chosen_label: str, pot_chips: int) -> OptionFact:
    aggressive = o["kind"] in ("bet", "raise")
    required = o["required_fold_equity"] if aggressive else None
    folds = o["fold_freq"]
    compare = required is not None and folds is not None
    return OptionFact(
        label=chosen_label if o["is_chosen"] else option_label(o["label"]),
        kind=o["kind"],
        ev=ev_bb(o["ev_bb"]),
        fold_freq=_opt_pct(o["fold_freq"], 0),
        equity_vs_continue=_opt_pct(o["equity_vs_continue"], 1),
        never_continues=aggressive
        and o["equity_vs_continue"] is None
        and o["ahead_vs_continue"] is None,
        is_best=bool(o["is_best"]),
        is_chosen=bool(o["is_chosen"]),
        required_fold_equity=_opt_pct(required, 1),
        required_formula=None
        if required is None
        else _fraction_formula(int(o["put"]), pot_chips, required),
        folds_pay=folds >= required if compare else None,
        fold_relation=_fold_relation(folds, required) if compare else None,
    )


def _fraction_formula(put: int, pot: int, api: float) -> str | None:
    """``"put / (pot + put)"`` in bb when it reproduces ``api`` within ``FRACTION_TOL``."""
    if pot + put <= 0 or abs(put / (pot + put) - api) >= FRACTION_TOL:
        return None
    return f"{bb(put)} / ({bb(pot)} + {bb(put)})"


def _loss_case(loss_bb: float, verdict: str) -> LossCase:
    """``verdictLine``'s three cases."""
    if loss_bb < EV_EPSILON:
        return "top"
    return "close" if verdict in ("best", "fine") else "lost"


def build_facts(result: dict[str, Any], puzzle: Puzzle, log: list[dict[str, Any]]) -> Facts:
    """Every number the explanation of ``result`` may use, formatted by code.

    ``log`` is ``views.action_log(puzzle.spot)`` (passed in: ``views`` imports this package).
    """
    sp = puzzle.spot
    s = sp.state
    grade = result["grade"]
    raw_options = result["options"]
    chosen_label = _chosen_label(result)
    pot_chips = int(total_pot(s))
    options = tuple(_option(o, chosen_label, pot_chips) for o in raw_options)
    to_call_chips = int(amount_to_call(s))

    board = [card(c) for c in _board_strs(puzzle)]
    flop = " ".join(board[:3]) if s.street >= Street.FLOP else None
    turn = board[3] if s.street >= Street.TURN else None
    river = board[4] if s.street >= Street.RIVER else None

    pot_odds = grade["pot_odds"]
    call = next((o for o in raw_options if o["kind"] == "call"), None)
    po_formula = None
    beats = None
    if pot_odds is not None and call is not None:
        po_formula = _fraction_formula(int(call["put"]), pot_chips, pot_odds)
        beats = grade["equity"] >= pot_odds

    aggressive = [o for o in raw_options if o["kind"] in ("bet", "raise")]
    best_bet = None
    if aggressive:
        top = max(range(len(aggressive)), key=lambda i: (aggressive[i]["ev_bb"], -i))
        best_bet = _option(aggressive[top], chosen_label, pot_chips)
    best = next(o for o in options if o.is_best)

    cats = result["categories"] or []
    order = sorted(range(len(cats)), key=lambda i: (-cats[i]["share"], i))[:2]
    categories = tuple(
        CategoryFact(cats[i]["name"], pct(cats[i]["share"], 1), pct(cats[i]["equity"], 0))
        for i in order
    )

    prof = result["reveal"]["profile"]
    loss_bb = float(grade["ev_loss_bb"])
    return Facts(
        street=STREET_KEYS[s.street],
        hero_position=_position(puzzle, sp.hero_seat),
        villain_position=_position(puzzle, 1 - sp.hero_seat),
        hero_cards=cards(_hero_strs(puzzle)),
        flop=flop,
        turn=turn,
        river=river,
        actions=_actions(log),
        profile_label=prof["label"],
        profile_description=prof["description"],
        pot=bb(pot_chips),
        to_call=bb(to_call_chips) if call is not None else None,
        facing_bet=call is not None,
        chosen_label=chosen_label,
        best_label=best.label,
        verdict=VERDICT_WORDS[grade["verdict"]],
        loss_case=_loss_case(loss_bb, grade["verdict"]),
        ev_loss=ev_bb(loss_bb),
        best_is_chosen=best.is_chosen,
        equity=pct(grade["equity"], 1),
        ahead_now=_opt_pct(grade["ahead_now"], 1),
        pot_odds=_opt_pct(pot_odds, 1),
        pot_odds_formula=po_formula,
        call_amount=None if call is None else bb(int(call["put"])),
        equity_beats_pot_odds=beats,
        options=options,
        check_best=best.kind == "check",
        best_bet=best_bet,
        categories=categories,
        range_steps=tuple(bb_label(st["label"]) for st in result["range_steps"][1:]),
    )
