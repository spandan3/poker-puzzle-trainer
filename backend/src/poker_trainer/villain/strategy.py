"""The single Villain policy: shared bet sizing, per-combo action distributions, sampling.

``action_distribution`` is the one source of truth. It generates the Villain's line
(``sample_action``), narrows its range from observed actions, and predicts its responses
to Hero's bets. Every key of a distribution is a concrete legal ``Action``; table keys
that resolve to the same ``Action`` (two sizes clamped to the same chips) are merged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

import numpy as np

from poker_trainer.engine.cards import ensure_distinct
from poker_trainer.engine.combos import combo_index
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Legal,
    Street,
    last_aggressor,
    legal_actions,
    live_seats,
    total_pot,
)
from poker_trainer.villain.features import (
    HandCategory,
    board_texture,
    categorize,
    load_thresholds,
    range_features,
    street_spr,
)
from poker_trainer.villain.profiles import (
    FACING_ACTIONS,
    STRONG_CONTINUE_MIN,
    UNOPENED_ACTIONS,
    Profile,
    Table,
)

if TYPE_CHECKING:
    from poker_trainer.villain.preflop5 import Damping

ALLIN_FRACTION = 0.6
OPEN_MULT = 2.5
THREEBET_MULT = 3.0
RAISE_MULT = 3.0
HERO_PROFILE = "tag"
# Version of the policy's behaviour (sizing, curves, sampling), stored with each played hand.
# Bump it by hand whenever a change here makes the same profile act differently.
STRATEGY_VERSION = 1

N_COMBOS = 1326
_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)
_DRAWS = (HandCategory.WEAK_DRAW, HandCategory.STRONG_DRAW)
_DRAW_BET_BOOST = 1.25
_LOW_SPR = 1.0
_COMMITTED = (HandCategory.MEDIUM, HandCategory.STRONG_DRAW, HandCategory.STRONG, HandCategory.NUTS)
_BLOCKED_ROW = len(HandCategory)  # extra all-zero table row used for board-blocked combos
# Size curve facing a bet or raise of f x the pot before it (MDF = 1 / (1 + f)).
# Up to a pot-size bet: continue = base ** ((1 + f) / 1.5). Past pot size, continue is the
# pot-size value times (2 / (1 + f)) ** power, i.e. it shrinks with MDF itself (the ratio
# of MDF here to MDF facing a pot-size bet), so the whole range's continue / MDF stays
# roughly flat in the size instead of dipping at 1.5-2x pot. Weak hands give up faster than
# MDF, bluff catchers and draws about as fast. STRONG keeps the gentle pot-size curve up
# to _STRONG_BEND x pot (all-in clamps of normal bets reach about there), then shrinks
# with power _STRONG_POWER, and past pot size never continues less than _STRONG_FLOOR (a
# huge over-jam does not blow it off its hand; below pot size a row with a low base can
# continue less). NUTS (base 1) always continues.
_OVERBET_POWER = np.zeros(_BLOCKED_ROW + 1)
_WEAK_ROWS = [int(c) for c in (HandCategory.AIR, HandCategory.WEAK_DRAW, HandCategory.WEAK)]
_OVERBET_POWER[_WEAK_ROWS] = 2.6
_OVERBET_POWER[[int(HandCategory.MEDIUM), int(HandCategory.STRONG_DRAW)]] = 1.8
_STRONG_POWER = 0.42
_STRONG_BEND = 5.0 / 3.0
_OVERBET_POWER.flags.writeable = False
_STRONG_FLOOR = STRONG_CONTINUE_MIN  # the loader keeps every STRONG facing row at or above it
# Multiway damping (``_damp_unopened`` / ``_damp_facing``): bluff rows, the thin-value row, and
# the rows below STRONG whose continuing is damped facing a bet.
_BLUFF_ROWS = _WEAK_ROWS  # AIR, WEAK_DRAW, WEAK
_THIN_ROW = int(HandCategory.MEDIUM)
_BELOW_STRONG = [
    int(c)
    for c in (
        HandCategory.AIR,
        HandCategory.WEAK_DRAW,
        HandCategory.WEAK,
        HandCategory.MEDIUM,
        HandCategory.STRONG_DRAW,
    )
]

Distribution = dict[Action, np.ndarray]


class UnsupportedSpot(ValueError):
    """The state is outside the supported pre-flop tree (e.g. a limp or a non-all-in 4-bet)."""


# ---------------------------------------------------------------------------
# Sizing (shared with Hero in M3)
# ---------------------------------------------------------------------------


def _legal(s: HandState) -> Legal:
    if s.to_act is None:
        raise ValueError("no player to act")
    return legal_actions(s)


def _sized(s: HandState, lg: Legal, kind: ActionKind, to: int) -> Action:
    assert lg.min_to is not None and lg.max_to is not None
    to = max(lg.min_to, min(to, lg.max_to))
    if to >= ALLIN_FRACTION * lg.max_to:
        to = lg.max_to
    return Action(s.to_act, kind, s.street, to)  # type: ignore[arg-type]


def bet_to(s: HandState, frac: float) -> Action:
    """Bet ``frac`` of the total pot: clamped to the legal range, all-in past the threshold."""
    lg = _legal(s)
    if lg.aggressive != ActionKind.BET:
        raise ValueError("betting is not legal in this state")
    to = s.street_bets[s.to_act] + round(frac * total_pot(s))  # type: ignore[index]
    return _sized(s, lg, ActionKind.BET, to)


def raise_to(s: HandState, mult: float) -> Action:
    """Raise to ``mult`` times the bet faced: clamped to the legal range, all-in past the threshold."""
    lg = _legal(s)
    if lg.aggressive != ActionKind.RAISE:
        raise ValueError("raising is not legal in this state")
    return _sized(s, lg, ActionKind.RAISE, round(mult * max(s.street_bets)))


def allin(s: HandState) -> Action:
    lg = _legal(s)
    if lg.aggressive is None or lg.max_to is None:
        raise ValueError("betting/raising is not legal in this state")
    return Action(s.to_act, lg.aggressive, s.street, lg.max_to)  # type: ignore[arg-type]


def _call(s: HandState, lg: Legal) -> Action:
    me = s.to_act
    return Action(me, ActionKind.CALL, s.street, s.street_bets[me] + lg.call)  # type: ignore[arg-type,index]


def _fold(s: HandState) -> Action:
    return Action(s.to_act, ActionKind.FOLD, s.street)  # type: ignore[arg-type]


def _check(s: HandState) -> Action:
    return Action(s.to_act, ActionKind.CHECK, s.street)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def role(s: HandState) -> str:
    """Post-flop role of the seat to act: facing_raise / facing_bet / cbet / lead / stab."""
    if s.street == Street.PREFLOP:
        raise ValueError("roles are defined post-flop only")
    if s.to_act is None:
        raise ValueError("no player to act")
    street_acts = [a for a in s.history if a.street == s.street]
    n_aggr = sum(1 for a in street_acts if a.kind in _AGGRESSIVE)
    if n_aggr >= 2:
        return "facing_raise"
    if n_aggr == 1:
        return "facing_bet"
    if last_aggressor(s, Street(s.street - 1)) == s.to_act:
        return "cbet"
    return "lead" if not street_acts else "stab"


# ---------------------------------------------------------------------------
# Distribution construction
# ---------------------------------------------------------------------------


def _merge(entries: list[tuple[Action, np.ndarray]]) -> Distribution:
    """Sum arrays whose keys resolve to the same Action; always returns fresh arrays."""
    out: Distribution = {}
    for a, arr in entries:
        if a in out:
            out[a] = out[a] + arr
        else:
            out[a] = np.array(arr, dtype=np.float64, copy=True)
    return out


def _rest(*arrays: np.ndarray) -> np.ndarray:
    return np.clip(1.0 - np.sum(arrays, axis=0), 0.0, 1.0)


def _preflop(profile: Profile, s: HandState) -> Distribution:
    pf = profile.preflop
    me = s.to_act
    lg = _legal(s)
    acts = [a for a in s.history if a.street == Street.PREFLOP]
    raises = all(a.kind == ActionKind.RAISE for a in acts)
    alternating = all(
        a.seat == (s.button if i % 2 == 0 else 1 - s.button) for i, a in enumerate(acts)
    )
    # Facing a jam: the last raise left the seat to act unable to raise (raiser all-in, or
    # the raise reached the effective stack cap).
    jam = lg.aggressive is None
    if not (raises and alternating):
        raise UnsupportedSpot(f"unsupported pre-flop line: {[a.kind.value for a in acts]}")

    n = len(acts)
    if n == 0 and me == s.button:
        if lg.aggressive != ActionKind.RAISE:
            raise UnsupportedSpot("button cannot open")
        return _merge([(_fold(s), _rest(pf.open)), (raise_to(s, OPEN_MULT), pf.open)])
    if n == 1:  # BB facing the open
        if jam:
            return _merge(
                [(_fold(s), _rest(pf.bb_call_open_jam)), (_call(s, lg), pf.bb_call_open_jam)]
            )
        return _merge(
            [
                (_fold(s), _rest(pf.bb_call, pf.bb_threebet)),
                (_call(s, lg), pf.bb_call),
                (raise_to(s, THREEBET_MULT), pf.bb_threebet),
            ]
        )
    if n == 2:  # BTN facing the 3-bet
        if jam:
            return _merge([(_fold(s), _rest(pf.btn_call_jam)), (_call(s, lg), pf.btn_call_jam)])
        return _merge(
            [
                (_fold(s), _rest(pf.btn_call_threebet, pf.btn_jam)),
                (_call(s, lg), pf.btn_call_threebet),
                (allin(s), pf.btn_jam),
            ]
        )
    if n == 3 and jam:  # BB facing the 4-bet jam
        return _merge([(_fold(s), _rest(pf.bb_call_jam)), (_call(s, lg), pf.bb_call_jam)])
    raise UnsupportedSpot(f"unsupported pre-flop spot after {n} raises")


@lru_cache(maxsize=1)
def _thresholds():
    return load_thresholds()


@lru_cache(maxsize=256)
def _row_index(board: tuple[int, ...]) -> np.ndarray:
    """Per-combo row into a (8, k) table: category, or the all-zero row for blocked combos."""
    cats = categorize(range_features(board), _thresholds())
    out = np.where(cats < 0, _BLOCKED_ROW, cats).astype(np.intp)
    out.flags.writeable = False
    return out


def _matrix(table: Table, keys: tuple[str, ...]) -> np.ndarray:
    """(8, len(keys)) probabilities; row 7 is all zero (board-blocked combos)."""
    m = np.zeros((_BLOCKED_ROW + 1, len(keys)))
    for cat in HandCategory:
        m[int(cat)] = [table[cat][k] for k in keys]
    return m


def _damping() -> Damping:
    """The multiway damping constants (``fivemax.json`` ``damping``)."""
    from poker_trainer.villain import preflop5  # imports this module: keep it lazy

    return preflop5.load_fivemax().damping


def _extra_opponents(s: HandState) -> int:
    """k = live opponents - 1 for the seat to act; all-in opponents count. 0 heads-up."""
    return len(live_seats(s)) - 2


def _scale(m: np.ndarray, rows: list[int], cols: slice | int, factor: float, to: int) -> None:
    """Multiply ``m[rows, cols]`` by ``factor`` in place and move the removed mass to column ``to``."""
    before = m[rows, cols]
    after = before * factor
    removed = before - after
    m[rows, cols] = after
    m[rows, to] += removed.sum(axis=1) if removed.ndim == 2 else removed


def _damp_unopened(m: np.ndarray, k: int) -> None:
    """Multiway: bluff bets x bluff^k, MEDIUM's thin bets x thin^k; the removed mass checks."""
    d = _damping()
    _scale(m, _BLUFF_ROWS, slice(1, None), d.bluff**k, 0)
    _scale(m, [_THIN_ROW], slice(1, None), d.thin**k, 0)


