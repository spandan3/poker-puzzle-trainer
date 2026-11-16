"""Analysis of a played hand: each Hero decision as a puzzle, solved and graded like one.

A decision's ``Spot`` is the hand as it stood when Hero acted. Its range is the bot's real
line narrowed by ``RangeTracker`` with the session's profile snapshot (never the live file),
seen through Hero's blockers. It is solved and graded by the same ``solve`` and
``grade_action`` the puzzles use, so the hand's result never enters the grade.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from poker_trainer.game.state import Action
from poker_trainer.play.hand import BOT_SEAT, HERO_SEAT, HandRecord, bot_cards, hero_cards, replay
from poker_trainer.puzzle.grade import ActionGrade, grade_action
from poker_trainer.puzzle.model import Puzzle, RangeView, Spot, load_config, visible_range
from poker_trainer.puzzle.solve import solve, villain_respond
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.narrowing import RangeTracker
from poker_trainer.villain.profiles import Profile


@dataclass(frozen=True)
class DecisionAnalysis:
    """Either ``puzzle`` and ``grade`` (graded), or ``not_graded`` with the reason."""

    puzzle: Puzzle | None
    grade: ActionGrade | None
    not_graded: str | None


def hero_decisions(r: HandRecord) -> tuple[int, ...]:
    """The indices into ``r.actions`` of Hero's actions, in order."""
    return tuple(i for i, a in enumerate(r.actions) if a.seat == HERO_SEAT)


def _decision_index(r: HandRecord, n: int) -> int:
    idx = hero_decisions(r)
    if not 0 <= n < len(idx):
        raise IndexError(f"decision {n} out of range: the hand has {len(idx)} Hero decisions")
    return idx[n]


def decision_spot(r: HandRecord, profile: Profile, n: int) -> tuple[Spot, Action]:
    """The spot at Hero's ``n``-th decision (0-based) and the action Hero took there.

    Raises ``IndexError`` for an ``n`` outside the hand's decisions, and ``ValueError`` when
    the range tracker cannot follow the bot's line (e.g. after a category-threshold change).
    """
    i = _decision_index(r, n)
    tracker = RangeTracker(profile, BOT_SEAT)
    for k in range(i):
        a = r.actions[k]
        if a.seat == BOT_SEAT:
            tracker.observe(replay(replace(r, actions=r.actions[:k])), a)
    s = replay(replace(r, actions=r.actions[:i]))
    hero = hero_cards(r)
    board = tuple(s.board)
    steps = tuple(
        RangeView(st.label, st.street, visible_range(st.range, hero, board)) for st in tracker.steps
    )
    spot = Spot(
        seed=r.bot_seed,
        attempt=n,
        state=s,
        hero_seat=HERO_SEAT,
        hero=hero,
        villain_hole=bot_cards(r),
        runout=tuple(r.deck[4:9]),
        profile=profile.name,
        profile_version=profile.version,
        categories_version=load_thresholds().version,
        config_version=load_config().version,
        steps=steps,
        start_stacks=r.start_stacks,
    )
    return spot, r.actions[i]


def analyse_decision(
    r: HandRecord, profile: Profile, n: int, *, samples: int | None = None
) -> DecisionAnalysis:
    """Solve Hero's ``n``-th decision and grade the action Hero took, with ``profile``.

    The equity MC is seeded from the record and ``n``, so the analysis is reproducible.
    ``UnsupportedSpot`` or ``ValueError`` from building the spot, the solver or the grader
    becomes ``not_graded`` with the message; an ``n`` out of range raises ``IndexError``.
    """
    _decision_index(r, n)
    if samples is None:
        samples = load_config().samples
    respond = villain_respond(profile)
    try:
        spot, action = decision_spot(r, profile, n)
        rng = random.Random(f"{r.bot_seed}:analysis:{n}")
        sol = solve(spot.state, spot.hero, spot.range, respond, rng=rng, samples=samples)
        puzzle = Puzzle(spot, sol)
        grade = grade_action(puzzle, action, respond=respond)
    except ValueError as e:  # UnsupportedSpot is a ValueError
        return DecisionAnalysis(None, None, str(e))
    return DecisionAnalysis(puzzle, grade, None)
