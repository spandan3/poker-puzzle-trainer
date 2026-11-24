"""No-limit hold'em hand state for 2 to 6 seats: blinds, betting rounds, legal actions.

Seats are ``0 .. n-1`` with ``n = len(stacks)``; clockwise is increasing seat index mod n.

- Heads-up (two seats) the button is the small blind; it acts first pre-flop and the other seat
  acts first on every later street.
- With three or more seats the small blind is ``button+1``, the big blind ``button+2``, and
  ``button+3`` acts first pre-flop. Post-flop the first live seat clockwise from the button acts
  first.

A seat may bet at most what the deepest other live seat that can still act could match, so
heads-up no chips are ever left uncalled. Multiway a seat can be all-in for less than others,
which is what makes side pots (``game/settle.py``). Folded seats are read from ``history``;
``folded`` is None until the hand ends by folds, then the seat whose fold ended it.
``sum(stacks) + pot + sum(street_bets) == total_chips`` holds in every state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum

from poker_trainer.engine.cards import ensure_distinct

SB = 1
BB = 2
START_STACK = 200
MAX_SEATS = 6


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
    stacks: tuple[int, ...]
    street_bets: tuple[int, ...]
    pot: int
    street: Street
    board: tuple[int, ...]
    to_act: int | None
    history: tuple[Action, ...]
    last_raise: int
    folded: int | None
    total_chips: int


_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)

# Position names clockwise from the button, by table size (3, 4 and 6 seats: tests only).
_POSITIONS: dict[int, tuple[str, ...]] = {
    3: ("BTN", "SB", "BB"),
    4: ("BTN", "SB", "BB", "CO"),
    5: ("BTN", "SB", "BB", "UTG", "CO"),
    6: ("BTN", "SB", "BB", "UTG", "HJ", "CO"),
}


def _illegal(a: Action, why: str) -> ValueError:
    return ValueError(f"illegal action: {a} ({why})")


def _set(values: tuple[int, ...], seat: int, value: int) -> tuple[int, ...]:
    return (*values[:seat], value, *values[seat + 1 :])


def num_seats(s: HandState) -> int:
    return len(s.stacks)


def folded_seats(s: HandState) -> frozenset[int]:
    """Seats that have folded this hand (read from the history)."""
    return frozenset(a.seat for a in s.history if a.kind == ActionKind.FOLD)


def live_seats(s: HandState) -> tuple[int, ...]:
    """Seats that have not folded, in seat order."""
    out = folded_seats(s)
    return tuple(i for i in range(len(s.stacks)) if i not in out)


def active_seats(s: HandState) -> tuple[int, ...]:
    """Live seats that are not all-in (they can still act), in seat order."""
    return tuple(i for i in live_seats(s) if s.stacks[i] > 0)


def _next_actor(s: HandState, start: int) -> int | None:
    """First seat clockwise from ``start`` (inclusive) that must act, or None if the round is over.

    A seat must act if it is live, not all-in, and either hasn't acted on this street (blinds
    are not actions) or is below the highest bet. With at most one such seat left, the round is
    over once it has matched: nobody could call a bet of its.
    """
    if s.folded is not None:
        return None
    n = len(s.stacks)
    active = active_seats(s)
    current = max(s.street_bets)
    if len(active) <= 1 and all(s.street_bets[i] >= current for i in active):
        return None
    acted = {a.seat for a in s.history if a.street == s.street}
    for k in range(n):
        seat = (start + k) % n
        if seat in active and (seat not in acted or s.street_bets[seat] < current):
            return seat
    return None


def new_hand(button: int, stacks: tuple[int, ...] = (START_STACK, START_STACK)) -> HandState:
    n = len(stacks)
    if not 2 <= n <= MAX_SEATS:
        raise ValueError(f"a hand needs 2 to {MAX_SEATS} seats, got {n}")
    if not 0 <= button < n:
        raise ValueError(f"button {button} is not a seat")
    posts = [0] * n
    if n == 2:
        bb_seat = 1 - button
        # Blinds are capped by the poster's stack and by what the opponent can ever match.
        posts[button] = min(SB, stacks[button], stacks[bb_seat])
        posts[bb_seat] = min(BB, stacks[bb_seat], stacks[button])
        first = button
    else:
        # Session rules keep every stack above the big blind, so no blind is posted all-in.
        if not all(x > BB for x in stacks):
            raise ValueError(f"every stack must exceed the big blind: {stacks}")
        posts[(button + 1) % n] = SB
        posts[(button + 2) % n] = BB
        first = (button + 3) % n
    s = HandState(
        button=button,
        stacks=tuple(x - p for x, p in zip(stacks, posts, strict=True)),
        street_bets=tuple(posts),
        pot=0,
        street=Street.PREFLOP,
        board=(),
        to_act=None,
        history=(),
        last_raise=BB,
        folded=None,
        total_chips=sum(stacks),
    )
    return replace(s, to_act=_next_actor(s, first))


def _can_reraise(s: HandState, seat: int) -> bool:
    """False if no full raise came after the seat's last action on this street.

    A seat that has not yet acted this street may always raise. A short all-in alone does not
    reopen raising for seats that have already acted. (A simplification of the TDA's cumulative
    rule; heads-up the two agree.)
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
    return not since or any(full_at[i] for i in since)


def legal_actions(s: HandState) -> Legal:
    if s.to_act is None:
        raise ValueError("no player to act")
    me = s.to_act
    mine = s.street_bets[me]
    current = max(s.street_bets)
    # What the deepest other seat that can still act could match.
    others = [s.stacks[i] + s.street_bets[i] for i in active_seats(s) if i != me]
    max_to = min(s.stacks[me] + mine, max(others, default=0))
    aggressive: ActionKind | None = None
    min_to = hi = None
    if max_to > current and _can_reraise(s, me):
        aggressive = ActionKind.BET if current == 0 else ActionKind.RAISE
        base = BB if current == 0 else current + s.last_raise
        min_to, hi = min(base, max_to), max_to
    call = min(max(current - mine, 0), s.stacks[me])
    return Legal(
        fold=call > 0,
        check=current <= mine,
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
        if len(live_seats(s)) == 2:
            folded = me  # this fold ends the hand
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
    return replace(ns, to_act=_next_actor(ns, (me + 1) % len(s.stacks)))


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
        street_bets=(0,) * len(s.stacks),
        street=Street(s.street + 1),
        board=(*s.board, *cards),
        last_raise=BB,
    )
    # Fewer than two seats able to bet: no betting, the board runs out.
    return replace(ns, to_act=_next_actor(ns, (ns.button + 1) % len(ns.stacks)))


def total_pot(s: HandState) -> int:
    return s.pot + sum(s.street_bets)


def amount_to_call(s: HandState) -> int:
    return 0 if s.to_act is None else legal_actions(s).call


def pot_odds(s: HandState) -> float:
    call = amount_to_call(s)
    return 0.0 if call == 0 else call / (total_pot(s) + call)


def position_name(s: HandState, seat: int) -> str:
    n = len(s.stacks)
    if n == 2:
        return "BTN" if seat == s.button else "BB"
    return _POSITIONS[n][(seat - s.button) % n]


def last_aggressor(s: HandState, street: Street) -> int | None:
    for a in reversed(s.history):
        if a.street == street and a.kind in _AGGRESSIVE:
            return a.seat
    return None
