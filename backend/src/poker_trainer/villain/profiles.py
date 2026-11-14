"""Villain profiles: versioned pre-flop ranges and post-flop action tables per style."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from poker_trainer.engine.ranges import Range, parse_range
from poker_trainer.villain.features import HandCategory

PROFILE_NAMES = ("tag", "lag", "tight", "sticky")

UNOPENED_ROLES = ("cbet", "lead", "stab")
UNOPENED_ACTIONS = ("check", "bet_33", "bet_75")
FACING_SPOTS = ("facing_bet", "facing_raise")
FACING_ACTIONS = ("fold", "call", "raise")
# Least continue (call + raise) a STRONG facing row may have. The size curve in
# ``strategy._facing`` floors STRONG at this value against huge bets, which is only a floor
# (never a boost above the row) when the row itself continues at least this much.
STRONG_CONTINUE_MIN = 0.75

Table = Mapping[HandCategory, Mapping[str, float]]


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
    unopened: Mapping[str, Table]
    facing: Mapping[str, Table]
    bands: Bands
    # River-only overrides of unopened rows: role -> category -> row. Missing roles or
    # categories fall back to ``unopened``. A river bet has no protection or draw value,
    # so WEAK/MEDIUM/AIR rows that are sensible on the flop over-bluff there.
    river_unopened: Mapping[str, Table] = MappingProxyType({})
    # River-only overrides of facing rows: spot -> category -> row, applied before the size
    # curve. On the river a raise has no protection value: a bluff catcher that raises only
    # folds out worse hands and gets called by better ones.
    river_facing: Mapping[str, Table] = MappingProxyType({})


def _table(raw: Any, actions: tuple[str, ...], where: str) -> Table:
    names = {c.name for c in HandCategory}
    if not isinstance(raw, dict) or set(raw) != names:
        raise ValueError(f"{where}: categories must be exactly {sorted(names)}")
    out = {cat: _row(raw[cat.name], actions, f"{where}.{cat.name}") for cat in HandCategory}
    return MappingProxyType(out)


def _row(raw: Any, actions: tuple[str, ...], where: str) -> Mapping[str, float]:
    if not isinstance(raw, dict) or set(raw) != set(actions):
        raise ValueError(f"{where}: actions must be {actions}")
    try:
        probs = {a: float(raw[a]) for a in actions}
    except (TypeError, ValueError) as e:
        raise ValueError(f"{where}: {e}") from e
    if any(not 0.0 <= p <= 1.0 for p in probs.values()):
        raise ValueError(f"{where}: probabilities must be in [0, 1]")
    if not math.isclose(sum(probs.values()), 1.0, abs_tol=1e-9):
        raise ValueError(f"{where}: row must sum to 1")
    return MappingProxyType(probs)


def _river_overrides(
    raw: Any,
    where: str,
    roles: tuple[str, ...] = UNOPENED_ROLES,
    actions: tuple[str, ...] = UNOPENED_ACTIONS,
) -> Mapping[str, Table]:
    """Optional partial tables: any subset of ``roles`` and categories."""
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, dict) or not set(raw) <= set(roles):
        raise ValueError(f"{where}: roles must be a subset of {roles}")
    names = {c.name for c in HandCategory}
    out = {}
    for role, rows in raw.items():
        if not isinstance(rows, dict) or not set(rows) <= names:
            raise ValueError(f"{where}.{role}: categories must be a subset of {sorted(names)}")
        out[role] = MappingProxyType(
            {
                HandCategory[cat]: _row(row, actions, f"{where}.{role}.{cat}")
                for cat, row in rows.items()
            }
        )
    return MappingProxyType(out)


def _band(raw: Any, where: str) -> tuple[float, float]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise ValueError(f"{where}: band must be a [lo, hi] pair")
    try:
        lo, hi = (float(x) for x in raw)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{where}: {e}") from e
    if lo > hi:
        raise ValueError(f"{where}: lower bound {lo} exceeds upper bound {hi}")
    return lo, hi


def _ranges(raw: Any, where: str) -> PreflopRanges:
    out = {}
    for name in PreflopRanges.__dataclass_fields__:
        try:
            r = parse_range(raw[name])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"{where}.{name}: {e}") from e
        r.setflags(write=False)
        out[name] = r
    return PreflopRanges(**out)


def load_profile(name: str) -> Profile:
    if name not in PROFILE_NAMES:
        raise ValueError(f"unknown profile {name!r}; expected one of {PROFILE_NAMES}")
    return _load(name)


def profile_meta(name: str) -> tuple[str, str]:
    """``(label, description)`` for a stored profile name.

    Falls back to ``(name.title(), "")`` for a name that is not a stored profile (the loader's
    ``ValueError``) instead of raising.
    """
    try:
        prof = load_profile(name)
    except ValueError:
        return name.title(), ""
    return prof.label, prof.description


@lru_cache(maxsize=len(PROFILE_NAMES))
def _load(name: str) -> Profile:
    text = (files("poker_trainer.villain") / "profiles" / f"{name}.json").read_text(
        encoding="utf-8"
    )
    return _profile_from_dict(name, json.loads(text))


def _profile_from_dict(name: str, raw: Any) -> Profile:
    """Build and validate a Profile; every structural problem raises ValueError."""
    try:
        if raw["name"] != name:
            raise ValueError(f"profile file {name}.json declares name {raw['name']!r}")
        version = int(raw["version"])
        if version < 1:
            raise ValueError(f"{name}.version must be >= 1, got {version}")
        unopened = MappingProxyType(
            {
                role: _table(raw["unopened"][role], UNOPENED_ACTIONS, f"{name}.unopened.{role}")
                for role in UNOPENED_ROLES
            }
        )
        facing = MappingProxyType(
            {
                spot: _table(raw["facing"][spot], FACING_ACTIONS, f"{name}.facing.{spot}")
                for spot in FACING_SPOTS
            }
        )
        river_facing = _river_overrides(
            raw.get("river_facing"), f"{name}.river_facing", FACING_SPOTS, FACING_ACTIONS
        )
        for where, tables in (("facing", facing), ("river_facing", river_facing)):
            for spot, table in tables.items():
                row = table.get(HandCategory.STRONG)
                if row is not None and row["call"] + row["raise"] < STRONG_CONTINUE_MIN - 1e-9:
                    raise ValueError(
                        f"{name}.{where}.{spot}.STRONG: continue must be at least "
                        f"{STRONG_CONTINUE_MIN}"
                    )
        return Profile(
            name=name,
            label=str(raw["label"]),
            description=str(raw["description"]),
            version=version,
            preflop=_ranges(raw["preflop"], f"{name}.preflop"),
            unopened=unopened,
            facing=facing,
            river_unopened=_river_overrides(raw.get("river_unopened"), f"{name}.river_unopened"),
            river_facing=river_facing,
            bands=Bands(
                bluff_offset=_band(raw["bands"]["bluff_offset"], f"{name}.bands.bluff_offset"),
                defence_ratio=_band(raw["bands"]["defence_ratio"], f"{name}.bands.defence_ratio"),
            ),
        )
    except KeyError as e:
        raise ValueError(f"{name}: missing key {e}") from e
    except TypeError as e:
        raise ValueError(f"{name}: malformed profile data: {e}") from e
