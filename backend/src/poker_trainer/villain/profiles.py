"""Villain profiles: versioned pre-flop ranges and post-flop action tables per style."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from poker_trainer.engine.ranges import Range, parse_range
from poker_trainer.villain.features import HandCategory

PROFILE_NAMES = ("tag", "lag", "tight", "sticky")

UNOPENED_ROLES = ("cbet", "lead", "stab")
UNOPENED_ACTIONS = ("check", "bet_33", "bet_75")
FACING_SPOTS = ("facing_bet", "facing_raise")
FACING_ACTIONS = ("fold", "call", "raise")

Table = dict[HandCategory, dict[str, float]]


@dataclass(frozen=True)
class PreflopRanges:
    open: Range
    bb_call: Range
    bb_threebet: Range
    bb_call_open_jam: Range
    btn_call_threebet: Range
    btn_jam: Range
    btn_call_jam: Range
    bb_call_jam: Range


@dataclass(frozen=True)
class Bands:
    bluff_offset: tuple[float, float]
    defence_ratio: tuple[float, float]


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    description: str
    version: int
    preflop: PreflopRanges
    unopened: dict[str, Table]
    facing: dict[str, Table]
    bands: Bands


def _table(raw: dict, actions: tuple[str, ...], where: str) -> Table:
    names = {c.name for c in HandCategory}
    if set(raw) != names:
        raise ValueError(f"{where}: categories must be exactly {sorted(names)}")
    out: Table = {}
    for cat in HandCategory:
        row = raw[cat.name]
        if set(row) != set(actions):
            raise ValueError(f"{where}.{cat.name}: actions must be {actions}")
        probs = {a: float(row[a]) for a in actions}
        if any(not 0.0 <= p <= 1.0 for p in probs.values()):
            raise ValueError(f"{where}.{cat.name}: probabilities must be in [0, 1]")
        if not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-9):
            raise ValueError(f"{where}.{cat.name}: row must sum to 1")
        out[cat] = probs
    return out


def _band(raw: list) -> tuple[float, float]:
    lo, hi = (float(x) for x in raw)
    if lo > hi:
        raise ValueError(f"band lower bound {lo} exceeds upper bound {hi}")
    return lo, hi


def _ranges(raw: dict) -> PreflopRanges:
    out = {}
    for name in PreflopRanges.__dataclass_fields__:
        r = parse_range(raw[name])
        r.setflags(write=False)
        out[name] = r
    return PreflopRanges(**out)


def load_profile(name: str) -> Profile:
    if name not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {name!r}; expected one of {PROFILE_NAMES}")
    return _load(name)


@lru_cache(maxsize=len(PROFILE_NAMES))
def _load(name: str) -> Profile:
    text = (files("poker_trainer.villain") / "profiles" / f"{name}.json").read_text(
        encoding="utf-8"
    )
    raw = json.loads(text)
    if raw["name"] != name:
        raise ValueError(f"profile file {name}.json declares name {raw['name']!r}")
    unopened = {
        role: _table(raw["unopened"][role], UNOPENED_ACTIONS, f"{name}.unopened.{role}")
        for role in UNOPENED_ROLES
    }
    facing = {
        spot: _table(raw["facing"][spot], FACING_ACTIONS, f"{name}.facing.{spot}")
        for spot in FACING_SPOTS
    }
    return Profile(
        name=name,
        label=str(raw["label"]),
        description=str(raw["description"]),
        version=int(raw["version"]),
        preflop=_ranges(raw["preflop"]),
        unopened=unopened,
        facing=facing,
        bands=Bands(
            bluff_offset=_band(raw["bands"]["bluff_offset"]),
            defence_ratio=_band(raw["bands"]["defence_ratio"]),
        ),
    )
