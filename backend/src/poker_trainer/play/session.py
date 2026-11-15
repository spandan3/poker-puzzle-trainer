"""Session rules: the stack rules applied at the start of each hand, and dealing a hand."""

from __future__ import annotations

import random

from poker_trainer.game.state import START_STACK
from poker_trainer.play.hand import HandRecord

START = START_STACK  # chips (100 bb)
BOT_MIN = 80  # the bot rebuys to START below this
BOT_MAX = 300  # the bot is reset to START above this
HERO_MIN = 10  # Hero must rebuy to START below this


def must_rebuy(hero: int) -> bool:
    return hero < HERO_MIN


def next_stacks(hero: int, bot: int, *, top_up: bool) -> tuple[int, int, int]:
    """``(hero_stack, bot_stack, hero_bought)`` for the next hand.

    ``hero_bought`` is the chips added to Hero now: a forced rebuy below ``HERO_MIN``, or a
    top-up to ``START`` when Hero asks for one and is below it.
    """
    bot_stack = START if bot < BOT_MIN or bot > BOT_MAX else bot
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
