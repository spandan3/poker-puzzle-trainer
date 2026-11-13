"""Grade a user's Answer against a Puzzle: verdict, EV loss, scores, intent and bluff check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from poker_trainer.game.state import Action, ActionKind, Street, total_pot
from poker_trainer.puzzle.model import OptionEV, Puzzle, best_margin, load_config, verdict_pot
from poker_trainer.puzzle.options import custom_action
from poker_trainer.puzzle.solve import Respond, evaluate_action, villain_respond
from poker_trainer.villain.profiles import load_profile

Verdict = Literal["best", "fine", "mistake", "blunder"]
Score = Literal["great", "good", "off"]
Intent = Literal["value", "bluff", "semi_bluff"]

_EPS = 1e-9
_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)
_INTENT_TEXT = {
    ActionKind.BET: {"value": "a value bet", "bluff": "a bluff", "semi_bluff": "a semi-bluff"},
    ActionKind.RAISE: {
        "value": "a value raise",
        "bluff": "a bluff raise",
        "semi_bluff": "a semi-bluff raise",
    },
}
_INTENT_REASON = {
    "value": "worse hands continue",
    "bluff": "only better hands continue",
    "semi_bluff": "better hands usually continue, though you still have real equity",
}
_NEVER_CONTINUES_REASON = {
    "bluff": (
        "Villain always folds here, so this bet wins the pot uncontested; "
        "it's a bluff with fold equity only"
    ),
    "value": (
        "Villain always folds here, so this bet wins the pot uncontested, "
        "though your hand would also be ahead if called"
    ),
}


def intent_text(intent: Intent, kind: ActionKind) -> str:
    """Plain-English name of ``intent`` for a bet or raise ("a value raise", "a bluff")."""
    return _INTENT_TEXT[kind][intent]


def _intent_flag(chosen: Intent, truth: Intent, kind: ActionKind, never: bool) -> str:
    said = intent_text(chosen, kind)
    if never:  # the reason already names the truth
        reason = _NEVER_CONTINUES_REASON[truth]
        if kind == ActionKind.RAISE:
            reason = reason.replace("this bet", "this raise")
        return f"You labelled this {said}, but {reason}."
    return f"You labelled this {said}, but {_INTENT_REASON[truth]}, so it's {intent_text(truth, kind)}."


@dataclass(frozen=True)
class Answer:
    action: Action
    equity_guess: float
    range_read_guess: float | None = None
    intent: Intent | None = None


@dataclass(frozen=True, eq=False)
class Grade:
    verdict: Verdict
    ev_loss_chips: float
    chosen: OptionEV
    best: OptionEV
    equity_error: float
    equity_score: Score
    range_read_error: float | None
    range_read_score: Score | None
    intent_truth: str | None
    intent_flag: str | None
    bluff_check: tuple[float, float] | None
    best_is_chosen: bool  # the chosen action is the best play (a listed best or a custom size)

    @property
    def ev_loss_bb(self) -> float:
        return self.ev_loss_chips / 2


def _verdict(loss: float, pot: int) -> Verdict:
    """Bands are relative to ``max(pot, min_pot)``, so tiny pots don't make every loss big."""
    v = load_config().verdict
    if loss <= best_margin(pot, v) + _EPS:
        return "best"
    floor_pot = verdict_pot(pot, v)
    if loss <= v.fine_pot * floor_pot + _EPS:
        return "fine"
    if loss <= v.mistake_pot * floor_pot + _EPS:
        return "mistake"
    return "blunder"


def _score(error: float) -> Score:
    sc = load_config().score
    if error <= sc.great + _EPS:
        return "great"
    if error <= sc.good + _EPS:
        return "good"
    return "off"


def _intent_truth(chosen: OptionEV, street: Street, overall_equity: float) -> Intent:
    ahead, eq = chosen.ahead_vs_continue, chosen.equity_vs_continue
    if ahead is None and eq is None:  # Villain never continues
        return "bluff" if overall_equity < 0.5 else "value"
    if street == Street.PREFLOP:  # all-in equity decides; no semi-bluffs pre-flop
        if eq is None:
            return "bluff" if overall_equity < 0.5 else "value"
        return "value" if eq >= 0.5 - _EPS else "bluff"
    if (ahead if ahead is not None else eq) >= 0.5 - _EPS:  # type: ignore[operator]
        return "value"
    if (
        street < Street.RIVER
        and eq is not None
        and eq >= load_config().intent.semi_bluff_equity - _EPS
    ):
        return "semi_bluff"
    return "bluff"


def _resolve(p: Puzzle, action: Action, respond: Respond | None) -> OptionEV:
    for o in p.solution.options:
        if o.option.action == action:
            return o
    s = p.spot.state
    if s.street == Street.PREFLOP:
        raise ValueError("custom sizes are only allowed after the flop")
    if action.kind not in _AGGRESSIVE:
        raise ValueError("a custom action must be a bet or raise")
    legal = custom_action(s, action.to)
    if legal != action:
        raise ValueError("illegal custom action")
    if respond is None:
        profile = load_profile(p.spot.profile)
        if profile.version != p.spot.profile_version:
            raise ValueError("profile changed since this puzzle was generated")
        respond = villain_respond(profile)
    return evaluate_action(
        s,
        p.spot.hero,
        p.spot.range,
        p.solution.combo_equity,
        legal,
        respond,
        samples=load_config().samples,
    )


def grade(p: Puzzle, a: Answer, *, respond: Respond | None = None) -> Grade:
    """Grade ``a`` against ``p``.

    The profile-version check runs only for custom sizes with the default ``respond``;
    callers that inject ``respond`` own that check.

    A custom size whose EV beats the best listed option by more than ``_EPS`` becomes the best
    play itself (loss 0); a tie keeps the listed option as best.
    """
    sol = p.solution
    s = p.spot.state
    chosen = _resolve(p, a.action, respond)
    best = sol.options[sol.best]
    custom = all(o.option.action != a.action for o in sol.options)
    if custom and chosen.ev_chips > best.ev_chips + _EPS:
        best = chosen
    loss = max(0.0, best.ev_chips - chosen.ev_chips)

    equity_error = abs(a.equity_guess - sol.equity)

    rr_error: float | None = None
    rr_score: Score | None = None
    if s.street != Street.RIVER and a.range_read_guess is not None and sol.ahead_now is not None:
        rr_error = float(abs(a.range_read_guess - sol.ahead_now))
        rr_score = _score(rr_error)

    truth: Intent | None = None
    flag: str | None = None
    bluff: tuple[float, float] | None = None
    if a.action.kind in _AGGRESSIVE:
        truth = _intent_truth(chosen, s.street, sol.equity)
        if a.intent is not None and a.intent != truth:
            never = chosen.ahead_vs_continue is None and chosen.equity_vs_continue is None
            flag = _intent_flag(a.intent, truth, a.action.kind, never)
        if chosen.required_fold_equity is not None and chosen.fold_freq is not None:
            bluff = (chosen.required_fold_equity, chosen.fold_freq)

    return Grade(
        verdict=_verdict(loss, total_pot(s)),
        ev_loss_chips=float(loss),
        chosen=chosen,
        best=best,
        equity_error=float(equity_error),
        equity_score=_score(equity_error),
        range_read_error=rr_error,
        range_read_score=rr_score,
        intent_truth=truth,
        intent_flag=flag,
        bluff_check=bluff,
        best_is_chosen=best.option.action == chosen.option.action,
    )
