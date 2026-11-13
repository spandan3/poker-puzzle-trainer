"""EV of every Hero option against Villain's displayed range, relative to folding.

Villain's responses come only from an injected ``respond`` callable; in production that
is ``villain_respond(profile)``, i.e. the shared ``action_distribution``. Every number is
computed from the displayed range ``D`` (already the visible range) and one
``ComboEquity`` table re-weighted to sub-ranges. Formulas: "Option EVs" in the M3 plan.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import numpy as np

from poker_trainer.engine.combos import COMBOS
from poker_trainer.engine.equity import (
    ComboEquity,
    EquityResult,
    UnsampledRange,
    ahead_now,
    combo_equity,
    equity_vs_range,
)
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.engine.ranges import Range
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    legal_actions,
    pot_odds,
    total_pot,
)
from poker_trainer.puzzle.model import (
    Branch,
    CategoryRow,
    Option,
    OptionEV,
    Solution,
    load_config,
)
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.features import (
    HandCategory,
    categorize,
    load_thresholds,
    range_features,
)
from poker_trainer.villain.profiles import Profile
from poker_trainer.villain.strategy import UnsupportedSpot, action_distribution

Respond = Callable[[HandState], dict[Action, np.ndarray]]

_AGGRESSIVE = (ActionKind.BET, ActionKind.RAISE)
_DEFAULT_SAMPLES = 40_000
_EMPTY = 1e-12  # a continuing range at or below this total weight counts as empty
_SUM_ATOL = 1e-9


def villain_respond(profile: Profile) -> Respond:
    """The production ``respond``: Villain's per-combo strategy on the post-action state."""
    return lambda s: action_distribution(profile, s)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _total(w: np.ndarray) -> float:
    return math.fsum(w)


