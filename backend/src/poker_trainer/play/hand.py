"""One hand against the bots (heads-up or 5-max), stored as a record and rebuilt by replay.

A ``HandRecord`` holds what was fixed when the hand started (button, stacks, deck order,
the bots' seed) and every action so far; the game state is never stored. A bot's action at
history index ``i`` is ``sample_action`` seeded with ``f"{bot_seed}:{i}"`` heads-up, and with
``f"{bot_seed}:{seat}:{i}"`` for seat ``seat`` with three or more seats, so the bots' play is a
pure function of the record and a resumed hand continues exactly as it would have.

Deck convention with ``n`` seats: seat ``i`` holds ``deck[2i : 2i+2]`` and the board is
``deck[2n : 2n+5]``. Heads-up this is ``generate_spot``'s: Hero ``deck[0:2]``, bot
``deck[2:4]``, board ``deck[4:9]``. Hero is always seat 0.

With three or more seats each bot seat plays a ``SeatBot``: its profile and its slice of
``fivemax.json`` as they were when the seat sat down, so a stored hand replays identically even
after the data files change. Heads-up the bot plays a bare ``Profile`` (heads-up never reads
``fivemax.json``).
"""

from __future__ import annotations

import copy
import random
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from poker_trainer.game.settle import PotAward, settle, settle_pots
from poker_trainer.game.state import (
    Action,
    HandState,
    Street,
    apply,
    deal,
    folded_seats,
    is_terminal,
    live_seats,
    needs_board,
    new_hand,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.preflop5 import FiveMax, fivemax_from_snapshot, seat_snapshot
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, profile_data, profile_from_dict
from poker_trainer.villain.strategy import sample_action

HERO_SEAT = 0  # fixed for the whole session; tuples indexed by seat start with Hero
BOT_SEAT = 1  # the bot's seat heads-up


SEATBOT_KEYS = ("profile", "profile_data", "fivemax_data")


@dataclass(frozen=True)
class SeatBot:
    """One bot seat's snapshot: its profile and its slice of ``fivemax.json``.

    Build it with ``SeatBot.live(name)`` (the data files as they are now) or
    ``SeatBot.from_dict`` (a stored snapshot); ``to_dict`` gives the plain, JSON-safe dict
    ``{"profile": name, "profile_data": <profile file>, "fivemax_data": {"version",
    "bb_call_mult", "damping", "block"}}`` that ``from_dict`` reads back. ``fivemax`` holds only
    this profile's block. Two snapshots are equal when their dicts are.
    """

    profile: Profile = field(compare=False)
    fivemax: FiveMax = field(compare=False)
    data: Mapping[str, Any] = field(repr=False)

    @classmethod
    def live(cls, name: str) -> SeatBot:
        """A snapshot of profile ``name`` from the data files as they are now."""
        return cls.from_dict(
            {
                "profile": name,
                "profile_data": profile_data(name),
                "fivemax_data": seat_snapshot(name),
            }
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> SeatBot:
        """Rebuild a stored snapshot; every structural problem raises ``ValueError``."""
        if not isinstance(raw, Mapping) or set(raw) != set(SEATBOT_KEYS):
            got = sorted(raw) if isinstance(raw, Mapping) else type(raw).__name__
            raise ValueError(
                f"a seat snapshot needs exactly the keys {sorted(SEATBOT_KEYS)}, got {got}"
            )
        name = raw["profile"]
        if name not in PROFILE_NAMES:
            raise ValueError(f"unknown profile {name!r}; expected one of {PROFILE_NAMES}")
        data = copy.deepcopy(dict(raw))
        try:
            profile = profile_from_dict(name, data["profile_data"])
        except (KeyError, TypeError) as e:  # belt and braces: the loader raises ValueError
            raise ValueError(f"{name}: bad profile_data: {e!r}") from e
        return cls(profile, fivemax_from_snapshot(name, data["fivemax_data"]), data)

    def to_dict(self) -> dict[str, Any]:
        """The snapshot as a fresh plain dict (``from_dict`` reads it back)."""
        return copy.deepcopy(dict(self.data))


Bot = SeatBot | Profile  # internal: heads-up passes a bare Profile (live files)


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
    next hand starts from before the session rules). ``winner`` is "villain" when the hand was
    abandoned or Hero folded, and otherwise the sign of Hero's delta. ``pots`` are the awards
    from ``settle_pots`` (empty when abandoned). ``shown`` is the bot seats whose cards are
    revealed at a showdown, clockwise from ``button+1`` (the button last); Hero is never in it.
    ``hero_folded`` is True when Hero has a fold in the history (the bots may still have played
    on to a showdown).
    """

    ended_by: Literal["fold", "showdown", "abandoned"]
    winner: Literal["hero", "villain", "split"]
    stacks: tuple[int, ...]
    hero_delta: int
    pots: tuple[PotAward, ...]
    shown: tuple[int, ...]
    hero_folded: bool


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


def _check_bots(r: HandRecord, bots: Mapping[int, Bot]) -> None:
    """The bot seats must be exactly ``1 .. n-1``: no missing seat, no Hero, no extras."""
    want = set(range(1, num_seats(r)))
    missing = sorted(want - set(bots))
    if missing:
        raise ValueError(f"no profile for bot seats {missing}")
    extra = sorted(set(bots) - want)
    if extra:
        raise ValueError(f"not a bot seat at this table: {extra}")


def _check_seat_bots(r: HandRecord, bots: Mapping[int, SeatBot]) -> None:
    _check_bots(r, bots)
    bad = sorted(seat for seat, b in bots.items() if not isinstance(b, SeatBot))
    if bad:
        raise TypeError(f"bot seats {bad} need a SeatBot snapshot")


def _bot_action(bot: Bot, s: HandState, cards: tuple[int, int], rng: random.Random) -> Action:
    if isinstance(bot, SeatBot):
        return sample_action(bot.profile, s, cards, rng, fivemax=bot.fivemax)
    return sample_action(bot, s, cards, rng)  # heads-up: the live files


def _advance_state(r: HandRecord, s: HandState, bots: Mapping[int, Bot]) -> HandRecord:
    actions = list(r.actions)
    while not is_terminal(s) and s.to_act is not None and s.to_act != HERO_SEAT:
        seat = s.to_act
        rng = _bot_rng(r, seat, len(s.history))
        a = _bot_action(bots[seat], s, hole(r, seat), rng)
        actions.append(a)
        s = _deal_board(apply(s, a), r.deck)
    return replace(r, actions=tuple(actions))


def _advance(r: HandRecord, bots: Mapping[int, Bot]) -> HandRecord:
    if r.abandoned:
        raise ValueError("the hand was abandoned")
    return _advance_state(r, replay(r), bots)


def advance_seats(r: HandRecord, bots: Mapping[int, SeatBot]) -> HandRecord:
    """Append the bots' actions until Hero is to act or the hand is over.

    ``bots[seat]`` is bot seat ``seat``'s snapshot; the keys must be exactly ``1 .. n-1``. Once
    Hero has folded the bots play the hand out. A record where Hero is to act, or a finished
    hand, comes back unchanged, so calling it again is harmless. Raises ``ValueError`` for an
    abandoned hand or a missing or extra seat, ``TypeError`` for a seat without a ``SeatBot``.
    """
    _check_seat_bots(r, bots)
    return _advance(r, bots)


def advance(r: HandRecord, profile: Profile) -> HandRecord:
    """Heads-up: append the bot's (seat 1, ``profile``) actions until Hero is to act or the
    hand is over."""
    _check_bots(r, {BOT_SEAT: profile})
    return _advance(r, {BOT_SEAT: profile})


def _is_on_menu(s: HandState, action: Action) -> bool:
    if any(o.action == action for o in hero_options(s)):
        return True
    if s.street == Street.PREFLOP:
        return False
    try:
        return custom_action(s, action.to) == action
    except ValueError:
        return False


def _hero_act(r: HandRecord, bots: Mapping[int, Bot], action: Action) -> HandRecord:
    if r.abandoned:
        raise ValueError("the hand was abandoned")
    s = replay(r)
    if is_terminal(s):
        raise ValueError("the hand is over")
    if s.to_act != HERO_SEAT:
        raise ValueError("it is not Hero's turn")
    if not _is_on_menu(s, action):
        raise ValueError(f"not an option for Hero: {action}")
    r = replace(r, actions=(*r.actions, action))
    return _advance_state(r, _deal_board(apply(s, action), r.deck), bots)


def hero_act_seats(r: HandRecord, bots: Mapping[int, SeatBot], action: Action) -> HandRecord:
    """Apply Hero's ``action`` (an option or a legal post-flop size), then let the bots act.

    ``bots`` as in ``advance_seats``. After a Hero fold the bots play the hand to its end.
    Raises ``ValueError`` when the hand is over or abandoned, when it is not Hero's turn, when
    the bot seats are not exactly ``1 .. n-1``, or when ``action`` is neither on Hero's menu
    nor a legal post-flop custom size; ``TypeError`` for a seat without a ``SeatBot``.
    """
    _check_seat_bots(r, bots)
    return _hero_act(r, bots, action)


def hero_act(r: HandRecord, profile: Profile, action: Action) -> HandRecord:
    """Heads-up ``hero_act_seats``: the bot in seat 1 plays ``profile``."""
    _check_bots(r, {BOT_SEAT: profile})
    return _hero_act(r, {BOT_SEAT: profile}, action)


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

    Pots come from ``settle_pots`` with the record's start stacks. ``winner`` is "villain"
    when the hand was abandoned or Hero folded (even with nothing committed, e.g. UTG folding
    pre-flop), and otherwise the sign of Hero's delta.
    """
    n = num_seats(r)
    if n < 3:
        raise ValueError("outcome5 needs three or more seats; use outcome")
    s = replay(r)
    start = r.start_stacks[HERO_SEAT]
    folded = HERO_SEAT in folded_seats(s)
    if r.abandoned:
        stacks = _abandoned_stacks(r, s)
        delta = stacks[HERO_SEAT] - start
        return HandOutcome5("abandoned", "villain", stacks, delta, (), (), folded)
    if not is_terminal(s):
        return None
    st = settle_pots(s, holes(r), r.start_stacks)
    delta = st.stacks[HERO_SEAT] - start
    winner = "villain" if folded else _winner(delta)
    if s.folded is not None:
        return HandOutcome5("fold", winner, st.stacks, delta, st.pots, (), folded)
    shown = _clockwise(tuple(i for i in live_seats(s) if i != HERO_SEAT), r.button, n)
    return HandOutcome5("showdown", winner, st.stacks, delta, st.pots, shown, folded)
