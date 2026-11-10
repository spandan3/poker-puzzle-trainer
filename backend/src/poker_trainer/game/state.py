"""Heads-up no-limit hold'em hand state: blinds, betting rounds, legal actions.

Seats are 0 and 1. The button is the small blind; it acts first pre-flop and the
other seat acts first on every later street. Bets are capped at the effective stack
(the smaller of the two total stacks), so no chips are ever left uncalled and
``sum(stacks) + pot + sum(street_bets) == total_chips`` holds in every state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum

from poker_trainer.engine.cards import ensure_distinct

SB = 1
BB = 2
START_STACK = 200


class Street(IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3


class ActionKind(StrEnum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


@dataclass(frozen=True)
class Action:
    seat: int
    kind: ActionKind
    street: Street
    to: int = 0


@dataclass(frozen=True)
class Legal:
    fold: bool
    check: bool
    call: int
    aggressive: ActionKind | None
    min_to: int | None
    max_to: int | None


@dataclass(frozen=True)
class HandState:
    button: int
    stacks: tuple[int, int]
    street_bets: tuple[int, int]
    pot: int
    street: Street
    board: tuple[int, ...]
    to_act: int | None
    history: tuple[Action, ...]
    last_raise: int
    folded: int | None
    total_chips: int


_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)


def _illegal(a: Action, why: str) -> ValueError:
    return ValueError(f"illegal action: {a} ({why})")


def _set(pair: tuple[int, int], seat: int, value: int) -> tuple[int, int]:
    return (value, pair[1]) if seat == 0 else (pair[0], value)


def _next_actor(s: HandState, last_actor: int | None) -> int | None:
    """Seat to act next in the current betting round, or None if the round is over."""
    if s.folded is not None:
        return None
    b = s.street_bets
    if 0 in s.stacks:
        if b[0] == b[1]:
            return None
        lower = 0 if b[0] < b[1] else 1
        return lower if s.stacks[lower] > 0 else None
    if b[0] == b[1] and len({a.seat for a in s.history if a.street == s.street}) == 2:
        return None
    return s.button if last_actor is None else 1 - last_actor


def new_hand(button: int, stacks: tuple[int, int] = (START_STACK, START_STACK)) -> HandState:
    bb_seat = 1 - button
    # Blinds are capped by the poster's stack and by what the opponent can ever match.
    posts = [0, 0]
    posts[button] = min(SB, stacks[button], stacks[bb_seat])
    posts[bb_seat] = min(BB, stacks[bb_seat], stacks[button])
    s = HandState(
        button=button,
        stacks=(stacks[0] - posts[0], stacks[1] - posts[1]),
        street_bets=(posts[0], posts[1]),
        pot=0,
        street=Street.PREFLOP,
        board=(),
        to_act=None,
        history=(),
        last_raise=BB,
        folded=None,
        total_chips=stacks[0] + stacks[1],
    )
    return replace(s, to_act=_next_actor(s, None))


def _can_reraise(s: HandState, seat: int) -> bool:
    """False if the only aggression since seat's last action was a short all-in.

    A seat that has not yet acted this street may always raise.
    """
    acts = [a for a in s.history if a.street == s.street]
    own = [i for i, a in enumerate(acts) if a.seat == seat]
    if not own:
        return True
    # Replay the street, recording whether each bet/raise was a full raise.
    bet = BB if s.street == Street.PREFLOP else 0
    required = BB
    full_at: dict[int, bool] = {}
    for i, a in enumerate(acts):
        if a.kind in _AGGRESSIVE:
            size = a.to - bet
            full_at[i] = size >= required
            if full_at[i]:
                required = size
            bet = a.to
    since = [i for i in full_at if i > own[-1]]
    return not since or all(full_at[i] for i in since)


def legal_actions(s: HandState) -> Legal:
    if s.to_act is None:
        raise ValueError("no player to act")
    me = s.to_act
    mine, theirs = s.street_bets[me], s.street_bets[1 - me]
    current = max(s.street_bets)
    max_to = min(s.stacks[me] + mine, s.stacks[1 - me] + theirs)
    aggressive: ActionKind | None = None
    min_to = hi = None
    if max_to > current and _can_reraise(s, me):
        aggressive = ActionKind.BET if current == 0 else ActionKind.RAISE
        base = BB if current == 0 else current + s.last_raise
        min_to, hi = min(base, max_to), max_to
    call = min(max(theirs - mine, 0), s.stacks[me])
    return Legal(
        fold=call > 0,
        check=theirs <= mine,
        call=call,
        aggressive=aggressive,
        min_to=min_to,
        max_to=hi,
    )


def apply(s: HandState, a: Action) -> HandState:
    if s.to_act is None:
        raise _illegal(a, "no player to act")
    if a.seat != s.to_act:
        raise _illegal(a, "not this seat's turn")
    if a.street != s.street:
        raise _illegal(a, "wrong street")
    lg = legal_actions(s)
    me = a.seat
    mine = s.street_bets[me]
    stacks, bets, last_raise, folded = s.stacks, s.street_bets, s.last_raise, s.folded
    to = 0
    if a.kind == ActionKind.FOLD:
        if not lg.fold:
            raise _illegal(a, "nothing to call")
        if a.to != 0:
            raise _illegal(a, "fold must have to=0")
        folded = me
    elif a.kind == ActionKind.CHECK:
        if not lg.check:
            raise _illegal(a, "facing a bet")
        if a.to != 0:
            raise _illegal(a, "check must have to=0")
    elif a.kind == ActionKind.CALL:
        if lg.call <= 0:
            raise _illegal(a, "nothing to call")
        to = mine + lg.call
        if a.to != to:
            raise _illegal(a, f"call must have to={to}")
        stacks = _set(stacks, me, stacks[me] - lg.call)
        bets = _set(bets, me, to)
    else:
        if lg.aggressive != a.kind or lg.min_to is None or lg.max_to is None:
            raise _illegal(a, "bet/raise not allowed")
        if not lg.min_to <= a.to <= lg.max_to:
            raise _illegal(a, f"amount must be in [{lg.min_to}, {lg.max_to}]")
        to = a.to
        size = to - max(bets)
        if size >= (BB if max(bets) == 0 else s.last_raise):
            last_raise = size  # a short all-in leaves the raise size unchanged
        stacks = _set(stacks, me, stacks[me] - (to - mine))
        bets = _set(bets, me, to)
    ns = replace(
        s,
        stacks=stacks,
        street_bets=bets,
        history=(*s.history, Action(me, a.kind, a.street, to)),
        last_raise=last_raise,
        folded=folded,
    )
    return replace(ns, to_act=_next_actor(ns, me))


def is_terminal(s: HandState) -> bool:
    return s.folded is not None or (s.street == Street.RIVER and s.to_act is None)


def needs_board(s: HandState) -> bool:
    return s.folded is None and s.to_act is None and s.street < Street.RIVER


def deal(s: HandState, cards: tuple[int, ...]) -> HandState:
    if not needs_board(s):
        raise ValueError("illegal deal: betting round is not complete")
    want = 3 if s.street == Street.PREFLOP else 1
    if len(cards) != want:
        raise ValueError(f"expected {want} cards, got {len(cards)}")
    ensure_distinct(s.board, cards)
    ns = replace(
        s,
        pot=s.pot + sum(s.street_bets),
        street_bets=(0, 0),
        street=Street(s.street + 1),
        board=(*s.board, *cards),
        last_raise=BB,
    )
    return replace(ns, to_act=None if 0 in ns.stacks else 1 - ns.button)


def total_pot(s: HandState) -> int:
    return s.pot + sum(s.street_bets)


def amount_to_call(s: HandState) -> int:
    return 0 if s.to_act is None else legal_actions(s).call


def pot_odds(s: HandState) -> float:
    call = amount_to_call(s)
    return 0.0 if call == 0 else call / (total_pot(s) + call)


def position_name(s: HandState, seat: int) -> str:
    return "BTN" if seat == s.button else "BB"


def last_aggressor(s: HandState, street: Street) -> int | None:
    for a in reversed(s.history):
        if a.street == street and a.kind in _AGGRESSIVE:
            return a.seat
    return None