def _eq(
    ce: ComboEquity, hero: tuple[int, int], board: tuple[int, ...], w: np.ndarray, samples: int
) -> EquityResult | None:
    """Hero's equity vs sub-range ``w`` of ``ce.base``; None for an empty sub-range."""
    if _total(w) <= 0.0:
        return None
    try:
        return ce.vs(w)
    except UnsampledRange:
        return equity_vs_range(hero, board, w, rng=random.Random(0), samples=max(1, samples // 4))


def _ahead(
    ce: ComboEquity,
    hero: tuple[int, int],
    board: tuple[int, ...],
    w: np.ndarray,
    samples: int,
) -> float | None:
    """Ahead-now share of ``w`` (equity on the river); None for an empty sub-range."""
    if _total(w) <= 0.0:
        return None
    if len(board) == 5:
        r = _eq(ce, hero, board, w, samples)
        return None if r is None else float(r.equity)
    return float(ahead_now(hero, board, w))


def _read_only(a: np.ndarray) -> np.ndarray:
    out = np.array(a, dtype=np.float64, copy=True)
    out.setflags(write=False)
    return out


def _label_for(s: HandState, action: Action) -> str:
    try:
        for o in hero_options(s):
            if o.action == action:
                return o.label
    except UnsupportedSpot:
        pass
    if action.kind == ActionKind.BET:
        return f"bet {action.to}"
    if action.kind == ActionKind.RAISE:
        return f"raise to {action.to}"
    return action.kind.value


def _check_respond(d: np.ndarray, dist: dict[Action, np.ndarray]) -> None:
    """Villain's response arrays must sum to 1 on every combo of ``d``."""
    total = np.zeros_like(d)
    for arr in dist.values():
        total = total + np.asarray(arr, dtype=np.float64)
    live = d > 0.0
    if not np.allclose(total[live], 1.0, rtol=0.0, atol=_SUM_ATOL):
        worst = float(np.max(np.abs(total[live] - 1.0)))
        raise ValueError(f"respond arrays do not sum to 1 on the range (max error {worst:.3g})")


def _reply(call_value: float, floor: float) -> tuple[str, float]:
    """Hero's better reply (call or fold) to a Villain bet or raise."""
    return ("calls", call_value) if call_value > floor else ("folds", floor)


def realisation(street: Street, in_position: bool, all_in: bool) -> float:
    """Share of equity Hero realises in a pot that is still open after the decision street.

    1.0 on the river or when no betting is left (a player is all-in); otherwise the
    configured ``(in position, out of position)`` factor for the street.
    """
    if street == Street.RIVER or all_in:
        return 1.0
    ip, oop = load_config().realisation[street]
    return ip if in_position else oop


def _all_in(s: HandState) -> bool:
    """No betting is left: a player has no chips behind."""
    return min(s.stacks) == 0


def _r(s: HandState, after: HandState) -> float:
    """Factor for Hero (``s.to_act``, deciding in ``s``) once the hand reaches ``after``."""
    return realisation(s.street, s.to_act == s.button, _all_in(after))


# ---------------------------------------------------------------------------
# Option EVs
# ---------------------------------------------------------------------------


def evaluate_action(
    s: HandState,
    hero: tuple[int, int],
    D: Range,
    ce: ComboEquity,
    action: Action,
    respond: Respond,
    *,
    label: str | None = None,
    samples: int = _DEFAULT_SAMPLES,
) -> OptionEV:
    """EV in chips (fold = 0) of Hero taking ``action`` in ``s`` against range ``D``.

    ``samples`` only sizes the deterministic fallback for an unsampled sub-range.
    """
    if s.to_act is None:
        raise ValueError("no player to act")
    me = s.to_act
    option = Option(label if label is not None else _label_for(s, action), action)
    board = tuple(s.board)
    d = np.asarray(D, dtype=np.float64)
    size = _total(d)
    if size <= 0.0:
        raise ValueError("empty range")
    P = total_pot(s)
    preriver = s.street < Street.RIVER
    eq_all = _eq(ce, hero, board, d, samples)
    if eq_all is None:
        raise ValueError("empty range")
    eq = float(eq_all.equity)

    def plain(ev: float, put: int, codes: tuple[str, ...], r: float = 1.0) -> OptionEV:
        return OptionEV(
            option=option,
            ev_chips=float(ev),
            fold_freq=None,
            equity_vs_continue=None,
            ahead_vs_continue=None,
            equity_vs_continue_se=None,
            required_fold_equity=None,
            put=int(put),
            continue_range=None,
            branches=(),
            simplifications=codes,
            realisation=float(r),
        )

    realised = ("realisation_position",) if preriver else ()

    if action.kind == ActionKind.FOLD:
        return plain(0.0, 0, ())

    if action.kind == ActionKind.CALL:
        put = action.to - s.street_bets[me]
        r = _r(s, apply(s, action))
        return plain(r * eq * (P + put) - put, put, realised, r)

    if action.kind == ActionKind.CHECK:
        s2 = apply(s, action)
        # Out of position: the street stays open and Villain acts next on it.
        oop = s2.to_act is not None and s2.street == s.street
        if preriver or s2.to_act is None:
            codes = ("check_reply", *realised) if oop else realised
            r = _r(s, s2)
            return plain(r * eq * P, 0, codes, r)
        return _river_check_lookahead(s2, hero, d, size, ce, option, respond, P, samples)

    if action.kind in _AGGRESSIVE:
        return _bet_or_raise(s, hero, d, size, ce, option, respond, P, samples)

    raise ValueError(f"unknown action kind: {action.kind}")


def _river_check_lookahead(
    s2: HandState,
    hero: tuple[int, int],
    d: np.ndarray,
    size: float,
    ce: ComboEquity,
    option: Option,
    respond: Respond,
    P: int,
    samples: int,
) -> OptionEV:
    """Hero checks OOP on the river; Villain checks back or bets, Hero then folds or calls."""
    board = tuple(s2.board)
    dist = respond(s2)
    _check_respond(d, dist)
    ev = 0.0
    branches: list[Branch] = []
    for key, arr in dist.items():
        w = d * np.asarray(arr, dtype=np.float64)
        share = _total(w) / size
        if share <= 0.0:
            continue
        r = _eq(ce, hero, board, w, samples)
        if r is None:
            raise ValueError(f"empty sub-range for Villain response {key}")
        e = float(r.equity)
        if key.kind == ActionKind.CHECK:
            v = e * P
            lab = "Villain checks back"
        elif key.kind == ActionKind.BET:
            b = key.to
            how, v = _reply(e * (P + 2 * b) - b, 0.0)
            lab = f"Villain bets {b} — Hero {how}"
        else:
            raise ValueError(f"unexpected Villain response to a check: {key}")
        ev += share * v
        branches.append(Branch(lab, float(share), e, float(v)))
    return OptionEV(
        option=option,
        ev_chips=float(ev),
        fold_freq=None,
        equity_vs_continue=None,
        ahead_vs_continue=None,
        equity_vs_continue_se=None,
        required_fold_equity=None,
        put=0,
        continue_range=None,
        branches=tuple(branches),
        simplifications=("check_reply",),
    )


def _bet_or_raise(
    s: HandState,
    hero: tuple[int, int],
    d: np.ndarray,
    size: float,
    ce: ComboEquity,
    option: Option,
    respond: Respond,
    P: int,
    samples: int,
) -> OptionEV:
    action = option.action
    me = action.seat
    board = tuple(s.board)
    put = action.to - s.street_bets[me]
    s2 = apply(s, action)
    dist = respond(s2)
    _check_respond(d, dist)

    fold_arr = np.zeros_like(d)
    for key, arr in dist.items():
        if key.kind == ActionKind.FOLD:
            fold_arr = fold_arr + np.asarray(arr, dtype=np.float64)
    F = _total(d * fold_arr) / size
    c_all = d * (1.0 - fold_arr)
    c_all = np.where(c_all > 0.0, c_all, 0.0)
    never_continues = _total(c_all) <= _EMPTY
    eq_c = None if never_continues else _eq(ce, hero, board, c_all, samples)
    ahead_c = None if never_continues else _ahead(ce, hero, board, c_all, samples)

    codes: set[str] = set()
    if s.street < Street.RIVER:
        codes.add("realisation_position")
    if s.street == Street.PREFLOP and action.kind == ActionKind.RAISE:
        codes.add("preflop_size")

    branches: list[Branch] = []
    if F > 0.0:
        branches.append(Branch("Villain folds", float(F), None, float(P)))
    ev = F * P
    for key, arr in dist.items():
        if key.kind == ActionKind.FOLD:
            continue
        w = d * np.asarray(arr, dtype=np.float64)
        share = _total(w) / size
        if share <= 0.0:
            continue
        r = _eq(ce, hero, board, w, samples)
        if r is None:
            raise ValueError(f"empty sub-range for Villain response {key}")
        e = float(r.equity)
        if key.kind == ActionKind.CALL:
            vcall = legal_actions(s2).call
            r_b = _r(s, apply(s2, key))
            v = r_b * e * (P + put + vcall) - put
            lab = "Villain calls"
        elif key.kind in _AGGRESSIVE:
            codes.add("reraise_reply")
            s3 = apply(s2, key)
            c = legal_actions(s3).call
            final = total_pot(s3) + c
            hero_call = Action(me, ActionKind.CALL, s3.street, s3.street_bets[me] + c)
            r_call = _r(s, apply(s3, hero_call))
            how, v = _reply(r_call * e * final - (put + c), float(-put))
            r_b = r_call if how == "calls" else 1.0  # folding realises nothing
            lab = f"Villain raises to {key.to} — Hero {how}"
        else:
            raise ValueError(f"unexpected Villain response to a bet: {key}")
        ev += share * v
        branches.append(Branch(lab, float(share), e, float(v), float(r_b)))

    if never_continues:
        F = 1.0
        ev = float(P)
        branches = [Branch("Villain folds", 1.0, None, float(P))]

    return OptionEV(
        option=option,
        ev_chips=float(ev),
        fold_freq=float(F),
        equity_vs_continue=None if eq_c is None else float(eq_c.equity),
        ahead_vs_continue=ahead_c,
        equity_vs_continue_se=None if eq_c is None else float(eq_c.std_error),
        required_fold_equity=float(put / (P + put)),
        put=int(put),
        continue_range=_read_only(c_all),
        branches=tuple(branches),
        simplifications=tuple(sorted(codes)),
    )


# ---------------------------------------------------------------------------
# Solve
# ---------------------------------------------------------------------------


def _category_breakdown(
    s: HandState, hero: tuple[int, int], d: np.ndarray, ce: ComboEquity, samples: int
) -> tuple[CategoryRow, ...] | None:
    if s.street == Street.PREFLOP:
        return None
    board = tuple(s.board)
    cats = categorize(range_features(board), load_thresholds())
    size = _total(d)
    # Per combo, by made hand now: +1 Hero wins, 0 tie, -1 Hero loses.
    dead = {*hero, *board}
    h = evaluate((*hero, *board))
    outcome = np.zeros(len(d), dtype=np.int8)
    for i in np.flatnonzero(d > 0.0):
        a, b = COMBOS[i]
        if a in dead or b in dead:
            raise ValueError(f"range has weight on a blocked combo: {COMBOS[i]}")
        v = evaluate((a, b, *board))
        outcome[i] = 1 if h < v else (0 if h == v else -1)
    rows: list[CategoryRow] = []
    for cat in sorted(HandCategory, reverse=True):
        w = np.where(cats == int(cat), d, 0.0)
        tot = _total(w)
        if tot <= 0.0:
            continue
        r = _eq(ce, hero, board, w, samples)
        ahead = _ahead(ce, hero, board, w, samples)
        if r is None or ahead is None:
            raise ValueError(f"empty sub-range for category {cat.name.lower()}")
        win = _total(w[outcome == 1]) / tot
        tie = _total(w[outcome == 0]) / tot
        rows.append(
            CategoryRow(
                category=cat.name.lower(),
                share=float(tot / size),
                ahead=float(ahead),
                equity=float(r.equity),
                win=float(win),
                tie=float(tie),
                lose=float(_total(w[outcome == -1]) / tot),
            )
        )
    return tuple(rows)


def solve(
    s: HandState,
    hero: tuple[int, int],
    D: Range,
    respond: Respond,
    *,
    rng: random.Random | None,
    samples: int = _DEFAULT_SAMPLES,
) -> Solution:
    """Equity, ahead-now, pot odds, every Hero option's EV, and the category breakdown."""
    board = tuple(s.board)
    d = np.asarray(D, dtype=np.float64)
    ce = combo_equity(hero, board, d, rng=rng, samples=samples)
    eq = ce.vs(d)
    ahead = None if s.street == Street.RIVER else float(ahead_now(hero, board, d))
    options = tuple(
        evaluate_action(s, hero, d, ce, o.action, respond, label=o.label, samples=samples)
        for o in hero_options(s)
    )
    best = max(range(len(options)), key=lambda i: options[i].ev_chips)
    codes = sorted({c for o in options for c in o.simplifications})
    has_call = any(o.option.action.kind == ActionKind.CALL for o in options)
    return Solution(
        equity=float(eq.equity),
        equity_std_error=float(eq.std_error),
        equity_exact=bool(eq.exact),
        ahead_now=ahead,
        pot_odds=float(pot_odds(s)) if has_call else 0.0,  # no call offered: no pot odds
        options=options,
        best=int(best),
        combo_equity=ce,
        category_breakdown=_category_breakdown(s, hero, d, ce, samples),
        simplifications=tuple(codes),
    )
