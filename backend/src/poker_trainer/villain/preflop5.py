"""5-max pre-flop bots: one hand ranking sliced by per-profile percentages.

Data (versioned, loaded with ``importlib.resources``):

- ``hand_ranking.json``: the 169 hand classes, strongest first (``analysis/hand_ranking.py``).
- ``fivemax.json``: per profile an open % by position, a 3-bet % and call % facing an open, a
  jam % and call % facing a 3-bet, and a call % facing a jam; the big blind's call multiplier;
  the multiway damping constants (used post-flop).

A bucket is a slice of the 1,326 combos taken in ranking order. A class that straddles a bucket
edge gets the fraction of its combos inside the slice as its weight, so a bucket of p% holds
exactly p% of the combos. "3-bet t%, call c%" means the top t% 3-bet and the next c% call.

The spot depends only on ``r``, the number of pre-flop raises (the history holds only FOLD,
CALL and RAISE: there are no limps, and a walk ends the hand):

- facing a jam (no raise legal, a pre-flop raiser is all-in, or ``r >= 3``): fold or call;
- ``r == 0``: fold or open to 2.5 bb (3 bb from the small blind);
- ``r == 1``: fold, call, or 3-bet to (3 + callers) x the open; the big blind calls wider;
- ``r == 2``: fold, call or jam.

``facing_jam`` is shared with Hero's options (``puzzle/options.py``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType

import numpy as np

from poker_trainer.engine.combos import HAND_CLASSES, combos_of_class
from poker_trainer.game.state import (
    ActionKind,
    HandState,
    Legal,
    Street,
    position_name,
)
from poker_trainer.villain.strategy import (
    Distribution,
    UnsupportedSpot,
    _call,
    _fold,
    _legal,
    _merge,
    _rest,
    _sized,
    allin,
    raise_to,
)

N_COMBOS = 1326
SEATS = 5
OPEN_MULT = 2.5  # x the big blind: 2.5 bb
SB_OPEN_MULT = 3.0  # the small blind opens to 3 bb (the bet faced is the 2-chip big blind)
SQUEEZE_BASE = 3  # a 3-bet is (3 + callers) x the open
OPEN_POSITIONS = ("UTG", "CO", "BTN", "SB")


@dataclass(frozen=True)
class FiveMaxProfile:
    """One profile's percentages (0-100, of the 1,326 combos)."""

    open: Mapping[str, float]  # by position: UTG, CO, BTN, SB
    threebet: float
    call: float
    jam_vs_threebet: float
    call_vs_threebet: float
    call_vs_jam: float


@dataclass(frozen=True)
class Damping:
    bluff: float
    thin: float
    call: float


@dataclass(frozen=True)
class FiveMax:
    version: int
    bb_call_mult: float
    damping: Damping
    profiles: Mapping[str, FiveMaxProfile]


def _pct(x: object, what: str) -> float:
    if isinstance(x, bool) or not isinstance(x, int | float) or not 0.0 <= x <= 100.0:
        raise ValueError(f"{what} must be a percentage in [0, 100], got {x!r}")
    return float(x)


def profile_from_block(name: str, raw: Mapping) -> FiveMaxProfile:
    """Parse and check one profile block of ``fivemax.json``."""
    opens = raw["open"]
    if set(opens) != set(OPEN_POSITIONS):
        raise ValueError(f"{name}: open needs exactly {OPEN_POSITIONS}, got {sorted(opens)}")
    p = FiveMaxProfile(
        open=MappingProxyType({k: _pct(opens[k], f"{name}.open.{k}") for k in OPEN_POSITIONS}),
        threebet=_pct(raw["vs_open"]["threebet"], f"{name}.vs_open.threebet"),
        call=_pct(raw["vs_open"]["call"], f"{name}.vs_open.call"),
        jam_vs_threebet=_pct(raw["vs_threebet"]["jam"], f"{name}.vs_threebet.jam"),
        call_vs_threebet=_pct(raw["vs_threebet"]["call"], f"{name}.vs_threebet.call"),
        call_vs_jam=_pct(raw["vs_jam"]["call"], f"{name}.vs_jam.call"),
    )
    if p.threebet + p.call > 100.0 or p.jam_vs_threebet + p.call_vs_threebet > 100.0:
        raise ValueError(f"{name}: buckets add up to more than 100%")
    return p


def fivemax_from_dict(raw: Mapping) -> FiveMax:
    mult = raw["bb_call_mult"]
    if not isinstance(mult, int | float) or mult < 1.0:
        raise ValueError(f"bb_call_mult must be >= 1, got {mult!r}")
    d = raw["damping"]
    damping = Damping(bluff=float(d["bluff"]), thin=float(d["thin"]), call=float(d["call"]))
    for k, v in vars(damping).items():
        if not 0.0 < v <= 1.0:
            raise ValueError(f"damping.{k} must be in (0, 1], got {v}")
    return FiveMax(
        version=int(raw["version"]),
        bb_call_mult=float(mult),
        damping=damping,
        profiles=MappingProxyType(
            {name: profile_from_block(name, block) for name, block in raw["profiles"].items()}
        ),
    )


