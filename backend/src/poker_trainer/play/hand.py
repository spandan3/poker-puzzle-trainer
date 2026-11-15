"""One heads-up hand against the bot, stored as a record and rebuilt by replay.

A ``HandRecord`` holds what was fixed when the hand started (button, stacks, deck order,
the bot's seed) and every action so far; the game state is never stored. The bot's action
at history index ``i`` is ``sample_action`` seeded with ``f"{bot_seed}:{i}"``, so the bot's
play is a pure function of the record and a resumed hand continues exactly as it would have.
Deck convention as in ``generate_spot``: Hero ``deck[0:2]``, bot ``deck[2:4]``, board
``deck[4:9]``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Literal

from poker_trainer.game.settle import settle
from poker_trainer.game.state import (
    Action,
    HandState,
    Street,
    apply,
    deal,
    is_terminal,
    needs_board,
    new_hand,
)
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.profiles import Profile
from poker_trainer.villain.strategy import sample_action

HERO_SEAT = 0  # fixed for the whole session; tuples indexed by seat are (Hero, bot)
BOT_SEAT = 1


@dataclass(frozen=True)
class HandRecord:
    button: int
    start_stacks: tuple[int, int]
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


def hero_cards(r: HandRecord) -> tuple[int, int]:
    return r.deck[0], r.deck[1]


def bot_cards(r: HandRecord) -> tuple[int, int]:
    return r.deck[2], r.deck[3]


def _deal_board(s: HandState, deck: tuple[int, ...]) -> HandState:
    """Deal every street whose betting is complete, including the run-out after an all-in."""
    while needs_board(s):
        n = 3 if s.street == Street.PREFLOP else 1
        k = len(s.board)
        s = deal(s, deck[4 + k : 4 + k + n])
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


def _bot_rng(r: HandRecord, index: int) -> random.Random:
    return random.Random(f"{r.bot_seed}:{index}")


def _advance_state(r: HandRecord, s: HandState, profile: Profile) -> HandRecord:
    actions = list(r.actions)
    while not is_terminal(s) and s.to_act == BOT_SEAT:
        a = sample_action(profile, s, bot_cards(r), _bot_rng(r, len(s.history)))
        actions.append(a)
        s = _deal_board(apply(s, a), r.deck)
    return replace(r, actions=tuple(actions))


def advance(r: HandRecord, profile: Profile) -> HandRecord:
    """Append the bot's actions until Hero is to act or the hand is over.

    A record where Hero is to act, or a finished hand, comes back unchanged, so calling it
    again is harmless. Raises ``ValueError`` for an abandoned hand.
    """
    if r.abandoned:
        raise ValueError("the hand was abandoned")
    return _advance_state(r, replay(r), profile)


def _is_on_menu(s: HandState, action: Action) -> bool:
    if any(o.action == action for o in hero_options(s)):
        return True
    if s.street == Street.PREFLOP:
        return False
    try:
        return custom_action(s, action.to) == action
    except ValueError:
        return False


def hero_act(r: HandRecord, profile: Profile, action: Action) -> HandRecord:
    """Apply Hero's ``action`` (an option or a legal post-flop size), then let the bot act.

    Raises ``ValueError`` when the hand is over or abandoned, when it is not Hero's turn, or
    when ``action`` is neither on Hero's menu nor a legal post-flop custom size.
    """
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
    return _advance_state(r, _deal_board(apply(s, action), r.deck), profile)


def abandon(r: HandRecord) -> HandRecord:
    """Mark a running hand abandoned: Hero keeps the chips behind, the bot takes the rest.

    An already abandoned record comes back unchanged; a finished hand raises ``ValueError``.
    """
    if r.abandoned:
        return r
    if is_terminal(replay(r)):
        raise ValueError("the hand is over")
    return replace(r, abandoned=True)


def outcome(r: HandRecord) -> HandOutcome | None:
    """How the hand ended, or None while it is running."""
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
