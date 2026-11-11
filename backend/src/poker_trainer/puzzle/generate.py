"""Puzzle generator: deal, play forward with the shared strategy, freeze a Hero decision, solve.

One ``random.Random(seed)`` drives the street and profile draw, every attempt and the
equity MC, so a seed reproduces its puzzle on the same machine. Rules: "Street and
profile", "Decision point" and "Trivial filter" in the M3 plan.
"""

from __future__ import annotations

import random

from poker_trainer.engine.ranges import total_weight
from poker_trainer.game.state import (
    Street,
    apply,
    deal,
    is_terminal,
    needs_board,
    new_hand,
    total_pot,
)
from poker_trainer.puzzle.model import Puzzle, RangeView, Spot, load_config, visible_range
from poker_trainer.puzzle.options import hero_options
from poker_trainer.puzzle.solve import solve, villain_respond
from poker_trainer.puzzle.trivial import is_trivial
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.narrowing import RangeTracker
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
from poker_trainer.villain.strategy import HERO_PROFILE, UnsupportedSpot, sample_action


def parse_street(street: Street | str) -> Street:
    if isinstance(street, Street):
        return street
    try:
        return Street[str(street).upper().replace("-", "")]
    except KeyError:
        raise ValueError(f"unknown street {street!r}") from None


def generate_spot(
    rng: random.Random, street: Street, profile: str, *, seed: int, attempt: int
) -> Spot | None:
    """One attempt at a Hero decision on ``street`` against ``profile``; None on failure."""
    cfg = load_config()
    villain_profile = load_profile(profile)
    hero_profile = load_profile(HERO_PROFILE)

    hero_seat = rng.randrange(2)
    button = rng.randrange(2)
    villain_seat = 1 - hero_seat
    deck = list(range(52))
    rng.shuffle(deck)
    hero = (deck[0], deck[1])
    villain_hole = (deck[2], deck[3])
    runout = tuple(deck[4:9])

    tracker = RangeTracker(villain_profile, villain_seat)
    s = new_hand(button)
    try:
        while True:
            if is_terminal(s):
                return None
            if needs_board(s):
                n = 3 if s.street == Street.PREFLOP else 1
                k = len(s.board)
                s = deal(s, runout[k : k + n])
                continue
            if s.street > street:
                return None
            if s.to_act == hero_seat:
                if s.street == street and rng.random() < cfg.stop_prob:
                    hero_options(s)  # UnsupportedSpot for lines the grader can't handle
                    break
                s = apply(s, sample_action(hero_profile, s, hero, rng))
            else:
                a = sample_action(villain_profile, s, villain_hole, rng)
                tracker.observe(s, a)
                s = apply(s, a)
    except UnsupportedSpot:
        return None

    board = tuple(s.board)
    steps = tuple(
        RangeView(st.label, st.street, visible_range(st.range, hero, board)) for st in tracker.steps
    )
    if any(total_weight(v.range) <= 0.0 for v in steps):
        return None
    return Spot(
        seed=seed,
        attempt=attempt,
        state=s,
        hero_seat=hero_seat,
        hero=hero,
        villain_hole=villain_hole,
        runout=runout,
        profile=profile,
        profile_version=villain_profile.version,
        categories_version=load_thresholds().version,
        steps=steps,
    )


def generate_puzzle(
    seed: int, *, street: Street | str | None = None, profile: str | None = None
) -> Puzzle:
    """A non-trivial puzzle for ``seed``; raises ``RuntimeError`` after ``max_attempts``."""
    cfg = load_config()
    rng = random.Random(seed)
    if street is None:
        names = list(cfg.street_weights)
        street = rng.choices(names, weights=[cfg.street_weights[n] for n in names])[0]
    target = parse_street(street)
    if profile is None:
        profile = rng.choice(PROFILE_NAMES)
    elif profile not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {PROFILE_NAMES}")
    respond = villain_respond(load_profile(profile))

    for attempt in range(cfg.max_attempts):
        spot = generate_spot(rng, target, profile, seed=seed, attempt=attempt)
        if spot is None:
            continue
        sol = solve(spot.state, spot.hero, spot.range, respond, rng=rng, samples=cfg.samples)
        if is_trivial(sol, total_pot(spot.state), cfg) is not None:
            continue
        return Puzzle(spot, sol)
    raise RuntimeError(
        f"no puzzle for seed {seed} ({target.name.lower()}, {profile}) "
        f"in {cfg.max_attempts} attempts"
    )