def _read(name: str) -> dict:
    return json.loads(files("poker_trainer.villain").joinpath(name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_fivemax() -> FiveMax:
    return fivemax_from_dict(_read("fivemax.json"))


@lru_cache(maxsize=1)
def load_ranking() -> tuple[int, tuple[str, ...]]:
    """``(version, classes strongest first)`` from ``hand_ranking.json``."""
    raw = _read("hand_ranking.json")
    classes = tuple(raw["classes"])
    if sorted(classes) != sorted(HAND_CLASSES):
        raise ValueError("hand_ranking.json must list each of the 169 hand classes once")
    return int(raw["version"]), classes


@lru_cache(maxsize=1)
def _class_spans() -> tuple[tuple[np.ndarray, float, float], ...]:
    """Per class in ranking order: its combo indices and its [start, end) in combo counts."""
    out = []
    start = 0.0
    for label in load_ranking()[1]:
        idx = np.array(combos_of_class(label), dtype=np.intp)
        out.append((idx, start, start + len(idx)))
        start += len(idx)
    return tuple(out)


@lru_cache(maxsize=256)
def bucket(lo_pct: float, hi_pct: float) -> np.ndarray:
    """Per-combo weight of the slice [lo%, hi%) of the combos in ranking order (read-only).

    The class straddling an edge gets the fraction of its combos inside the slice, so the
    weights sum to exactly ``(hi - lo)% x 1326``.
    """
    lo = max(0.0, min(lo_pct, 100.0)) / 100.0 * N_COMBOS
    hi = max(0.0, min(hi_pct, 100.0)) / 100.0 * N_COMBOS
    w = np.zeros(N_COMBOS)
    for idx, start, end in _class_spans():
        overlap = min(end, hi) - max(start, lo)
        if overlap > 0:
            w[idx] = overlap / (end - start)
    w.flags.writeable = False
    return w


def preflop_raises(s: HandState) -> list[int]:
    """Indices in ``s.history`` of the pre-flop raises."""
    return [
        i
        for i, a in enumerate(s.history)
        if a.street == Street.PREFLOP and a.kind == ActionKind.RAISE
    ]


def facing_jam(s: HandState, lg: Legal) -> bool:
    """True when the seat to act may only fold or call pre-flop.

    No raise is legal, or a pre-flop raiser is now all-in (even if a deeper seat could
    technically raise), or there have been three raises already (a 4-bet is always a jam,
    even when it is capped below the jammer's own stack).
    """
    raises = preflop_raises(s)
    if lg.aggressive is None or len(raises) >= 3:
        return True
    return any(s.stacks[s.history[i].seat] == 0 for i in raises)


def callers_after_open(s: HandState) -> int:
    """Number of CALLs after the first pre-flop raise."""
    raises = preflop_raises(s)
    if not raises:
        return 0
    return sum(
        1
        for a in s.history[raises[0] + 1 :]
        if a.street == Street.PREFLOP and a.kind == ActionKind.CALL
    )


def has_limp(s: HandState) -> bool:
    """A CALL before any raise (not in the supported tree)."""
    for a in s.history:
        if a.street != Street.PREFLOP or a.kind == ActionKind.RAISE:
            return False
        if a.kind == ActionKind.CALL:
            return True
    return False


def distribution(fm: FiveMax, p: FiveMaxProfile, s: HandState) -> Distribution:
    """The 5-max pre-flop distribution for the seat to act (see ``strategy.action_distribution``).

    ``strategy`` imports this module lazily, so the import above is not circular.
    """
    if len(s.stacks) != SEATS:
        raise UnsupportedSpot(f"the 5-max pre-flop policy needs 5 seats, got {len(s.stacks)}")
    lg = _legal(s)
    if has_limp(s):
        raise UnsupportedSpot("limped pots are not supported")
    if facing_jam(s, lg):
        call = bucket(0.0, p.call_vs_jam)
        return _merge([(_fold(s), _rest(call)), (_call(s, lg), call)])
    r = len(preflop_raises(s))
    pos = position_name(s, s.to_act)  # type: ignore[arg-type]
    if r == 0:
        if pos not in OPEN_POSITIONS:
            raise UnsupportedSpot(f"{pos} cannot open")
        opened = bucket(0.0, p.open[pos])
        mult = SB_OPEN_MULT if pos == "SB" else OPEN_MULT
        return _merge([(_fold(s), _rest(opened)), (raise_to(s, mult), opened)])
    if r == 1:
        call_pct = p.call * fm.bb_call_mult if pos == "BB" else p.call
        call_pct = min(call_pct, 100.0 - p.threebet)
        three = bucket(0.0, p.threebet)
        call = bucket(p.threebet, p.threebet + call_pct)
        to = round((SQUEEZE_BASE + callers_after_open(s)) * max(s.street_bets))
        return _merge(
            [
                (_fold(s), _rest(three, call)),
                (_call(s, lg), call),
                (_sized(s, lg, ActionKind.RAISE, to), three),
            ]
        )
    # r == 2
    jam = bucket(0.0, p.jam_vs_threebet)
    call = bucket(p.jam_vs_threebet, p.jam_vs_threebet + p.call_vs_threebet)
    return _merge([(_fold(s), _rest(jam, call)), (_call(s, lg), call), (allin(s), jam)])