def _damp_facing(m: np.ndarray, k: int, committed: bool) -> None:
    """Multiway facing a bet: MEDIUM's raise -> call, bluff raises x bluff^k, then continuing
    (call + raise) below STRONG x call^k; the removed mass folds. ``committed`` (low SPR) skips
    the ``_COMMITTED`` rows, which the low-SPR step then handles as heads-up."""
    d = _damping()
    skip = {int(c) for c in _COMMITTED} if committed else set()
    if _THIN_ROW not in skip:
        m[_THIN_ROW, 1] += m[_THIN_ROW, 2]
        m[_THIN_ROW, 2] = 0.0
    _scale(m, [r for r in _BLUFF_ROWS if r not in skip], 2, d.bluff**k, 0)
    _scale(m, [r for r in _BELOW_STRONG if r not in skip], slice(1, None), d.call**k, 0)


def _unopened(
    profile: Profile, s: HandState, r: str, lg: Legal, k: int = 0
) -> list[tuple[Action, np.ndarray]]:
    m = _matrix(profile.unopened[r], UNOPENED_ACTIONS)  # check, bet_33, bet_75
    if s.street == Street.RIVER:
        for cat, row in profile.river_unopened.get(r, {}).items():
            m[int(cat)] = [row[key] for key in UNOPENED_ACTIONS]
    if board_texture(s.board).wet:
        rows = [int(c) for c in _DRAWS]
        m[rows, 1:] *= _DRAW_BET_BOOST
        m[rows] /= m[rows].sum(axis=1, keepdims=True)
    if k > 0:
        _damp_unopened(m, k)
    rows = _row_index(s.board)
    check = _check(s)
    can_bet = lg.aggressive == ActionKind.BET
    entries = [(check, m[rows, 0])]
    for col, frac in ((1, 0.33), (2, 0.75)):
        entries.append((bet_to(s, frac) if can_bet else check, m[rows, col]))
    return entries


