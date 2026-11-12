"""The template explanation: headline, the hand, the verdict and Villain, written from ``Facts``.

Every number in the text is a ``Facts`` string (so the template passes the guardrail against
its own facts). It talks about Villain's range and the EV of the options, never the sampled
run-out, Villain's cards or who won.
"""

from __future__ import annotations

from typing import Any

from poker_trainer.explain.facts import ActionFact, Facts, OptionFact, build_facts
from poker_trainer.puzzle.model import Puzzle

GRADED_ON_RANGE = "The range in the Range tab is the range this puzzle was graded on."

_GERUNDS = {
    "Fold": "folding",
    "Call": "calling",
    "Check": "checking",
    "Bet": "betting",
    "Raise": "raising",
}
_PLACES = {"BTN": "on the button", "BB": "in the big blind"}


def _gerund(label: str) -> str:
    """``"Bet 33%"`` -> ``"betting 33%"``, ``"All-in"`` -> ``"going all-in"``."""
    if label == "All-in":
        return "going all-in"
    first, _, rest = label.partition(" ")
    verb = _GERUNDS.get(first)
    if verb is None:
        return label
    return f"{verb} {rest}" if rest else verb


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _who(a: ActionFact) -> str:
    return "you" if a.actor == "hero" else "Villain"


def _street_actions(f: Facts, street: str) -> str:
    return _join([f"{_who(a)} {a.text}" for a in f.actions if a.street == street])


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def headline(f: Facts) -> str:
    """``verdictLine``'s three cases, as a sentence."""
    if f.loss_case == "top":
        return f"{f.chosen_label} was the top play, and you found it."
    if f.loss_case == "close":
        return f"{f.chosen_label} was close: within {f.ev_loss} of the top play, {f.best_label}."
    return (
        f"{f.best_label} was the top play; {_gerund(f.chosen_label)} loses {f.ev_loss} "
        "against Villain's range."
    )


def hand_paragraphs(f: Facts) -> list[str]:
    opening = (
        f"You held {f.hero_cards} {_PLACES[f.hero_position]}, against Villain, "
        f"a {f.profile_label} player, {_PLACES[f.villain_position]}."
    )
    pre = _street_actions(f, "preflop")
    if pre:
        opening += f" Pre-flop, {pre}."
    paragraphs = [opening]

    later = []
    boards = (
        ("flop", f.flop, "The flop came {}"),
        ("turn", f.turn, "The turn was the {}"),
        ("river", f.river, "The river was the {}"),
    )
    for street, board, intro in boards:
        if board is None:
            continue
        acts = _street_actions(f, street)
        later.append(intro.format(board) + (f": {acts}." if acts else "."))
    if later:
        paragraphs.append(" ".join(later))

    if f.facing_bet:
        decision = f"You faced {f.to_call} more to call, with {f.pot} in the pot."
    else:
        decision = f"It was your turn to act with {f.pot} in the pot."
    paragraphs[-1] += " " + decision
    return paragraphs


def _choice(f: Facts) -> str:
    chosen, best = f.chosen, f.best
    if f.loss_case == "top":
        # a custom size can match or beat the listed top play without being it
        top = (
            "the top play"
            if f.best_is_chosen
            else f"which matched or beat the top listed play ({f.best_label})"
        )
        return (
            f"You chose {f.chosen_label} (EV {chosen.ev}), {top} against Villain's range. "
            f"Verdict: {f.verdict}."
        )
    verdict = (
        f"That is close to the top play, so the verdict is {f.verdict}."
        if f.loss_case == "close"
        else f"Verdict: {f.verdict}."
    )
    return (
        f"You chose {f.chosen_label} (EV {chosen.ev}). The top play was {f.best_label} "
        f"(EV {best.ev}), so your choice gives up {f.ev_loss} against Villain's range. {verdict}"
    )


