"""The single Villain policy: shared bet sizing, per-combo action distributions, sampling.

``action_distribution`` is the one source of truth. It generates the Villain's line
(``sample_action``), narrows its range from observed actions, and predicts its responses
to Hero's bets. Every key of a distribution is a concrete legal ``Action``; table keys
that resolve to the same ``Action`` (two sizes clamped to the same chips) are merged.
"""

from __future__ import annotations

import random
from functools import lru_cache

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
    UNOPENED_ACTIONS,
    Profile,
    Table,
)

ALLIN_FRACTION = 0.6
OPEN_MULT = 2.5
THREEBET_MULT = 3.0
RAISE_MULT = 3.0
HERO_PROFILE = "tag"

N_COMBOS = 1326
_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)
_DRAWS = (HandCategory.WEAK_DRAW, HandCategory.STRONG_DRAW)
_DRAW_BET_BOOST = 1.25
_LOW_SPR = 1.0
_COMMITTED = (HandCategory.MEDIUM, HandCategory.STRONG_DRAW, HandCategory.STRONG, HandCategory.NUTS)
_BLOCKED_ROW = len(HandCategory)  # extra all-zero table row used for board-blocked combos

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


def _unopened(profile: Profile, s: HandState, r: str, lg: Legal) -> list[tuple[Action, np.ndarray]]:
    m = _matrix(profile.unopened[r], UNOPENED_ACTIONS)  # check, bet_33, bet_75
    if board_texture(s.board).wet:
        rows = [int(c) for c in _DRAWS]
        m[rows, 1:] *= _DRAW_BET_BOOST
        m[rows] /= m[rows].sum(axis=1, keepdims=True)
    rows = _row_index(s.board)
    check = _check(s)
    can_bet = lg.aggressive == ActionKind.BET
    entries = [(check, m[rows, 0])]
    for col, frac in ((1, 0.33), (2, 0.75)):
        entries.append((bet_to(s, frac) if can_bet else check, m[rows, col]))
    return entries


def _facing(profile: Profile, s: HandState, r: str, lg: Legal) -> list[tuple[Action, np.ndarray]]:
    m = _matrix(profile.facing[r], FACING_ACTIONS)  # fold, call, raise
    f = lg.call / (total_pot(s) - lg.call)
    base = m[:, 1] + m[:, 2]
    cont = base ** ((1.0 + f) / 1.5)
    share = np.divide(cont, base, out=np.zeros_like(base), where=base > 0)
    m[:, 1] *= share
    m[:, 2] *= share
    m[:, 0] = 1.0 - cont
    m[_BLOCKED_ROW] = 0.0
    if lg.aggressive != ActionKind.RAISE:
        m[:, 1] += m[:, 2]
        m[:, 2] = 0.0
    if street_spr(s) <= _LOW_SPR:
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
    board-blocked combos are 0 everywhere. Pre-flop nothing is blocked.
    """
    lg = _legal(s)
    if s.street == Street.PREFLOP:
        return _preflop(profile, s)
    r = role(s)
    entries = _facing(profile, s, r, lg) if r.startswith("facing") else _unopened(profile, s, r, lg)
    return _merge(entries)


def sample_action(
    profile: Profile, s: HandState, hole: tuple[int, int], rng: random.Random
) -> Action:
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
