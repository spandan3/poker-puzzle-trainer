"""One hand against the bots (heads-up or 5-max), stored as a record and rebuilt by replay.

A ``HandRecord`` holds what was fixed when the hand started (button, stacks, deck order,
the bots' seed) and every action so far; the game state is never stored. A bot's action at
history index ``i`` is ``sample_action`` seeded with ``f"{bot_seed}:{i}"`` heads-up, and with
``f"{bot_seed}:{seat}:{i}"`` for seat ``seat`` with three or more seats, so the bots' play is a
pure function of the record and a resumed hand continues exactly as it would have.

Deck convention with ``n`` seats: seat ``i`` holds ``deck[2i : 2i+2]`` and the board is
``deck[2n : 2n+5]``. Heads-up this is ``generate_spot``'s: Hero ``deck[0:2]``, bot
``deck[2:4]``, board ``deck[4:9]``. Hero is always seat 0.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from poker_trainer.game.settle import PotAward, settle, settle_pots
from poker_trainer.game.state import (
    Action,
    HandState,
    Street,
    apply,
    deal,
    is_terminal,
    live_seats,
    needs_board,
    new_hand,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.profiles import Profile
from poker_trainer.villain.strategy import sample_action

HERO_SEAT = 0  # fixed for the whole session; tuples indexed by seat start with Hero
BOT_SEAT = 1  # the bot's seat heads-up


@dataclass(frozen=True)
class HandRecord:
    button: int
    start_stacks: tuple[int, ...]  # one per seat, before the blinds; n = len(start_stacks)
    deck: tuple[int, ...]
    bot_seed: int
    actions: tuple[Action, ...]
    abandoned: bool = False


@dataclass(frozen=True)
class HandOutcome:
    ended_by: Literal["fold", "showdown", "abandoned"]
    winner: Literal["hero", "villain", "split"]
    stacks: tuple[int, int]
    hero_delta: int


@dataclass(frozen=True)
class HandOutcome5:
    """How a hand with three or more seats ended.

    ``stacks`` are every seat's stacks after the hand (for an abandoned hand, the stacks the
    next hand starts from before the session rules). ``winner`` is the sign of Hero's delta.
    ``pots`` are the awards from ``settle_pots`` (empty when abandoned). ``shown`` is the bot
    seats whose cards are revealed at a showdown, clockwise from ``button+1``.
    """

    ended_by: Literal["fold", "showdown", "abandoned"]
    winner: Literal["hero", "villain", "split"]
    stacks: tuple[int, ...]
    hero_delta: int
    pots: tuple[PotAward, ...]
    shown: tuple[int, ...]


def num_seats(r: HandRecord) -> int:
    return len(r.start_stacks)


def hole(r: HandRecord, seat: int) -> tuple[int, int]:
    """Seat ``seat``'s hole cards: ``deck[2*seat : 2*seat+2]``."""
    if not 0 <= seat < num_seats(r):
        raise ValueError(f"seat {seat} is not at the table")
    return r.deck[2 * seat], r.deck[2 * seat + 1]


def holes(r: HandRecord) -> tuple[tuple[int, int], ...]:
    return tuple(hole(r, i) for i in range(num_seats(r)))


def hero_cards(r: HandRecord) -> tuple[int, int]:
    return r.deck[0], r.deck[1]


def bot_cards(r: HandRecord) -> tuple[int, int]:
    """The heads-up bot's cards (seat 1)."""
    return r.deck[2], r.deck[3]


def _deal_board(s: HandState, deck: tuple[int, ...]) -> HandState:
    """Deal every street whose betting is complete, including the run-out after an all-in."""
    base = 2 * len(s.stacks)  # the board follows every seat's hole cards
    while needs_board(s):
        n = 3 if s.street == Street.PREFLOP else 1
        k = len(s.board)
        s = deal(s, deck[base + k : base + k + n])
    return s