def _equity(f: Facts) -> str:
    text = f"Your equity against Villain's whole range is {f.equity}."
    if f.pot_odds is not None and f.call_amount is not None:
        needs = f.pot_odds if f.pot_odds_formula is None else f"{f.pot_odds_formula} = {f.pot_odds}"
        outcome = (
            "so calling beats folding" if f.equity_beats_pot_odds else "so folding beats calling"
        )
        side = "above" if f.equity_beats_pot_odds else "below"
        text += (
            f" Calling {f.call_amount} into a pot of {f.pot} needs {needs} equity; "
            f"{f.equity} is {side} that, {outcome}."
        )
    if f.check_best and f.best_bet is not None:
        text += (
            f" Checking (EV {f.best.ev}) does better than the best bet, "
            f"{f.best_bet.label} (EV {f.best_bet.ev})."
        )
    return text


def _aggressive_line(f: Facts, o: OptionFact) -> str:
    if o.never_continues:
        text = f"{o.label}: Villain always folds to it, so it wins the pot uncontested."
    else:
        parts = []
        if o.fold_freq is not None:
            parts.append(f"Villain folds {o.fold_freq} of the time")
        if o.equity_vs_continue is not None:
            parts.append(f"you have {o.equity_vs_continue} equity against the hands that continue")
        text = f"{o.label}: {_join(parts)}." if parts else ""
    if o.is_chosen and f.bluff_required is not None:
        word = f.chosen.kind
        formula = "" if f.bluff_formula is None else f" ({f.bluff_formula})"
        text += (
            f" To profit on folds alone, a {word} this size needs {f.bluff_required} "
            f"folds{formula}."
        )
    return text.strip()


def _aggression(f: Facts) -> str | None:
    shown = [o for o in (f.best, f.chosen) if o.aggressive]
    lines = []
    for o in dict.fromkeys(shown):  # best first; once when best is chosen
        line = _aggressive_line(f, o)
        if line:
            lines.append(line)
    return " ".join(lines) or None


def _range(f: Facts) -> str | None:
    parts = []
    if f.ahead_now is not None:
        parts.append(f"Right now you are ahead of {f.ahead_now} of Villain's range.")
    cats = [f"{c.name} ({c.share} of it; your equity {c.equity})" for c in f.categories]
    if len(cats) == 1:
        parts.append(f"The largest part of the range is {cats[0]}.")
    elif cats:
        parts.append(f"The largest parts of the range are {_join(cats)}.")
    return " ".join(parts) or None


def verdict_paragraphs(f: Facts) -> list[str]:
    out = [_choice(f), _equity(f)]
    for extra in (_aggression(f), _range(f)):
        if extra is not None:
            out.append(extra)
    return out


def villain_paragraphs(f: Facts) -> list[str]:
    out = [f"Villain is a {f.profile_label} player. {f.profile_description}"]
    if f.range_steps:
        out.append(f"Villain's range narrowed with each action: {'; '.join(f.range_steps)}.")
    else:
        out.append("Villain had not acted yet, so the range is every hand Villain can hold.")
    out.append(GRADED_ON_RANGE)
    return out


def render(f: Facts) -> dict[str, Any]:
    """The template ``Explanation`` (JSON-safe) for ``f``."""
    return {
        "source": "template",
        "headline": headline(f),
        "sections": [
            {"id": "hand", "title": "The hand", "paragraphs": hand_paragraphs(f)},
            {"id": "verdict", "title": "The verdict", "paragraphs": verdict_paragraphs(f)},
            {"id": "villain", "title": "Villain", "paragraphs": villain_paragraphs(f)},
        ],
        "model": None,
        "fallback": None,
    }


def explain(result: dict[str, Any], puzzle: Puzzle, log: list[dict[str, Any]]) -> dict[str, Any]:
    """The template explanation of a result dict (``views.attempt_result``'s, without
    ``explanation``); ``log`` is ``views.action_log(puzzle.spot)``. Pure: no database, no
    network."""
    return render(build_facts(result, puzzle, log))


def text_of(explanation: dict[str, Any]) -> str:
    """Every string of an explanation, one per line (for checks and tests)."""
    lines = [explanation["headline"]]
    for s in explanation["sections"]:
        lines.append(s["title"])
        lines.extend(s["paragraphs"])
    return "\n".join(lines)