def _continue(base: np.ndarray, f: float) -> np.ndarray:
    """Continue (call + raise) probability per category row facing a bet of ``f`` x pot."""
    if f <= 1.0:
        return base ** ((1.0 + f) / 1.5)
    mdf_scale = 2.0 / (1.0 + f)  # MDF here / MDF facing a pot-size bet
    cont = base ** (4.0 / 3.0) * mdf_scale**_OVERBET_POWER
    # STRONG keeps the gentle curve up to _STRONG_BEND x pot, then shrinks with MDF.
    strong = int(HandCategory.STRONG)
    bend = min(f, _STRONG_BEND)
    gentle = base[strong] ** ((1.0 + bend) / 1.5) * ((1.0 + bend) / (1.0 + f)) ** _STRONG_POWER
    cont[strong] = max(gentle, _STRONG_FLOOR)
    return cont


def _facing(
    profile: Profile, s: HandState, r: str, lg: Legal, k: int = 0
) -> list[tuple[Action, np.ndarray]]:
    m = _matrix(profile.facing[r], FACING_ACTIONS)  # fold, call, raise
    if s.street == Street.RIVER:
        for cat, row in profile.river_facing.get(r, {}).items():
            m[int(cat)] = [row[key] for key in FACING_ACTIONS]
    f = lg.call / (total_pot(s) - lg.call)
    base = m[:, 1] + m[:, 2]
    cont = _continue(base, f)
    share = np.divide(cont, base, out=np.zeros_like(base), where=base > 0)
    m[:, 1] *= share
    m[:, 2] *= share
    m[:, 0] = 1.0 - cont
    m[_BLOCKED_ROW] = 0.0
    low_spr = street_spr(s) <= _LOW_SPR
    if k > 0:
        _damp_facing(m, k, committed=low_spr)
    if lg.aggressive != ActionKind.RAISE:
        m[:, 1] += m[:, 2]
        m[:, 2] = 0.0
    if low_spr:
        rows = [int(c) for c in _COMMITTED]
        m[rows, 1] += m[rows, 0]
        m[rows, 0] = 0.0
    rows = _row_index(s.board)
    call = _call(s, lg)
    raise_ = raise_to(s, RAISE_MULT) if lg.aggressive == ActionKind.RAISE else call
    return [(_fold(s), m[rows, 0]), (call, m[rows, 1]), (raise_, m[rows, 2])]