def replay(r: HandRecord) -> HandState:
    """The hand's state after every recorded action, with the board dealt so far."""
    s = _deal_board(new_hand(r.button, r.start_stacks), r.deck)
    for a in r.actions:
        s = _deal_board(apply(s, a), r.deck)
    return s


def board(r: HandRecord) -> tuple[int, ...]:
    """The board cards dealt so far."""
    return replay(r).board


def _bot_rng(r: HandRecord, seat: int, index: int) -> random.Random:
    if num_seats(r) == 2:
        return random.Random(f"{r.bot_seed}:{index}")  # heads-up: unchanged since M10
    return random.Random(f"{r.bot_seed}:{seat}:{index}")


def _check_profiles(r: HandRecord, profiles: Mapping[int, Profile]) -> None:
    missing = [i for i in range(1, num_seats(r)) if i not in profiles]
    if missing:
        raise ValueError(f"no profile for bot seats {missing}")


def _advance_state(r: HandRecord, s: HandState, profiles: Mapping[int, Profile]) -> HandRecord:
    actions = list(r.actions)
    while not is_terminal(s) and s.to_act is not None and s.to_act != HERO_SEAT:
        seat = s.to_act
        rng = _bot_rng(r, seat, len(s.history))
        a = sample_action(profiles[seat], s, hole(r, seat), rng)
        actions.append(a)
        s = _deal_board(apply(s, a), r.deck)
    return replace(r, actions=tuple(actions))


def advance_seats(r: HandRecord, profiles: Mapping[int, Profile]) -> HandRecord:
    """Append the bots' actions until Hero is to act or the hand is over.

    ``profiles[seat]`` is the profile of bot seat ``seat`` (every seat but Hero's). Once Hero
    has folded the bots play the hand out. A record where Hero is to act, or a finished hand,
    comes back unchanged, so calling it again is harmless. Raises ``ValueError`` for an
    abandoned hand or a missing profile.
    """
    if r.abandoned:
        raise ValueError("the hand was abandoned")
    _check_profiles(r, profiles)
    return _advance_state(r, replay(r), profiles)


def advance(r: HandRecord, profile: Profile) -> HandRecord:
    """Heads-up ``advance_seats``: the bot in seat 1 plays ``profile``."""
    return advance_seats(r, {BOT_SEAT: profile})


def _is_on_menu(s: HandState, action: Action) -> bool:
    if any(o.action == action for o in hero_options(s)):
        return True
    if s.street == Street.PREFLOP:
        return False
    try:
        return custom_action(s, action.to) == action
    except ValueError:
        return False


def hero_act_seats(r: HandRecord, profiles: Mapping[int, Profile], action: Action) -> HandRecord:
    """Apply Hero's ``action`` (an option or a legal post-flop size), then let the bots act.

    After a Hero fold the bots play the hand to its end. Raises ``ValueError`` when the hand
    is over or abandoned, when it is not Hero's turn, when a bot seat has no profile, or when
    ``action`` is neither on Hero's menu nor a legal post-flop custom size.
    """
    if r.abandoned:
        raise ValueError("the hand was abandoned")
    _check_profiles(r, profiles)
    s = replay(r)
    if is_terminal(s):
        raise ValueError("the hand is over")
    if s.to_act != HERO_SEAT:
        raise ValueError("it is not Hero's turn")
    if not _is_on_menu(s, action):
        raise ValueError(f"not an option for Hero: {action}")
    r = replace(r, actions=(*r.actions, action))
    return _advance_state(r, _deal_board(apply(s, action), r.deck), profiles)


def hero_act(r: HandRecord, profile: Profile, action: Action) -> HandRecord:
    """Heads-up ``hero_act_seats``: the bot in seat 1 plays ``profile``."""
    return hero_act_seats(r, {BOT_SEAT: profile}, action)


