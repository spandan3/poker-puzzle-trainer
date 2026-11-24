"""Hero's legal options for a decision, sized with the shared Villain sizing helpers."""

from __future__ import annotations

from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Legal,
    Street,
    legal_actions,
)
from poker_trainer.puzzle.model import Option
from poker_trainer.villain import preflop5
from poker_trainer.villain.strategy import UnsupportedSpot, allin, bet_to, raise_to

_BET_FRACS = ((0.33, "bet 33%"), (0.5, "bet 50%"), (0.75, "bet 75%"), (1.0, "bet 100%"))
_RAISE_MULTS = ((2.5, "raise 2.5x"), (3.0, "raise 3x"))


def _merge(s: HandState, entries: list[tuple[str, Action]]) -> tuple[Option, ...]:
    """Merge options resolving to the same Action; "all-in" wins when ``to == max_to``."""
    lg = legal_actions(s)
    merged: dict[Action, str] = {}
    for label, act in entries:
        is_allin = act.kind in (ActionKind.BET, ActionKind.RAISE) and act.to == lg.max_to
        if act not in merged:
            merged[act] = "all-in" if is_allin else label
    return tuple(Option(label, act) for act, label in merged.items())


def hero_options(s: HandState) -> tuple[Option, ...]:
    if s.to_act is None:
        raise ValueError("no player to act")
    lg = legal_actions(s)
    me = s.to_act
    fold = Action(me, ActionKind.FOLD, s.street)
    check = Action(me, ActionKind.CHECK, s.street)
    call = Action(me, ActionKind.CALL, s.street, s.street_bets[me] + lg.call)
    entries: list[tuple[str, Action]] = []

    if s.street == Street.PREFLOP and len(s.stacks) != 2:
        return _merge(s, _preflop_multiway(s, lg, fold, call))

    if s.street == Street.PREFLOP:
        acts = [a for a in s.history if a.street == Street.PREFLOP]
        if any(a.kind != ActionKind.RAISE for a in acts):
            raise UnsupportedSpot("unsupported pre-flop line")
        if lg.call > 0 and lg.aggressive is None:  # facing a jam
            entries = [("fold", fold), ("call", call)]
        elif not acts and me == s.button:
            entries = [("fold", fold)]
            entries += [(lab, raise_to(s, m)) for m, lab in _RAISE_MULTS]
            entries.append(("all-in", allin(s)))
        elif len(acts) == 1 and me != s.button:
            entries = [("fold", fold), ("call", call)]
            entries += [(lab, raise_to(s, m)) for m, lab in _RAISE_MULTS]
            entries.append(("all-in", allin(s)))
        elif len(acts) == 2 and me == s.button:
            entries = [("fold", fold), ("call", call), ("all-in", allin(s))]
        else:
            raise UnsupportedSpot("unsupported pre-flop spot")
        return _merge(s, entries)

    if lg.call > 0:
        entries = [("fold", fold), ("call", call)]
        if lg.aggressive == ActionKind.RAISE:
            entries += [(lab, raise_to(s, m)) for m, lab in _RAISE_MULTS]
    else:
        entries = [("check", check)]
        if lg.aggressive == ActionKind.BET:
            entries += [(lab, bet_to(s, f)) for f, lab in _BET_FRACS]
    if lg.aggressive is not None:
        entries.append(("all-in", allin(s)))
    return _merge(s, entries)


def _preflop_multiway(
    s: HandState, lg: Legal, fold: Action, call: Action
) -> list[tuple[str, Action]]:
    """5-max pre-flop: the same tree as the bots (``villain/preflop5.py``), facing a jam first."""
    if len(s.stacks) != preflop5.SEATS:
        raise UnsupportedSpot(f"no pre-flop options for {len(s.stacks)} seats")
    if preflop5.has_limp(s):
        raise UnsupportedSpot("limped pots are not supported")
    if preflop5.facing_jam(s, lg):
        return [("fold", fold), ("call", call)]
    r = len(preflop5.preflop_raises(s))
    if r == 0:
        entries = [("fold", fold)]
    elif r == 1:
        entries = [("fold", fold), ("call", call)]
    else:
        return [("fold", fold), ("call", call), ("all-in", allin(s))]
    entries += [(lab, raise_to(s, m)) for m, lab in _RAISE_MULTS]
    entries.append(("all-in", allin(s)))
    return entries


def custom_action(s: HandState, to: int) -> Action:
    """A validated post-flop BET or RAISE to ``to`` chips; raises ``ValueError`` otherwise."""
    if s.street == Street.PREFLOP:
        raise ValueError("custom sizes are only allowed after the flop")
    if s.to_act is None:
        raise ValueError("no player to act")
    lg = legal_actions(s)
    if lg.aggressive is None or lg.min_to is None or lg.max_to is None:
        raise ValueError("betting/raising is not legal in this state")
    if not lg.min_to <= to <= lg.max_to:
        raise ValueError(f"size must be in [{lg.min_to}, {lg.max_to}]")
    return Action(s.to_act, lg.aggressive, s.street, int(to))