def action_distribution(profile: Profile, s: HandState) -> Distribution:
    """Per-combo probability of each legal action for the seat to act.

    Arrays are ``(1326,)``; for every combo not blocked by the board they sum to 1, and
    board-blocked combos are 0 everywhere. Pre-flop nothing is blocked. Pre-flop, two seats use
    the per-combo heads-up tables and five seats the 5-max ranking policy (``preflop5``); any
    other table size raises ``UnsupportedSpot``. Post-flop the heads-up tables are used at any
    table size; with k = live opponents - 1 > 0 (all-in opponents count) they are damped first
    (``_damp_unopened`` / ``_damp_facing``, constants in ``fivemax.json``). k = 0 never touches
    them, so heads-up (and a multiway hand down to two live seats) is the heads-up policy.
    """
    lg = _legal(s)
    if s.street == Street.PREFLOP:
        n = len(s.stacks)
        if n == 2:
            return _preflop(profile, s)
        if n != 5:
            raise UnsupportedSpot(f"no pre-flop policy for {n} seats")
        from poker_trainer.villain import preflop5  # imports this module: keep it lazy

        fm = preflop5.load_fivemax()
        block = fm.profiles.get(profile.name)
        if block is None:
            raise UnsupportedSpot(f"no 5-max pre-flop block for profile {profile.name!r}")
        return preflop5.distribution(fm, block, s)
    return _postflop(profile, s, lg, _extra_opponents(s))


def _postflop(profile: Profile, s: HandState, lg: Legal, k: int) -> Distribution:
    """The post-flop policy with multiway damping ``k`` (live opponents - 1; 0 is heads-up)."""
    r = role(s)
    build = _facing if r.startswith("facing") else _unopened
    return _merge(build(profile, s, r, lg, k))


class _Uniform(Protocol):
    def random(self) -> float: ...


def sample_action(profile: Profile, s: HandState, hole: tuple[int, int], rng: _Uniform) -> Action:
    """Sample the seat-to-act's action for its actual hole cards (deterministic given rng)."""
    ensure_distinct(tuple(hole), s.board)
    i = combo_index(*hole)
    dist = action_distribution(profile, s)
    weights = [(a, float(arr[i])) for a, arr in dist.items() if arr[i] > 0.0]
    if not weights:
        raise ValueError(f"no action has positive probability for hole {hole}")
    u = rng.random() * sum(w for _, w in weights)
    acc = 0.0
    for a, w in weights:
        acc += w
        if u < acc:
            return a
    return weights[-1][0]
