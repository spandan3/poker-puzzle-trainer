"""Frozen puzzle data model, puzzle config, and the JSON round-trip.

Dataclasses holding ndarrays use ``eq=False``; compare them field by field.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

import numpy as np

from poker_trainer.engine.equity import ComboEquity
from poker_trainer.engine.ranges import Range, remove_blocked
from poker_trainer.game.state import Action, ActionKind, HandState, Street

FORMAT = 1

SIMPLIFICATIONS: Mapping[str, str] = MappingProxyType(
    {
        "realisation": "Before the river, Hero is assumed to realise full equity.",
        "reraise_reply": "After a Villain re-raise, Hero only folds or calls.",
        "preflop_size": "Pre-flop, Villain's responses don't depend on Hero's raise size.",
    }
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictConfig:
    best_bb: float
    best_pot: float
    fine_pot: float
    mistake_pot: float


@dataclass(frozen=True)
class ScoreConfig:
    great: float
    good: float


@dataclass(frozen=True)
class TrivialConfig:
    eq_hi: float
    eq_lo: float
    gap_pot: float
    gap_eq_hi: float
    gap_eq_lo: float


@dataclass(frozen=True)
class PuzzleConfig:
    version: int
    street_weights: Mapping[str, float]
    stop_prob: float
    samples: int
    verdict: VerdictConfig
    score: ScoreConfig
    trivial: TrivialConfig
    max_attempts: int


@lru_cache(maxsize=1)
def load_config() -> PuzzleConfig:
    raw = json.loads(
        files("poker_trainer.puzzle").joinpath("config.json").read_text(encoding="utf-8")
    )
    return PuzzleConfig(
        version=raw["version"],
        street_weights=MappingProxyType(dict(raw["street_weights"])),
        stop_prob=raw["stop_prob"],
        samples=raw["samples"],
        verdict=VerdictConfig(**raw["verdict"]),
        score=ScoreConfig(**raw["score"]),
        trivial=TrivialConfig(**raw["trivial"]),
        max_attempts=raw["max_attempts"],
    )


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    label: str
    action: Action


@dataclass(frozen=True, eq=False)
class RangeView:
    label: str
    street: Street
    range: Range


@dataclass(frozen=True, eq=False)
class Spot:
    seed: int
    attempt: int
    state: HandState
    hero_seat: int
    hero: tuple[int, int]
    villain_hole: tuple[int, int]
    runout: tuple[int, ...]
    profile: str
    profile_version: int
    categories_version: int
    steps: tuple[RangeView, ...]

    @property
    def range(self) -> Range:
        return self.steps[-1].range


@dataclass(frozen=True)
class Branch:
    label: str
    share: float
    equity: float | None
    value_chips: float


@dataclass(frozen=True, eq=False)
class OptionEV:
    option: Option
    ev_chips: float
    fold_freq: float | None
    equity_vs_continue: float | None
    ahead_vs_continue: float | None
    equity_vs_continue_se: float | None
    required_fold_equity: float | None
    put: int
    continue_range: Range | None
    branches: tuple[Branch, ...]
    simplifications: tuple[str, ...]

    @property
    def ev_bb(self) -> float:
        return self.ev_chips / 2


@dataclass(frozen=True)
class CategoryRow:
    category: str
    share: float
    ahead: float
    equity: float


@dataclass(frozen=True, eq=False)
class Solution:
    equity: float
    equity_std_error: float
    equity_exact: bool
    ahead_now: float | None
    pot_odds: float
    options: tuple[OptionEV, ...]
    best: int
    combo_equity: ComboEquity
    category_breakdown: tuple[CategoryRow, ...] | None
    simplifications: tuple[str, ...]


@dataclass(frozen=True, eq=False)
class Puzzle:
    spot: Spot
    solution: Solution


def visible_range(r: Range, hero: tuple[int, int], board: tuple[int, ...]) -> Range:
    """What Villain can hold given what Hero sees now (the only place blockers are removed)."""
    out = remove_blocked(r, (*hero, *board))
    out.setflags(write=False)
    return out


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def _arr(a: np.ndarray) -> list[float]:
    return np.asarray(a).astype(float).tolist()


def _f(x: float | None) -> float | None:
    return None if x is None else float(x)


def _ro(values: Any) -> np.ndarray:
    a = np.array(values, dtype=np.float64)
    a.setflags(write=False)
    return a


def _action_to_dict(a: Action) -> dict[str, Any]:
    return {"seat": int(a.seat), "kind": a.kind.value, "street": int(a.street), "to": int(a.to)}


def _action_from_dict(d: dict[str, Any]) -> Action:
    return Action(d["seat"], ActionKind(d["kind"]), Street(d["street"]), d["to"])


def _state_to_dict(s: HandState) -> dict[str, Any]:
    return {
        "button": int(s.button),
        "stacks": [int(x) for x in s.stacks],
        "street_bets": [int(x) for x in s.street_bets],
        "pot": int(s.pot),
        "street": int(s.street),
        "board": [int(x) for x in s.board],
        "to_act": None if s.to_act is None else int(s.to_act),
        "history": [_action_to_dict(a) for a in s.history],
        "last_raise": int(s.last_raise),
        "folded": None if s.folded is None else int(s.folded),
        "total_chips": int(s.total_chips),
    }


def _state_from_dict(d: dict[str, Any]) -> HandState:
    return HandState(
        button=d["button"],
        stacks=(d["stacks"][0], d["stacks"][1]),
        street_bets=(d["street_bets"][0], d["street_bets"][1]),
        pot=d["pot"],
        street=Street(d["street"]),
        board=tuple(d["board"]),
        to_act=d["to_act"],
        history=tuple(_action_from_dict(a) for a in d["history"]),
        last_raise=d["last_raise"],
        folded=d["folded"],
        total_chips=d["total_chips"],
    )


def _spot_to_dict(sp: Spot) -> dict[str, Any]:
    return {
        "seed": int(sp.seed),
        "attempt": int(sp.attempt),
        "state": _state_to_dict(sp.state),
        "hero_seat": int(sp.hero_seat),
        "hero": [int(x) for x in sp.hero],
        "villain_hole": [int(x) for x in sp.villain_hole],
        "runout": [int(x) for x in sp.runout],
        "profile": str(sp.profile),
        "profile_version": int(sp.profile_version),
        "categories_version": int(sp.categories_version),
        "steps": [
            {"label": v.label, "street": int(v.street), "range": _arr(v.range)} for v in sp.steps
        ],
    }


def _spot_from_dict(d: dict[str, Any]) -> Spot:
    return Spot(
        seed=d["seed"],
        attempt=d["attempt"],
        state=_state_from_dict(d["state"]),
        hero_seat=d["hero_seat"],
        hero=(d["hero"][0], d["hero"][1]),
        villain_hole=(d["villain_hole"][0], d["villain_hole"][1]),
        runout=tuple(d["runout"]),
        profile=d["profile"],
        profile_version=d["profile_version"],
        categories_version=d["categories_version"],
        steps=tuple(
            RangeView(v["label"], Street(v["street"]), _ro(v["range"])) for v in d["steps"]
        ),
    )


def _option_ev_to_dict(o: OptionEV) -> dict[str, Any]:
    return {
        "label": o.option.label,
        "action": _action_to_dict(o.option.action),
        "ev_chips": float(o.ev_chips),
        "fold_freq": _f(o.fold_freq),
        "equity_vs_continue": _f(o.equity_vs_continue),
        "ahead_vs_continue": _f(o.ahead_vs_continue),
        "equity_vs_continue_se": _f(o.equity_vs_continue_se),
        "required_fold_equity": _f(o.required_fold_equity),
        "put": int(o.put),
        "continue_range": None if o.continue_range is None else _arr(o.continue_range),
        "branches": [
            {
                "label": b.label,
                "share": float(b.share),
                "equity": _f(b.equity),
                "value_chips": float(b.value_chips),
            }
            for b in o.branches
        ],
        "simplifications": list(o.simplifications),
    }


def _option_ev_from_dict(d: dict[str, Any]) -> OptionEV:
    return OptionEV(
        option=Option(d["label"], _action_from_dict(d["action"])),
        ev_chips=d["ev_chips"],
        fold_freq=d["fold_freq"],
        equity_vs_continue=d["equity_vs_continue"],
        ahead_vs_continue=d["ahead_vs_continue"],
        equity_vs_continue_se=d["equity_vs_continue_se"],
        required_fold_equity=d["required_fold_equity"],
        put=d["put"],
        continue_range=None if d["continue_range"] is None else _ro(d["continue_range"]),
        branches=tuple(
            Branch(b["label"], b["share"], b["equity"], b["value_chips"]) for b in d["branches"]
        ),
        simplifications=tuple(d["simplifications"]),
    )


def _combo_equity_to_dict(c: ComboEquity) -> dict[str, Any]:
    return {
        "hero": [int(x) for x in c.hero],
        "board": [int(x) for x in c.board],
        "base": _arr(c.base),
        "wins": _arr(c.wins),
        "ties": _arr(c.ties),
        "count": _arr(c.count),
        "exact": bool(c.exact),
    }


def _combo_equity_from_dict(d: dict[str, Any]) -> ComboEquity:
    return ComboEquity(
        hero=(d["hero"][0], d["hero"][1]),
        board=tuple(d["board"]),
        base=_ro(d["base"]),
        wins=_ro(d["wins"]),
        ties=_ro(d["ties"]),
        count=_ro(d["count"]),
        exact=d["exact"],
    )


def _solution_to_dict(s: Solution) -> dict[str, Any]:
    cb = s.category_breakdown
    return {
        "equity": float(s.equity),
        "equity_std_error": float(s.equity_std_error),
        "equity_exact": bool(s.equity_exact),
        "ahead_now": _f(s.ahead_now),
        "pot_odds": float(s.pot_odds),
        "options": [_option_ev_to_dict(o) for o in s.options],
        "best": int(s.best),
        "combo_equity": _combo_equity_to_dict(s.combo_equity),
        "category_breakdown": None
        if cb is None
        else [
            {
                "category": r.category,
                "share": float(r.share),
                "ahead": float(r.ahead),
                "equity": float(r.equity),
            }
            for r in cb
        ],
        "simplifications": list(s.simplifications),
    }


def _solution_from_dict(d: dict[str, Any]) -> Solution:
    cb = d["category_breakdown"]
    return Solution(
        equity=d["equity"],
        equity_std_error=d["equity_std_error"],
        equity_exact=d["equity_exact"],
        ahead_now=d["ahead_now"],
        pot_odds=d["pot_odds"],
        options=tuple(_option_ev_from_dict(o) for o in d["options"]),
        best=d["best"],
        combo_equity=_combo_equity_from_dict(d["combo_equity"]),
        category_breakdown=None
        if cb is None
        else tuple(CategoryRow(r["category"], r["share"], r["ahead"], r["equity"]) for r in cb),
        simplifications=tuple(d["simplifications"]),
    )


def puzzle_to_dict(p: Puzzle) -> dict[str, Any]:
    """JSON-safe dict (ranges and equity tables as lists of floats)."""
    return {
        "format": FORMAT,
        "spot": _spot_to_dict(p.spot),
        "solution": _solution_to_dict(p.solution),
    }


def puzzle_from_dict(d: dict[str, Any]) -> Puzzle:
    if d.get("format") != FORMAT:
        raise ValueError(f"unsupported puzzle format: {d.get('format')!r}")
    return Puzzle(_spot_from_dict(d["spot"]), _solution_from_dict(d["solution"]))
