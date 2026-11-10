"""Range narrowing driven by the same policy that generated Villain's line."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poker_trainer.engine.ranges import Range, full_range, total_weight
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    legal_actions,
    total_pot,
)
from poker_trainer.villain.profiles import Profile
from poker_trainer.villain.strategy import action_distribution

_STREET_NAMES = {
    Street.PREFLOP: "Pre-flop",
    Street.FLOP: "Flop",
    Street.TURN: "Turn",
    Street.RIVER: "River",
}


def narrow(r: Range, dist: dict[Action, np.ndarray], action: Action) -> Range:
    """Weight each combo by its probability of taking ``action``; returns a new array."""
    if action not in dist:
        raise ValueError("action not available")
    out = r * dist[action]
    if total_weight(out) <= 0.0:
        raise ValueError("action has zero probability for every combo in range")
    return out


def describe(action: Action, s: HandState) -> str:
    """Human label for ``action`` taken in state ``s`` (the state before the action)."""
    street = _STREET_NAMES[action.street]
    kind = action.kind
    if kind in (ActionKind.BET, ActionKind.RAISE):
        if action.to == legal_actions(s).max_to:
            return f"{street}: goes all-in"
        if action.street == Street.PREFLOP:
            n_raises = sum(
                1 for a in s.history if a.street == Street.PREFLOP and a.kind == ActionKind.RAISE
            )
            name = "opens" if n_raises == 0 else f"{n_raises + 2}-bets"
            return f"{street}: {name} to {action.to}"
        if kind == ActionKind.BET:
            pct = round(100 * (action.to - s.street_bets[action.seat]) / total_pot(s))
            return f"{street}: bets {action.to} ({pct}% pot)"
        return f"{street}: raises to {action.to}"
    return {
        ActionKind.CALL: f"{street}: calls",
        ActionKind.FOLD: f"{street}: folds",
        ActionKind.CHECK: f"{street}: checks",
    }[kind]


@dataclass(frozen=True)
class RangeStep:
    label: str
    street: Street
    action: Action | None
    range: Range


class RangeTracker:
    """Tracks one seat's range as it acts, using the shared strategy."""

    def __init__(self, profile: Profile, seat: int):
        self.profile = profile
        self.seat = seat
        self.steps: list[RangeStep] = [RangeStep("Start", Street.PREFLOP, None, full_range())]

    @property
    def current(self) -> Range:
        return self.steps[-1].range

    def observe(self, s: HandState, action: Action) -> RangeStep:
        if s.to_act != self.seat:
            raise ValueError(f"seat {self.seat} is not to act")
        dist = action_distribution(self.profile, s)
        step = RangeStep(describe(action, s), s.street, action, narrow(self.current, dist, action))
        self.steps.append(step)
        return step