def abandon(r: HandRecord) -> HandRecord:
    """Mark a running hand abandoned: Hero keeps the chips behind, the bots take the rest.

    Heads-up the bot takes everything else; with more seats see ``outcome5``.

    An already abandoned record comes back unchanged; a finished hand raises ``ValueError``.
    """
    if r.abandoned:
        return r
    if is_terminal(replay(r)):
        raise ValueError("the hand is over")
    return replace(r, abandoned=True)


def outcome(r: HandRecord) -> HandOutcome | None:
    """How the heads-up hand ended, or None while it is running (``outcome5`` for more seats)."""
    if num_seats(r) != 2:
        raise ValueError("outcome is heads-up only; use outcome5")
    s = replay(r)
    start = r.start_stacks[HERO_SEAT]
    if r.abandoned:
        hero = s.stacks[HERO_SEAT]
        return HandOutcome("abandoned", "villain", (hero, s.total_chips - hero), hero - start)
    if not is_terminal(s):
        return None
    stacks = settle(s, (hero_cards(r), bot_cards(r)))
    delta = stacks[HERO_SEAT] - start
    if s.folded is not None:
        return HandOutcome("fold", "villain" if s.folded == HERO_SEAT else "hero", stacks, delta)
    # Both seats put in the same chips by showdown, so the sign of Hero's delta is the result.
    winner = "hero" if delta > 0 else "villain" if delta < 0 else "split"
    return HandOutcome("showdown", winner, stacks, delta)


def _winner(delta: int) -> Literal["hero", "villain", "split"]:
    return "hero" if delta > 0 else "villain" if delta < 0 else "split"


def _clockwise(seats: tuple[int, ...], button: int, n: int) -> tuple[int, ...]:
    """``seats`` in clockwise order starting from ``button+1`` (the button comes last)."""
    return tuple(sorted(seats, key=lambda i: (i - button - 1) % n))


def _abandoned_stacks(r: HandRecord, s: HandState) -> tuple[int, ...]:
    """Stacks after an abandoned hand with three or more seats.

    Hero keeps the chips behind and loses what it committed. Each bot gets back its stack
    from before the hand, and Hero's committed chips are split evenly among the bots still
    live, odd chips one at a time clockwise from ``button+1``. Chips are conserved.
    """
    n = num_seats(r)
    committed = r.start_stacks[HERO_SEAT] - s.stacks[HERO_SEAT]
    bots = _clockwise(tuple(i for i in live_seats(s) if i != HERO_SEAT), r.button, n)
    stacks = list(r.start_stacks)
    stacks[HERO_SEAT] = s.stacks[HERO_SEAT]
    share, odd = divmod(committed, len(bots))
    for k, seat in enumerate(bots):
        stacks[seat] += share + (1 if k < odd else 0)
    return tuple(stacks)


def outcome5(r: HandRecord) -> HandOutcome5 | None:
    """How a hand with three or more seats ended, or None while it is running.

    Pots come from ``settle_pots`` with the record's start stacks. ``winner`` follows the sign
    of Hero's delta, so a Hero who folded with nothing in the pot reads "split".
    """
    n = num_seats(r)
    if n < 3:
        raise ValueError("outcome5 needs three or more seats; use outcome")
    s = replay(r)
    start = r.start_stacks[HERO_SEAT]
    if r.abandoned:
        stacks = _abandoned_stacks(r, s)
        delta = stacks[HERO_SEAT] - start
        return HandOutcome5("abandoned", _winner(delta), stacks, delta, (), ())
    if not is_terminal(s):
        return None
    st = settle_pots(s, holes(r), r.start_stacks)
    delta = st.stacks[HERO_SEAT] - start
    if s.folded is not None:
        return HandOutcome5("fold", _winner(delta), st.stacks, delta, st.pots, ())
    shown = _clockwise(tuple(i for i in live_seats(s) if i != HERO_SEAT), r.button, n)
    return HandOutcome5("showdown", _winner(delta), st.stacks, delta, st.pots, shown)
