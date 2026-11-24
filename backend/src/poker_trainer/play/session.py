"""Session rules: the stack rules applied at the start of each hand, and dealing a hand."""

from __future__ import annotations

import random
from collections.abc import Sequence

from poker_trainer.game.state import START_STACK
from poker_trainer.play.hand import HandRecord

START = START_STACK  # chips (100 bb)
BOT_MIN = 80  # the bot rebuys to START below this
BOT_MAX = 300  # the bot is reset to START above this
HERO_MIN = 10  # Hero must rebuy to START below this
SEATS5 = 5  # Hero (seat 0) and four bots


def must_rebuy(hero: int) -> bool:
    return hero < HERO_MIN


def _bot_stack(bot: int) -> int:
    return START if bot < BOT_MIN or bot > BOT_MAX else bot


def next_stacks(hero: int, bot: int, *, top_up: bool) -> tuple[int, int, int]:
    """``(hero_stack, bot_stack, hero_bought)`` for the next hand.

    ``hero_bought`` is the chips added to Hero now: a forced rebuy below ``HERO_MIN``, or a
    top-up to ``START`` when Hero asks for one and is below it.
    """
    bot_stack = _bot_stack(bot)
    if must_rebuy(hero) or (top_up and hero < START):
        return START, bot_stack, START - hero
    return hero, bot_stack, 0


def new_record(button: int, stacks: tuple[int, int], rng: random.Random) -> HandRecord:
    """A fresh hand: a shuffled deck and the bot's seed, both drawn from ``rng``."""
    deck = list(range(52))
    rng.shuffle(deck)
    return HandRecord(
        button=button,
        start_stacks=(stacks[0], stacks[1]),
        deck=tuple(deck),
        bot_seed=rng.getrandbits(62),
        actions=(),
    )


def next_stacks5(
    hero: int, bots: Sequence[int], *, top_up: bool
) -> tuple[int, tuple[int, ...], int]:
    """``(hero_stack, bot_stacks, hero_bought)`` for the next 5-max hand.

    Each bot separately: below ``BOT_MIN`` or above ``BOT_MAX`` it is reset to ``START``.
    Hero as heads-up: a forced rebuy below ``HERO_MIN``, or a top-up to ``START`` on request.
    """
    if len(bots) != SEATS5 - 1:
        raise ValueError(f"5-max needs {SEATS5 - 1} bot stacks, got {len(bots)}")
    bot_stacks = tuple(_bot_stack(b) for b in bots)
    if must_rebuy(hero) or (top_up and hero < START):
        return START, bot_stacks, START - hero
    return hero, bot_stacks, 0


def next_button(button: int, seats: int) -> int:
    """The button moves one seat clockwise each hand."""
    return (button + 1) % seats


def new_record5(button: int, stacks: Sequence[int], rng: random.Random) -> HandRecord:
    """A fresh 5-max hand (Hero is seat 0): a shuffled deck and the bots' seed from ``rng``."""
    if len(stacks) != SEATS5:
        raise ValueError(f"5-max needs {SEATS5} stacks, got {len(stacks)}")
    if not 0 <= button < SEATS5:
        raise ValueError(f"button {button} is not a seat")
    deck = list(range(52))
    rng.shuffle(deck)
    return HandRecord(
        button=button,
        start_stacks=tuple(int(x) for x in stacks),
        deck=tuple(deck),
        bot_seed=rng.getrandbits(62),
        actions=(),
    )
