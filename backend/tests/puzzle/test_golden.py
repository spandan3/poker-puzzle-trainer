"""Golden hand-worked spots (spec §12A): the grader's main accuracy guarantee.

Every spot is built from an explicit legal ``HandState`` line, an explicit small Villain
range and an injected ``respond`` with explicit per-combo arrays. The expected pot odds,
fold frequency (F), branch shares, equities and EV per option were worked out by hand
(the working is in the comment above each test); they were not copied from the code.

Notation (all chips): P = total pot at the decision, put = chips Hero adds, vcall = chips
Villain needs to call Hero's bet/raise, |D| = total weight of Villain's range,
eq(X) = Hero's equity vs sub-range X. Option EV formulas: "Option EVs" in the M3 plan.

* River and turn equities are worked out by hand (exact), compared to 1e-9.
* Flop equities come from ``reference.exact_flop`` (full turn+river enumeration); the
  code's Monte Carlo is compared with a 4·SE tolerance (the reference is exact, SE 0).
* Pre-flop equities come from exact enumeration of all 1,712,304 boards per matchup
  (``exact_preflop`` below, cross-checked against pokerkit); 4·SE tolerance. These are
  ``slow`` because each matchup enumerates ~1.7M boards.

EV tolerance for MC spots: EV = const + Σ k_i·eq_i, so tol = 4·Σ|k_i|·SE_i (a
conservative linear sum, since the branch estimates share samples).
"""

from __future__ import annotations

import functools
import itertools
import math
import random

import numpy as np
import pytest
from reference.exact_flop import exact_flop_reference

from poker_trainer.engine.cards import card_str, parse_cards
from poker_trainer.engine.combos import COMBOS, combo_index
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.engine.ranges import parse_range
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    apply,
    deal,
    legal_actions,
    new_hand,
    total_pot,
)
from poker_trainer.puzzle.model import Solution, visible_range
from poker_trainer.puzzle.solve import solve
from poker_trainer.villain.strategy import allin, bet_to, raise_to

N = len(COMBOS)
EXACT = 1e-9


# ---------------------------------------------------------------------------
# Helpers: lines, ranges, respond
# ---------------------------------------------------------------------------


def cards(s: str) -> tuple[int, ...]:
    return tuple(parse_cards(s))


def idx(name: str) -> int:
    a, b = parse_cards(name)
    return combo_index(a, b)


def check_of(s: HandState) -> Action:
    return Action(s.to_act, ActionKind.CHECK, s.street)


def fold_of(s: HandState) -> Action:
    return Action(s.to_act, ActionKind.FOLD, s.street)


def call_of(s: HandState) -> Action:
    me = s.to_act
    return Action(me, ActionKind.CALL, s.street, s.street_bets[me] + legal_actions(s).call)


def chk(s: HandState) -> HandState:
    return apply(s, check_of(s))


def opened(stacks: tuple[int, int] = (200, 200)) -> HandState:
    """BTN (seat 0) raises to 5, BB (seat 1) calls: P = 10 at the flop."""
    s = new_hand(0, stacks)
    s = apply(s, raise_to(s, 2.5))
    assert s.history[-1].to == 5
    return apply(s, call_of(s))


def flop(board: tuple[int, ...], stacks: tuple[int, int] = (200, 200)) -> HandState:
    """BB (seat 1) to act first on the flop."""
    return deal(opened(stacks), board[:3])


def turn(board: tuple[int, ...]) -> HandState:
    """Flop checked through; BB to act on the turn, P = 10."""
    return deal(chk(chk(flop(board))), board[3:4])


def river(board: tuple[int, ...]) -> HandState:
    """Flop and turn checked through; BB to act on the river, P = 10."""
    return deal(chk(chk(turn(board))), board[4:5])


def vrange(text: str, hero: tuple[int, ...], board: tuple[int, ...]) -> np.ndarray:
    return visible_range(parse_range(text), hero, board)


def sub(D: np.ndarray, *names: str) -> np.ndarray:
    """D restricted to the named combos (weights kept)."""
    w = np.zeros(N)
    for n in names:
        w[idx(n)] = D[idx(n)]
    return w


def responder(D: np.ndarray, table):
    """``respond`` from ``table(s2) -> [(canonical Action, {combo: prob})]``.

    Checks that the arrays sum to 1 on every live combo of D.
    """

    def respond(s2: HandState) -> dict[Action, np.ndarray]:
        out: dict[Action, np.ndarray] = {}
        for action, probs in table(s2):
            if not probs:
                continue
            assert action not in out
            a = np.zeros(N)
            for name, p in probs.items():
                a[idx(name)] = p
            out[action] = a
        total = np.sum(list(out.values()), axis=0)
        live = np.asarray(D) > 0
        assert np.allclose(total[live], 1.0, rtol=0, atol=1e-12), "respond must sum to 1"
        return out

    return respond


def facing(s2: HandState, fold: dict, call: dict, raises=()) -> list:
    """Villain facing Hero's bet or raise: fold / call / explicit raise keys."""
    return [(fold_of(s2), fold), (call_of(s2), call), *raises]


def never(s2: HandState):
    raise AssertionError("respond must not be called for fold/call options")


def by_label(sol: Solution) -> dict:
    return {o.option.label: o for o in sol.options}


def assert_evs(sol: Solution, want: dict[str, float]) -> None:
    """Every option is listed, in order, and each EV matches to 1e-9."""
    got = by_label(sol)
    assert list(got) == list(want)
    for label, ev in want.items():
        assert got[label].ev_chips == pytest.approx(ev, abs=EXACT), label


def solve_exact(s, hero, D, respond) -> Solution:
    sol = solve(s, hero, D, respond, rng=random.Random(0), samples=10)
    assert sol.equity_exact
    return sol


# ---------------------------------------------------------------------------
# River (8 spots). Board Ks 7h 2c 4d 9s; line: BTN opens to 5, BB calls, flop and turn
# checked through, so P = 10 entering the river and both stacks are 195.
#
# Showdowns vs Hero KhQh (pair of kings, Q kicker):
#   AsKd (K, A kicker) wins -> eq 0;   7c7d (set) wins -> eq 0;
#   KcQc identical ranks -> tie, eq 1/2;
#   JcTc / QcJc (high card) lose -> eq 1;  KcJd (K, J kicker) loses -> eq 1.
# Showdowns vs Hero 6h5h (K-9-7-6-5 high, no straight: needs 3 or 8):
#   AsKd, JcTc (K J T 9 7), QcJc, KcJd, 3c3d (pair) all win -> Hero eq 0.
# ---------------------------------------------------------------------------

RB = cards("Ks7h2c4d9s")
KQ = cards("KhQh")
H65 = cards("6h5h")


def river_facing(frac: float) -> HandState:
    r = river(RB)
    return apply(r, bet_to(r, frac))


# R1 river call, weighted range with a tie. BB bets 8 (75% of 10); Hero (BTN) KhQh.
#   P = 18, call put 8, pot odds 8/26.
#   D = AsKd 1, JcTc .5, KcQc 1, 7c7d .5; |D| = 3.
#   eq(D) = (0·1 + 1·.5 + .5·1 + 0·.5)/3 = 1/3.
#   call = (1/3)(18+8) − 8 = 26/3 − 8 = 2/3.
#   Villain vs a raise: AsKd, 7c7d call; JcTc, KcQc fold.  F = (.5+1)/3 = 1/2,
#   C = {AsKd, 7c7d}, eq(C) = 0.
#   raise 2.5x to 20: put 20, vcall 12: 1/2·18 + 1/2·(0·50 − 20) = 9 − 10 = −1.
#   raise 3x to 24: 9 − 12 = −3.   all-in 195: 9 − 195/2 = −88.5.
def test_r1_river_call_tie_and_weights():
    s = river_facing(0.75)
    assert s.history[-1].to == 8 and total_pot(s) == 18 and s.to_act == 0
    D = vrange("AsKd, JcTc:0.5, KcQc, 7c7d:0.5", KQ, RB)

    def table(s2):
        return facing(s2, fold={"JcTc": 1, "KcQc": 1}, call={"AsKd": 1, "7c7d": 1})

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(1 / 3, abs=EXACT)
    assert sol.pot_odds == pytest.approx(8 / 26, abs=EXACT)
    assert_evs(
        sol,
        {"fold": 0.0, "call": 2 / 3, "raise 2.5x": -1.0, "raise 3x": -3.0, "all-in": -88.5},
    )
    o = by_label(sol)
    assert [o[k].option.action.to for k in ("raise 2.5x", "raise 3x", "all-in")] == [20, 24, 195]
    assert o["call"].put == 8
    assert o["raise 2.5x"].fold_freq == pytest.approx(0.5, abs=EXACT)
    assert o["raise 2.5x"].equity_vs_continue == pytest.approx(0.0, abs=EXACT)
    assert o["raise 2.5x"].required_fold_equity == pytest.approx(20 / 38, abs=EXACT)
    assert sol.options[sol.best].option.label == "call"
    assert o["call"].simplifications == ()


# R2 river value bet, size-dependent calls. BB checks; Hero (BTN) KhQh in position, P = 10.
#   D = AsKd .5, KcJd 1, JcTc 1, QcJc 1; |D| = 3.5.
#   eq(D) = (0·.5 + 1 + 1 + 1)/3.5 = 6/7.  check (closes the river) = 6/7·10 = 60/7.
#   Villain vs bet to t: AsKd always calls; KcJd calls t <= 5; QcJc calls t <= 3;
#   JcTc folds.  Bet sizes: 33% -> 3, 50% -> 5, 75% -> 8, 100% -> 10, all-in 195.
#   bet 3:  C = AsKd .5, KcJd 1, QcJc 1 (2.5), F = 1/3.5 = 2/7, eq(C) = 2/2.5 = .8;
#           2/7·10 + 5/7·(.8·16 − 3) = 20/7 + 5/7·9.8 = 20/7 + 49/7 = 69/7.
#   bet 5:  C = AsKd .5, KcJd 1 (1.5), F = 4/7, eq(C) = 1/1.5 = 2/3;
#           40/7 + 3/7·(2/3·20 − 5) = 40/7 + 3/7·25/3 = 65/7.
#   bet 8:  C = AsKd .5, F = 6/7, eq 0: 60/7 − 8/7 = 52/7.
#   bet 10: 60/7 − 10/7 = 50/7.   all-in: 60/7 − 195/7 = −135/7.
def test_r2_river_value_bet_sizing():
    s = chk(river(RB))
    assert total_pot(s) == 10 and s.to_act == 0
    D = vrange("AsKd:0.5, KcJd, JcTc, QcJc", KQ, RB)
    assert D.sum() == pytest.approx(3.5)

    def table(s2):
        t = max(s2.street_bets)
        callers = {"AsKd": 1} | ({"KcJd": 1} if t <= 5 else {}) | ({"QcJc": 1} if t <= 3 else {})
        folders = {k: 1 for k in ("KcJd", "QcJc", "JcTc") if k not in callers}
        return facing(s2, fold=folders, call=callers)

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(6 / 7, abs=EXACT)
    assert sol.pot_odds == 0.0
    assert_evs(
        sol,
        {
            "check": 60 / 7,
            "bet 33%": 69 / 7,
            "bet 50%": 65 / 7,
            "bet 75%": 52 / 7,
            "bet 100%": 50 / 7,
            "all-in": -135 / 7,
        },
    )
    o = by_label(sol)
    assert [o[k].option.action.to for k in list(o)[1:]] == [3, 5, 8, 10, 195]
    assert o["bet 33%"].fold_freq == pytest.approx(2 / 7, abs=EXACT)
    assert o["bet 33%"].equity_vs_continue == pytest.approx(0.8, abs=EXACT)
    assert o["bet 50%"].fold_freq == pytest.approx(4 / 7, abs=EXACT)
    assert o["bet 50%"].equity_vs_continue == pytest.approx(2 / 3, abs=EXACT)
    assert o["bet 33%"].required_fold_equity == pytest.approx(3 / 13, abs=EXACT)
    assert sol.options[sol.best].option.label == "bet 33%"


# R3 river bluff. BB checks; Hero (BTN) 6h5h, eq 0 vs every combo; P = 10.
#   D = AsKd, JcTc, QcJc, 3c3d (all 1); |D| = 4.  check = 0·10 = 0.
#   Villain vs bet to t: AsKd calls; 3c3d calls t <= 5; JcTc, QcJc fold.
#   bet 3:  F = 2/4, 1/2·10 + 1/2·(0 − 3) = 3.5.     bet 5:  5 − 2.5 = 2.5.
#   bet 8:  F = 3/4, 7.5 − 1/4·8 = 5.5.               bet 10: 7.5 − 2.5 = 5.
#   all-in: 7.5 − 195/4 = −41.25.   Required fold equity for bet 8: 8/18.
def test_r3_river_bluff():
    s = chk(river(RB))
    D = vrange("AsKd, JcTc, QcJc, 3c3d", H65, RB)

    def table(s2):
        t = max(s2.street_bets)
        if t <= 5:
            return facing(s2, fold={"JcTc": 1, "QcJc": 1}, call={"AsKd": 1, "3c3d": 1})
        return facing(s2, fold={"JcTc": 1, "QcJc": 1, "3c3d": 1}, call={"AsKd": 1})

    sol = solve_exact(s, H65, D, responder(D, table))
    assert sol.equity == pytest.approx(0.0, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 0.0,
            "bet 33%": 3.5,
            "bet 50%": 2.5,
            "bet 75%": 5.5,
            "bet 100%": 5.0,
            "all-in": -41.25,
        },
    )
    o = by_label(sol)["bet 75%"]
    assert o.fold_freq == pytest.approx(0.75, abs=EXACT)
    assert o.required_fold_equity == pytest.approx(8 / 18, abs=EXACT)
    assert o.ahead_vs_continue == pytest.approx(0.0, abs=EXACT)
    assert sol.options[sol.best].option.label == "bet 75%"


# R4 river OOP check look-ahead with two Villain bet sizes. Hero is BB (seat 1) KhQh and
# acts first; P = 10.  D = AsKd, 7c7d, JcTc, KcJd (all 1); |D| = 4; eq(D) = 2/4 = 1/2.
#   After Hero checks, Villain: KcJd checks back; 7c7d bets 5 half / bets 10 half;
#   AsKd and JcTc bet 10.
#     checks back: share 1/4, eq 1, v = 1·10 = 10.
#     bets 5:  share .5/4 = 1/8, eq 0, v = max(0, 0·20 − 5) = 0 (Hero folds).
#     bets 10: share 2.5/4 = 5/8, eq = 1/2.5 = .4, v = max(0, .4·30 − 10) = 2 (Hero calls).
#   check = 1/4·10 + 1/8·0 + 5/8·2 = 2.5 + 1.25 = 3.75.
#   Villain vs Hero's bet to t: AsKd, 7c7d call; KcJd calls t <= 5; JcTc folds.
#   bet 3:  F 1/4, C = AsKd, 7c7d, KcJd, eq(C) 1/3: 2.5 + 3/4·(16/3 − 3) = 2.5 + 1.75 = 4.25.
#   bet 5:  2.5 + 3/4·(20/3 − 5) = 2.5 + 1.25 = 3.75.
#   bet 8:  F 1/2, eq(C) 0: 5 − 4 = 1.   bet 10: 5 − 5 = 0.   all-in: 5 − 97.5 = −92.5.
def test_r4_river_oop_check_lookahead_two_sizes():
    s = river(RB)
    assert s.to_act == 1 and total_pot(s) == 10
    D = vrange("AsKd, 7c7d, JcTc, KcJd", KQ, RB)

    def table(s2):
        if legal_actions(s2).call == 0:  # Hero checked
            b5, b10 = bet_to(s2, 0.5), bet_to(s2, 1.0)
            assert (b5.to, b10.to) == (5, 10)
            return [
                (check_of(s2), {"KcJd": 1}),
                (b5, {"7c7d": 0.5}),
                (b10, {"AsKd": 1, "7c7d": 0.5, "JcTc": 1}),
            ]
        if max(s2.street_bets) <= 5:
            return facing(s2, fold={"JcTc": 1}, call={"AsKd": 1, "7c7d": 1, "KcJd": 1})
        return facing(s2, fold={"JcTc": 1, "KcJd": 1}, call={"AsKd": 1, "7c7d": 1})

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(0.5, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 3.75,
            "bet 33%": 4.25,
            "bet 50%": 3.75,
            "bet 75%": 1.0,
            "bet 100%": 0.0,
            "all-in": -92.5,
        },
    )
    br = by_label(sol)["check"].branches
    assert [b.label for b in br] == [
        "Villain checks back",
        "Villain bets 5 — Hero folds",
        "Villain bets 10 — Hero calls",
    ]
    assert [b.share for b in br] == pytest.approx([1 / 4, 1 / 8, 5 / 8], abs=EXACT)
    assert [b.equity for b in br] == pytest.approx([1.0, 0.0, 0.4], abs=EXACT)
    assert [b.value_chips for b in br] == pytest.approx([10.0, 0.0, 2.0], abs=EXACT)
    assert sol.options[sol.best].option.label == "bet 33%"


# R5 (Review Focus 3) river OOP check where Villain ALWAYS bets and Hero's reply is
# floored at fold. Hero BB 6h5h (eq 0 vs all); P = 10.
#   D = AsKd 1, JcTc .5, 3c3d 1; |D| = 2.5.
#   check: Villain bets 10 with everything: share 1, eq 0, v = max(0, 0·30 − 10) = 0.
#   Villain vs Hero's bet to t: AsKd calls; 3c3d calls t <= 3; JcTc folds.
#   bet 3:  F = .5/2.5 = .2: 2 + .8·(−3) = −0.4.
#   bet 5:  F = 1.5/2.5 = .6: 6 − .4·5 = 4.   bet 8: 6 − 3.2 = 2.8.   bet 10: 6 − 4 = 2.
#   all-in: 6 − .4·195 = −72.
def test_r5_river_oop_check_villain_always_bets_hero_folds():
    s = river(RB)
    D = vrange("AsKd, JcTc:0.5, 3c3d", H65, RB)

    def table(s2):
        if legal_actions(s2).call == 0:
            return [(bet_to(s2, 1.0), {"AsKd": 1, "JcTc": 1, "3c3d": 1})]
        if max(s2.street_bets) <= 3:
            return facing(s2, fold={"JcTc": 1}, call={"AsKd": 1, "3c3d": 1})
        return facing(s2, fold={"JcTc": 1, "3c3d": 1}, call={"AsKd": 1})

    sol = solve_exact(s, H65, D, responder(D, table))
    assert_evs(
        sol,
        {
            "check": 0.0,
            "bet 33%": -0.4,
            "bet 50%": 4.0,
            "bet 75%": 2.8,
            "bet 100%": 2.0,
            "all-in": -72.0,
        },
    )
    br = by_label(sol)["check"].branches
    assert [b.label for b in br] == ["Villain bets 10 — Hero folds"]
    assert br[0].share == pytest.approx(1.0, abs=EXACT)
    assert br[0].value_chips == 0.0
    assert sol.options[sol.best].option.label == "bet 50%"


# R6 (Review Focus 2 and 3, and 1) river OOP: Villain ALWAYS checks back and ALWAYS calls
# (F = 0), including Hero's all-in, where Villain can only fold or call. Hero BB KhQh.
#   D = AsKd .5, JcTc 1, KcQc 1; |D| = 2.5; eq = (0 + 1 + .5)/2.5 = .6.
#   check: one branch, checks back, share 1, v = .6·10 = 6.
#   bet to t, everyone calls: .6·(10 + 2t) − t = 6 + .2t:
#   3 -> 6.6, 5 -> 7, 8 -> 7.6, 10 -> 8, all-in 195 -> 6 + 39 = 45.
def test_r6_river_villain_always_checks_back_and_always_calls():
    s = river(RB)
    D = vrange("AsKd:0.5, JcTc, KcQc", KQ, RB)
    everyone = {"AsKd": 1, "JcTc": 1, "KcQc": 1}

    def table(s2):
        if legal_actions(s2).call == 0:
            return [(check_of(s2), everyone)]
        return facing(s2, fold={}, call=everyone)

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(0.6, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 6.0,
            "bet 33%": 6.6,
            "bet 50%": 7.0,
            "bet 75%": 7.6,
            "bet 100%": 8.0,
            "all-in": 45.0,
        },
    )
    o = by_label(sol)
    assert [b.label for b in o["check"].branches] == ["Villain checks back"]
    assert o["check"].branches[0].value_chips == pytest.approx(6.0, abs=EXACT)
    for label in ("bet 33%", "bet 50%", "bet 75%", "bet 100%", "all-in"):
        assert o[label].fold_freq == 0.0
        assert o[label].equity_vs_continue == pytest.approx(0.6, abs=EXACT)
        assert [b.label for b in o[label].branches] == ["Villain calls"]
    assert o["all-in"].option.action.to == 195
    assert sol.options[sol.best].option.label == "all-in"


# R7 river raise facing a bet; Villain re-jams and Hero CALLS the jam. BB bets 5 (50%);
# Hero (BTN) KhQh; P = 15, call put 5, pot odds 5/20.
#   D = AsKd, 7c7d, JcTc, KcJd (all 1); eq(D) = 2/4 = .5. call = .5·20 − 5 = 5.
#   Villain vs Hero's raise: KcJd folds; AsKd calls; 7c7d and JcTc jam to 195.
#   raise 2.5x to 12 (put 12, vcall 7): F 1/4.
#     call branch: share 1/4, eq 0: 0·34 − 12 = −12.
#     jam branch: share 2/4, eq(7c7d, JcTc) = 1/2; s3 pot = 10 + 12 + 195 = 217, Hero call
#       c = 183, final = 400: max(−12, .5·400 − (12 + 183)) = max(−12, 5) = 5 (Hero calls).
#     EV = 1/4·15 − 1/4·12 + 1/2·5 = 3.75 − 3 + 2.5 = 3.25.
#   raise 3x to 15 (vcall 10): call branch −15; jam: final 400, max(−15, 200 − 195) = 5;
#     EV = 3.75 − 3.75 + 2.5 = 2.5.
#   all-in 195 (vcall 190): Villain can only fold or call; jammers call instead.
#     C = AsKd, 7c7d, JcTc, eq 1/3: 3.75 + 3/4·(400/3 − 195) = 3.75 + 100 − 146.25 = −42.5.
def test_r7_river_raise_villain_rejams_hero_calls():
    s = river_facing(0.5)
    assert s.history[-1].to == 5 and total_pot(s) == 15
    D = vrange("AsKd, 7c7d, JcTc, KcJd", KQ, RB)

    def table(s2):
        if legal_actions(s2).aggressive is None:  # Hero is all-in
            return facing(s2, fold={"KcJd": 1}, call={"AsKd": 1, "7c7d": 1, "JcTc": 1})
        jam = allin(s2)
        assert jam.to == 195
        return facing(
            s2, fold={"KcJd": 1}, call={"AsKd": 1}, raises=[(jam, {"7c7d": 1, "JcTc": 1})]
        )

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.pot_odds == pytest.approx(5 / 20, abs=EXACT)
    assert_evs(
        sol,
        {"fold": 0.0, "call": 5.0, "raise 2.5x": 3.25, "raise 3x": 2.5, "all-in": -42.5},
    )
    o = by_label(sol)
    assert o["raise 2.5x"].option.action.to == 12
    br = o["raise 2.5x"].branches
    assert [b.label for b in br] == [
        "Villain folds",
        "Villain calls",
        "Villain raises to 195 — Hero calls",
    ]
    assert [b.share for b in br] == pytest.approx([0.25, 0.25, 0.5], abs=EXACT)
    assert [b.value_chips for b in br] == pytest.approx([15.0, -12.0, 5.0], abs=EXACT)
    assert "reraise_reply" in o["raise 2.5x"].simplifications
    assert "reraise_reply" not in o["all-in"].simplifications
    assert o["raise 2.5x"].fold_freq == pytest.approx(0.25, abs=EXACT)
    assert o["raise 2.5x"].equity_vs_continue == pytest.approx(1 / 3, abs=EXACT)
    assert sol.options[sol.best].option.label == "call"


# R8 river bluff-raise vs a non-all-in 3x re-raise; Hero FOLDS to it. BB bets 8;
# Hero (BTN) 6h5h, eq 0 vs all; P = 18. D = AsKd, JcTc, QcJc, KcJd (all 1).
#   call = 0·26 − 8 = −8.
#   Villain vs Hero's raise: AsKd re-raises 3x; KcJd calls; JcTc, QcJc fold.  F = 1/2.
#   raise 2.5x to 20 (vcall 12): call branch 1/4·(0·50 − 20);
#     re-raise to 60: s3 pot = 10 + 20 + 60 = 90, c = 40, final 130,
#     max(−20, 0·130 − 60) = −20 (Hero folds).  EV = 9 − 5 − 5 = −1.
#   raise 3x to 24 (vcall 16): re-raise to 72; both branches −24: EV = 9 − 12 = −3.
#   all-in (Villain only folds/calls; AsKd calls): 9 − 1/2·195 = −88.5.
def test_r8_river_bluff_raise_villain_reraises_hero_folds():
    s = river_facing(0.75)
    D = vrange("AsKd, JcTc, QcJc, KcJd", H65, RB)

    def table(s2):
        folders = {"JcTc": 1, "QcJc": 1}
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold=folders, call={"AsKd": 1, "KcJd": 1})
        rr = raise_to(s2, 3.0)
        assert rr.to == 3 * max(s2.street_bets)
        return facing(s2, fold=folders, call={"KcJd": 1}, raises=[(rr, {"AsKd": 1})])

    sol = solve_exact(s, H65, D, responder(D, table))
    assert_evs(
        sol,
        {"fold": 0.0, "call": -8.0, "raise 2.5x": -1.0, "raise 3x": -3.0, "all-in": -88.5},
    )
    o = by_label(sol)
    assert [b.label for b in o["raise 2.5x"].branches] == [
        "Villain folds",
        "Villain calls",
        "Villain raises to 60 — Hero folds",
    ]
    assert [b.label for b in o["raise 3x"].branches][-1] == "Villain raises to 72 — Hero folds"
    assert sol.options[sol.best].option.label == "fold"


# ---------------------------------------------------------------------------
# Turn (5 spots, exact). Board Ks 7h 2c 4d; line: BTN opens to 5, BB calls, flop checked
# through; P = 10 entering the turn. One river card to come from 44 unseen cards
# (52 − 2 Hero − 4 board − 2 Villain). The board is rainbow: no flush is possible.
#
# Hero KhQh (pair of kings, Q kicker), per Villain combo:
#   AsKd: Hero wins only with a Q (Qc Qd Qs) -> 3/44. Paired rivers (7/2/4/K) and A keep
#         Villain ahead on the kicker.
#   JcTc: J/T give Villain a smaller pair; no one-card straight -> Hero always wins, 1.
#   KcJd: Villain wins only with a J (Jh Js Jc) -> Hero 41/44.
#   7c7d: set; a K gives Villain a full house (777KK) -> Hero 0.
# Hero 6h5h (K-7-6-5-4 high; open-ended: a 3 or an 8 makes a straight):
#   AsKd: straight outs 3 (x4) + 8 (x4) -> 8/44. A 6 or 5 pair loses to KK.
#   7c7d: 3s and 8s make a straight over the set; the board does not pair -> 8/44.
#   JcTc / QcJc: 8 straight outs + 6s (6c 6d 6s) + 5s (5c 5d 5s) -> 14/44.
#   3c3d: 8s (x4) + 3h 3s (straight over trips) + 6s (x3) + 5s (x3) -> 12/44.
# ---------------------------------------------------------------------------

TB = cards("Ks7h2c4d")


# T1 turn call facing 75%. BB bets 8; Hero (BTN) KhQh; P = 18; pot odds 8/26.
#   D = AsKd 1, JcTc 1, KcJd 1, 7c7d .5; |D| = 3.5.
#   eq(D) = (3/44 + 1 + 41/44 + 0)/3.5 = (88/44)/3.5 = 4/7.  ahead_now = 2/3.5 = 4/7.
#   call = 4/7·26 − 8 = 48/7.
#   Villain vs a raise: AsKd and 7c7d call; JcTc, KcJd fold.  F = 2/3.5 = 4/7,
#   C share 3/7, eq(C) = (3/44)/1.5 = 1/22.
#   raise 2.5x to 20 (vcall 12): 4/7·18 + 3/7·(50/22 − 20) = 72/7 − 585/77 = 207/77.
#   raise 3x to 24 (vcall 16): 72/7 + 3/7·(58/22 − 24) = 792/77 − 705/77 = 87/77.
#   all-in 195 (vcall 187): 72/7 + 3/7·(400/22 − 195) = 792/77 − 5835/77 = −5043/77.
def test_t1_turn_call():
    t = turn(TB)
    s = apply(t, bet_to(t, 0.75))
    assert s.history[-1].to == 8 and total_pot(s) == 18
    D = vrange("AsKd, JcTc, KcJd, 7c7d:0.5", KQ, TB)

    def table(s2):
        return facing(s2, fold={"JcTc": 1, "KcJd": 1}, call={"AsKd": 1, "7c7d": 1})

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(4 / 7, abs=EXACT)
    assert sol.ahead_now == pytest.approx(4 / 7, abs=EXACT)
    assert sol.pot_odds == pytest.approx(8 / 26, abs=EXACT)
    assert_evs(
        sol,
        {
            "fold": 0.0,
            "call": 48 / 7,
            "raise 2.5x": 207 / 77,
            "raise 3x": 87 / 77,
            "all-in": -5043 / 77,
        },
    )
    o = by_label(sol)
    assert o["raise 2.5x"].fold_freq == pytest.approx(4 / 7, abs=EXACT)
    assert o["raise 2.5x"].equity_vs_continue == pytest.approx(1 / 22, abs=EXACT)
    assert o["raise 2.5x"].ahead_vs_continue == pytest.approx(0.0, abs=EXACT)
    assert o["call"].simplifications == ("realisation",)
    assert sol.options[sol.best].option.label == "call"


# T2 turn value bet in position. BB checks; Hero (BTN) KhQh; P = 10.
#   D = AsKd .5, KcJd 1, JcTc 1; |D| = 2.5.
#   eq(D) = (.5·3/44 + 41/44 + 1)/2.5 = (86.5/44)/2.5 = 173/220.  ahead_now = 2/2.5 = .8.
#   check (closes the turn, full realisation) = 173/220·10 = 173/22.
#   Villain vs bet to t: AsKd calls; KcJd calls t <= 5; JcTc folds.
#   t = 3 and 5: F = .4, C = AsKd .5 + KcJd 1, eq(C) = (1.5/44 + 41/44)/1.5 = 85/132.
#     bet 3: 4 + .6·(85/132·16 − 3) = 4 + .6·241/33 = 461/55.
#     bet 5: 4 + .6·(85/132·20 − 5) = 4 + .6·260/33 = 96/11.
#   t >= 8: F = .8, C = AsKd .5, eq(C) = 3/44.
#     bet 8:  8 + .2·(3/44·26 − 8) = 8 − 137/110 = 743/110.
#     bet 10: 8 + .2·(3/44·30 − 10) = 8 − 35/22 = 141/22.
#     all-in: 8 + .2·(3/44·400 − 195) = 8 − 369/11 = −281/11.
def test_t2_turn_value_bet():
    s = chk(turn(TB))
    assert s.to_act == 0 and total_pot(s) == 10
    D = vrange("AsKd:0.5, KcJd, JcTc", KQ, TB)

    def table(s2):
        if max(s2.street_bets) <= 5:
            return facing(s2, fold={"JcTc": 1}, call={"AsKd": 1, "KcJd": 1})
        return facing(s2, fold={"JcTc": 1, "KcJd": 1}, call={"AsKd": 1})

    sol = solve_exact(s, KQ, D, responder(D, table))
    assert sol.equity == pytest.approx(173 / 220, abs=EXACT)
    assert sol.ahead_now == pytest.approx(0.8, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 173 / 22,
            "bet 33%": 461 / 55,
            "bet 50%": 96 / 11,
            "bet 75%": 743 / 110,
            "bet 100%": 141 / 22,
            "all-in": -281 / 11,
        },
    )
    o = by_label(sol)
    assert o["bet 50%"].equity_vs_continue == pytest.approx(85 / 132, abs=EXACT)
    assert o["bet 50%"].fold_freq == pytest.approx(0.4, abs=EXACT)
    assert o["check"].simplifications == ("realisation",)
    assert sol.options[sol.best].option.label == "bet 50%"


# T3 (Review Focus 2) turn, Villain NEVER continues (C = 0); Hero out of position.
# Hero is BB (seat 1) with 6h5h and acts first; P = 10.
#   D = AsKd, 7c7d (both 1); Hero eq 8/44 vs each -> eq(D) = 2/11.
#   check OOP before the river = eq·P = 20/11 (labelled realisation, no look-ahead).
#   Villain folds to every bet: F = 1, every bet and the all-in earn P = 10,
#   equity vs the continuing range is None (no NaN). Ties go to the first: bet 33%.
def test_t3_turn_villain_never_continues():
    s = turn(TB)
    assert s.to_act == 1
    D = vrange("AsKd, 7c7d", H65, TB)

    def table(s2):
        assert legal_actions(s2).call > 0, "check before the river must not look ahead"
        return facing(s2, fold={"AsKd": 1, "7c7d": 1}, call={})

    sol = solve_exact(s, H65, D, responder(D, table))
    assert sol.equity == pytest.approx(2 / 11, abs=EXACT)
    assert sol.ahead_now == pytest.approx(0.0, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 20 / 11,
            "bet 33%": 10.0,
            "bet 50%": 10.0,
            "bet 75%": 10.0,
            "bet 100%": 10.0,
            "all-in": 10.0,
        },
    )
    for o in sol.options[1:]:
        assert o.fold_freq == 1.0
        assert o.equity_vs_continue is None
        assert o.ahead_vs_continue is None
        assert o.equity_vs_continue_se is None
        assert [b.label for b in o.branches] == ["Villain folds"]
        assert not np.any(o.continue_range)
        assert all(math.isfinite(x) for x in (o.ev_chips, o.required_fold_equity))
    assert by_label(sol)["check"].simplifications == ("realisation",)
    assert sol.options[sol.best].option.label == "bet 33%"


# T4 turn semi-bluff in position. BB checks; Hero (BTN) 6h5h; P = 10.
#   D = AsKd 1, JcTc 1, QcJc .5, 3c3d .5; |D| = 3.
#   eq(D) = (8 + 14 + .5·14 + .5·12)/44/3 = 35/132.  check = 350/132 = 175/66.
#   Villain vs bet to t: AsKd calls; QcJc calls half / folds half; 3c3d calls t <= 5;
#   JcTc folds.
#   t = 3, 5: fold weight 1 + .25 = 1.25 -> F = 5/12; C = AsKd 1, 3c3d .5, QcJc .25 (1.75),
#     eq(C) = (8 + 6 + 3.5)/44/1.75 = 5/22.
#     bet 3: 50/12 + 7/12·(5/22·16 − 3) = 50/12 + 7/12·7/11 = 599/132.
#     bet 5: 50/12 + 7/12·(5/22·20 − 5) = 50/12 − 7/12·5/11 = 515/132.
#   t >= 8: F = 1.75/3 = 7/12; C = AsKd 1, QcJc .25 (1.25), eq(C) = 11.5/44/1.25 = 23/110.
#     bet 8:  70/12 + 5/12·(23/110·26 − 8) = 770/132 − 141/132 = 629/132.
#     bet 10: 70/12 + 5/12·(23/110·30 − 10) = 770/132 − 205/132 = 565/132.
#     all-in: 70/12 + 5/12·(23/110·400 − 195) = 770/132 − 6125/132 = −5355/132.
def test_t4_turn_semi_bluff():
    s = chk(turn(TB))
    D = vrange("AsKd, JcTc, QcJc:0.5, 3c3d:0.5", H65, TB)

    def table(s2):
        if max(s2.street_bets) <= 5:
            fold = {"JcTc": 1, "QcJc": 0.5}
            call = {"AsKd": 1, "QcJc": 0.5, "3c3d": 1}
        else:
            fold = {"JcTc": 1, "QcJc": 0.5, "3c3d": 1}
            call = {"AsKd": 1, "QcJc": 0.5}
        return facing(s2, fold=fold, call=call)

    sol = solve_exact(s, H65, D, responder(D, table))
    assert sol.equity == pytest.approx(35 / 132, abs=EXACT)
    assert_evs(
        sol,
        {
            "check": 175 / 66,
            "bet 33%": 599 / 132,
            "bet 50%": 515 / 132,
            "bet 75%": 629 / 132,
            "bet 100%": 565 / 132,
            "all-in": -5355 / 132,
        },
    )
    o = by_label(sol)
    assert o["bet 33%"].fold_freq == pytest.approx(5 / 12, abs=EXACT)
    assert o["bet 33%"].equity_vs_continue == pytest.approx(5 / 22, abs=EXACT)
    assert o["bet 75%"].fold_freq == pytest.approx(7 / 12, abs=EXACT)
    assert o["bet 75%"].equity_vs_continue == pytest.approx(23 / 110, abs=EXACT)
    assert sol.options[sol.best].option.label == "bet 75%"


# T5 (Review Focus 1) turn, Villain is already all-in: Hero has no bet/raise option.
# BB jams 195 into 10; Hero (BTN) KhQh; P = 205, call put 195, pot odds 195/400.
#   D = AsKd, KcJd, JcTc, 7c7d (all 1): eq = (3 + 41 + 44 + 0)/44/4 = 1/2.
#   call = .5·400 − 195 = 5.
def test_t5_turn_facing_jam_only_fold_or_call():
    t = turn(TB)
    s = apply(t, allin(t))
    assert s.history[-1] == Action(1, ActionKind.BET, Street.TURN, 195)
    assert total_pot(s) == 205
    D = vrange("AsKd, KcJd, JcTc, 7c7d", KQ, TB)
    sol = solve_exact(s, KQ, D, never)
    assert sol.equity == pytest.approx(0.5, abs=EXACT)
    assert sol.pot_odds == pytest.approx(195 / 400, abs=EXACT)
    assert_evs(sol, {"fold": 0.0, "call": 5.0})
    assert by_label(sol)["call"].put == 195
    assert sol.options[sol.best].option.label == "call"


# ---------------------------------------------------------------------------
# Flop (4 spots, MC). Equities: reference.exact_flop (exact turn+river enumeration).
# ---------------------------------------------------------------------------

FB = cards("Ks7h2c")  # spots F1, F2
FB2 = cards("Kh7h2c")  # spots F3, F4
FLOP_SAMPLES = 40_000


class MC:
    """Reference equity and the code's SE for sub-ranges of D in one solved spot."""

    def __init__(self, sol: Solution, D: np.ndarray, ref):
        self.sol, self.D, self.ref = sol, D, ref

    def eq(self, *names: str) -> float:
        return self.ref(sub(self.D, *names))

    def se(self, *names: str) -> float:
        return float(self.sol.combo_equity.vs(sub(self.D, *names)).std_error)

    def check(self, label: str, const: float, terms: list[tuple[float, tuple[str, ...]]]):
        """Assert option ``label``'s EV == const + Σ k·eq(names), within 4·Σ|k|·SE."""
        want = const + sum(k * self.eq(*names) for k, names in terms)
        tol = 4 * sum(abs(k) * self.se(*names) for k, names in terms)
        got = by_label(self.sol)[label].ev_chips
        assert abs(got - want) <= tol + EXACT, (label, got, want, tol)

    def check_eq(self, got: float, se: float, *names: str) -> None:
        want = self.eq(*names)
        assert abs(got - want) <= 4 * se + EXACT, (names, got, want, se)


def flop_mc(s, hero, D, respond, seed: int) -> MC:
    sol = solve(s, hero, D, respond, rng=random.Random(seed), samples=FLOP_SAMPLES)
    assert not sol.equity_exact
    return MC(sol, D, lambda w: exact_flop_reference(hero, s.board, w))


def all_names(D: np.ndarray) -> tuple[str, ...]:
    return tuple(card_str(COMBOS[i][0]) + card_str(COMBOS[i][1]) for i in np.flatnonzero(D))


# F1 flop facing a bet; Villain re-raises 3x (not all-in) and Hero folds to it.
# Board Ks 7h 2c; BB bets 5 (50%); Hero (BTN) KhQh; P = 15, call put 5, pot odds 5/20.
#   D = AsKd, 7c7d, JcTc, KcJd (all 1); |D| = 4.
#   call = eq(D)·20 − 5.
#   Villain vs a raise: JcTc folds; AsKd, KcJd call; 7c7d re-raises 3x. F = 1/4.
#   raise 2.5x to 12 (put 12, vcall 7): call branch 2/4·(eq(AK,KJ)·34 − 12);
#     re-raise to 36: s3 pot = 10 + 12 + 36 = 58, c = 24, final 82;
#     Hero folds (−12) when eq(77)·82 − 36 < −12, i.e. eq(77) < 24/82 (asserted).
#     EV = 15/4 + 1/2·(34·eq(C) − 12) − 12/4 = −5.25 + 17·eq(C).
#   raise 3x to 15 (vcall 10): re-raise to 45, final = 10 + 15 + 45 + 30 = 100;
#     fold (−15) when eq(77) < 30/100.  EV = 15/4 + 1/2·(40·eq(C) − 15) − 15/4 = −7.5 + 20·eq(C).
#   all-in 195 (vcall 190): Villain only folds/calls; JcTc folds, rest call (3/4):
#     EV = 15/4 + 3/4·(400·eq(AK,77,KJ) − 195) = −142.5 + 300·eq(AK,77,KJ).
def test_f1_flop_raise_villain_reraises_hero_folds():
    f = flop(FB)
    s = apply(f, bet_to(f, 0.5))
    assert s.history[-1].to == 5 and total_pot(s) == 15
    D = vrange("AsKd, 7c7d, JcTc, KcJd", KQ, FB)

    def table(s2):
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold={"JcTc": 1}, call={"AsKd": 1, "7c7d": 1, "KcJd": 1})
        rr = raise_to(s2, 3.0)
        return facing(s2, fold={"JcTc": 1}, call={"AsKd": 1, "KcJd": 1}, raises=[(rr, {"7c7d": 1})])

    mc = flop_mc(s, KQ, D, responder(D, table), seed=11)
    sol, o = mc.sol, by_label(mc.sol)
    assert list(o) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    assert sol.pot_odds == pytest.approx(5 / 20, abs=EXACT)
    mc.check_eq(sol.equity, sol.equity_std_error, *all_names(D))
    assert mc.eq("7c7d") < 24 / 82 and mc.eq("7c7d") < 30 / 100  # Hero folds to re-raises
    C = ("AsKd", "KcJd")
    mc.check("call", -5.0, [(20.0, all_names(D))])
    mc.check("raise 2.5x", -5.25, [(17.0, C)])
    mc.check("raise 3x", -7.5, [(20.0, C)])
    mc.check("all-in", -142.5, [(300.0, ("AsKd", "7c7d", "KcJd"))])
    assert o["fold"].ev_chips == 0.0
    assert o["raise 2.5x"].branches[-1].label == "Villain raises to 36 — Hero folds"
    assert o["raise 3x"].branches[-1].label == "Villain raises to 45 — Hero folds"
    assert o["raise 2.5x"].fold_freq == pytest.approx(0.25, abs=EXACT)
    o25 = o["raise 2.5x"]
    mc.check_eq(o25.equity_vs_continue, o25.equity_vs_continue_se, "AsKd", "7c7d", "KcJd")
    assert set(o25.simplifications) == {"realisation", "reraise_reply"}


# F2 (Review Focus 1) flop, short stacks: options merge into one "all-in".
# Stacks 20/20: after BTN opens to 5 and BB calls, 15 behind each, P = 10.
# Hero is BB (seat 1) KhQh, first to act.  Sizes: 33% -> 3, 50% -> 5, 75% -> 8 (< 0.6·15),
# 100% -> 10 >= 0.6·15 = 9 -> clamps to all-in 15, merged with "all-in" (label wins).
#   D = AsKd 1, QcJc 1, 7c7d .5, 9h8h 1; |D| = 3.5.
#   check OOP before the river = 10·eq(D).
#   Villain vs bet to t: AsKd, 7c7d call; 9h8h calls t <= 5 else folds; QcJc folds.
#   bet 3: F = 1/3.5 = 2/7, C = AsKd, 7c7d, 9h8h (5/7):
#          20/7 + 5/7·(16·eq(C) − 3) = 5/7 + 80/7·eq(C).
#   bet 5: 20/7 + 5/7·(20·eq(C) − 5) = −5/7 + 100/7·eq(C).
#   bet 8: F = 4/7, C2 = AsKd, 7c7d (3/7): 40/7 + 3/7·(26·eq(C2) − 8) = 16/7 + 78/7·eq(C2).
#   all-in 15 (vcall 15): 40/7 + 3/7·(40·eq(C2) − 15) = −5/7 + 120/7·eq(C2).
def test_f2_flop_short_stack_allin_merge():
    s = flop(FB, stacks=(20, 20))
    assert s.stacks == (15, 15) and s.to_act == 1 and total_pot(s) == 10
    D = vrange("AsKd, QcJc, 7c7d:0.5, 9h8h", KQ, FB)

    def table(s2):
        if max(s2.street_bets) <= 5:
            return facing(s2, fold={"QcJc": 1}, call={"AsKd": 1, "7c7d": 1, "9h8h": 1})
        return facing(s2, fold={"QcJc": 1, "9h8h": 1}, call={"AsKd": 1, "7c7d": 1})

    mc = flop_mc(s, KQ, D, responder(D, table), seed=12)
    o = by_label(mc.sol)
    assert list(o) == ["check", "bet 33%", "bet 50%", "bet 75%", "all-in"]
    assert [x.option.action.to for x in o.values()][1:] == [3, 5, 8, 15]
    C, C2 = ("AsKd", "7c7d", "9h8h"), ("AsKd", "7c7d")
    mc.check("check", 0.0, [(10.0, all_names(D))])
    mc.check("bet 33%", 5 / 7, [(80 / 7, C)])
    mc.check("bet 50%", -5 / 7, [(100 / 7, C)])
    mc.check("bet 75%", 16 / 7, [(78 / 7, C2)])
    mc.check("all-in", -5 / 7, [(120 / 7, C2)])
    assert o["bet 33%"].fold_freq == pytest.approx(2 / 7, abs=EXACT)
    assert o["all-in"].fold_freq == pytest.approx(4 / 7, abs=EXACT)
    assert o["all-in"].required_fold_equity == pytest.approx(15 / 25, abs=EXACT)
    assert o["check"].simplifications == ("realisation",)


# F3 (Review Focus 2) flop, Villain ALWAYS continues vs Hero's raises (F = 0).
# Board Kh 7h 2c; BB bets 8 (75%); Hero (BTN) AhTh (nut flush draw); P = 18; pot odds 8/26.
#   D = KdQd 1, 7c7d 1, AcKc .5; |D| = 2.5.
#   call = 26·eq(D) − 8.
#   raise 2.5x to 20 (vcall 12), everyone calls: 50·eq(D) − 20.
#   raise 3x to 24 (vcall 16), everyone calls: 58·eq(D) − 24.
#   all-in 195 (vcall 187): KdQd folds, F = .4; C = 7c7d, AcKc .5 (.6):
#     .4·18 + .6·(400·eq(C) − 195) = −109.8 + 240·eq(C).
def test_f3_flop_villain_always_continues():
    f = flop(FB2)
    s = apply(f, bet_to(f, 0.75))
    assert s.history[-1].to == 8 and total_pot(s) == 18
    hero = cards("AhTh")
    D = vrange("KdQd, 7c7d, AcKc:0.5", hero, FB2)

    def table(s2):
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold={"KdQd": 1}, call={"7c7d": 1, "AcKc": 1})
        return facing(s2, fold={}, call={"KdQd": 1, "7c7d": 1, "AcKc": 1})

    mc = flop_mc(s, hero, D, responder(D, table), seed=13)
    o = by_label(mc.sol)
    assert list(o) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    assert [o[k].option.action.to for k in ("raise 2.5x", "raise 3x")] == [20, 24]
    everyone = all_names(D)
    mc.check("call", -8.0, [(26.0, everyone)])
    mc.check("raise 2.5x", -20.0, [(50.0, everyone)])
    mc.check("raise 3x", -24.0, [(58.0, everyone)])
    mc.check("all-in", -109.8, [(240.0, ("7c7d", "AcKc"))])
    for label in ("raise 2.5x", "raise 3x"):
        assert o[label].fold_freq == 0.0
        assert [b.label for b in o[label].branches] == ["Villain calls"]
        mc.check_eq(o[label].equity_vs_continue, o[label].equity_vs_continue_se, *everyone)
    assert o["all-in"].fold_freq == pytest.approx(0.4, abs=EXACT)


# F4 flop in position, checked to; Villain jams over Hero's bet with a set.
# Board Kh 7h 2c; BB checks; Hero (BTN) QhJh; P = 10.
#   D = AsKd 1, 7c7d .5, Td9d 1, AcQc 1; |D| = 3.5.
#   check (closes the flop, full realisation) = 10·eq(D).
#   Villain vs bet to t: Td9d folds; AsKd calls; AcQc calls t <= 5 else folds;
#   7c7d jams to 195. For every t: s3 pot = 10 + t + 195, c = 195 − t, final = 400;
#   Hero folds (−t) when 400·eq(77) − 195 < −t, i.e. eq(77) < (195 − 10)/400 (asserted).
#   bet 3:  F = 2/7; call AsKd, AcQc (4/7); jam 1/7:
#           20/7 + 4/7·(16·eq(C) − 3) − 3/7 = 5/7 + 64/7·eq(C).
#   bet 5:  20/7 + 4/7·(20·eq(C) − 5) − 5/7 = −5/7 + 80/7·eq(C).
#   bet 8:  F = 4/7; call AsKd (2/7); jam 1/7: 40/7 + 2/7·(26·eq(AK) − 8) − 8/7
#           = 16/7 + 52/7·eq(AK).
#   bet 10: 40/7 + 2/7·(30·eq(AK) − 10) − 10/7 = 10/7 + 60/7·eq(AK).
#   all-in 195 (vcall 195): Td9d, AcQc fold (4/7); AsKd, 7c7d call (3/7):
#           40/7 + 3/7·(400·eq(AK,77) − 195) = −545/7 + 1200/7·eq(AK,77).
def test_f4_flop_bet_villain_jams_hero_folds():
    s = chk(flop(FB2))
    assert s.to_act == 0 and total_pot(s) == 10
    hero = cards("QhJh")
    D = vrange("AsKd, 7c7d:0.5, Td9d, AcQc", hero, FB2)

    def table(s2):
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold={"Td9d": 1, "AcQc": 1}, call={"AsKd": 1, "7c7d": 1})
        small = max(s2.street_bets) <= 5
        fold = {"Td9d": 1} | ({} if small else {"AcQc": 1})
        call = {"AsKd": 1} | ({"AcQc": 1} if small else {})
        return facing(s2, fold=fold, call=call, raises=[(allin(s2), {"7c7d": 1})])

    mc = flop_mc(s, hero, D, responder(D, table), seed=14)
    o = by_label(mc.sol)
    assert list(o) == ["check", "bet 33%", "bet 50%", "bet 75%", "bet 100%", "all-in"]
    assert mc.eq("7c7d") < (195 - 10) / 400
    C = ("AsKd", "AcQc")
    mc.check("check", 0.0, [(10.0, all_names(D))])
    mc.check("bet 33%", 5 / 7, [(64 / 7, C)])
    mc.check("bet 50%", -5 / 7, [(80 / 7, C)])
    mc.check("bet 75%", 16 / 7, [(52 / 7, ("AsKd",))])
    mc.check("bet 100%", 10 / 7, [(60 / 7, ("AsKd",))])
    mc.check("all-in", -545 / 7, [(1200 / 7, ("AsKd", "7c7d"))])
    for label in ("bet 33%", "bet 50%", "bet 75%", "bet 100%"):
        assert o[label].branches[-1].label == "Villain raises to 195 — Hero folds"
        assert o[label].branches[-1].value_chips == -o[label].put
    assert o["bet 33%"].fold_freq == pytest.approx(2 / 7, abs=EXACT)
    b33 = o["bet 33%"]
    mc.check_eq(b33.equity_vs_continue, b33.equity_vs_continue_se, "AsKd", "AcQc", "7c7d")


# ---------------------------------------------------------------------------
# Pre-flop (3 spots, MC, slow). Equities: exact enumeration over all C(48, 5) boards per
# matchup. Pre-flop no combo in these ranges shares a card with Hero, so a sub-range's
# equity is the weight-averaged per-combo equity.
# ---------------------------------------------------------------------------

PRE_SAMPLES = 100_000


@functools.cache
def exact_preflop(hero: tuple[int, int], villain: tuple[int, int]) -> float:
    """Hero's exact all-in equity vs one Villain combo (ties count half)."""
    dead = set(hero) | set(villain)
    rest = [c for c in range(52) if c not in dead]
    share = n = 0
    for board in itertools.combinations(rest, 5):
        h = evaluate(hero + board)
        v = evaluate(villain + board)
        share += 2 if h < v else 1 if h == v else 0
        n += 2
    return share / n


def preflop_ref(hero: tuple[int, int]):
    def ref(w: np.ndarray) -> float:
        num = den = 0.0
        for i in np.flatnonzero(w):
            assert not set(COMBOS[i]) & set(hero)
            num += w[i] * exact_preflop(hero, COMBOS[i])
            den += w[i]
        return num / den

    return ref


def preflop_mc(s, hero, D, respond, seed: int) -> MC:
    sol = solve(s, hero, D, respond, rng=random.Random(seed), samples=PRE_SAMPLES)
    return MC(sol, D, preflop_ref(hero))


@pytest.mark.slow
def test_exact_preflop_reference_agrees_with_pokerkit():
    """The enumerator itself, vs pokerkit (20k samples, 4·SE)."""
    from pokerkit import Card, Deck, StandardHighHand, calculate_equities
    from pokerkit import parse_range as pk_parse_range

    state = random.getstate()
    random.seed(0)
    try:
        pk = calculate_equities(
            (pk_parse_range("AhJd"), pk_parse_range("AsKs")),
            Card.parse(""),
            2,
            5,
            Deck.STANDARD,
            (StandardHighHand,),
            sample_count=20_000,
        )[0]
    finally:
        random.setstate(state)
    ours = exact_preflop(cards("AhJd"), cards("AsKs"))
    assert abs(ours - pk) <= 4 * math.sqrt(ours * (1 - ours) / 20_000)


# P1 pre-flop BTN open. new_hand(0): Hero BTN (seat 0) AhJd has posted 1, BB 2; P = 3.
# Options: fold, raise 2.5x (to 5), raise 3x (to 6), all-in (200) — no limp.
#   D = AsKs .5, 7c7d 1, KsQs 1, 9c4d 1; |D| = 3.5.
#   Villain vs an open: 9c4d folds; 7c7d, KsQs call; AsKs 3-bets 3x.
#   vs all-in: KsQs, 9c4d fold; AsKs, 7c7d call.
#   raise to 5 (put 4, vcall 3): F 2/7; call (4/7): 10·eq(C) − 4, C = 7c7d, KsQs;
#     3-bet to 15 (1/7): s3 pot 20, c 10, final 30; Hero folds (−4) when
#     30·eq(AKs) − 14 < −4, i.e. eq(AKs) < 1/3 (asserted).
#     EV = 6/7 + 4/7·(10·eq(C) − 4) − 4/7 = −2 + 40/7·eq(C).
#   raise to 6 (put 5, vcall 4): 3-bet to 18, pot 24, c 12, final 36; fold when
#     36·eq(AKs) − 17 < −5, i.e. eq(AKs) < 1/3.
#     EV = 6/7 + 4/7·(12·eq(C) − 5) − 5/7 = −19/7 + 48/7·eq(C).
#   all-in (put 199, vcall 198): F 4/7; C2 = AsKs .5, 7c7d (3/7):
#     12/7 + 3/7·(400·eq(C2) − 199) = −585/7 + 1200/7·eq(C2).
@pytest.mark.slow
def test_p1_preflop_btn_open():
    s = new_hand(0)
    assert s.to_act == 0 and total_pot(s) == 3
    hero = cards("AhJd")
    D = vrange("AsKs:0.5, 7c7d, KsQs, 9c4d", hero, ())

    def table(s2):
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold={"KsQs": 1, "9c4d": 1}, call={"AsKs": 1, "7c7d": 1})
        return facing(
            s2,
            fold={"9c4d": 1},
            call={"7c7d": 1, "KsQs": 1},
            raises=[(raise_to(s2, 3.0), {"AsKs": 1})],
        )

    mc = preflop_mc(s, hero, D, responder(D, table), seed=21)
    o = by_label(mc.sol)
    assert list(o) == ["fold", "raise 2.5x", "raise 3x", "all-in"]
    assert [x.option.action.to for x in o.values()][1:] == [5, 6, 200]
    assert mc.eq("AsKs") < 1 / 3
    C = ("7c7d", "KsQs")
    mc.check("raise 2.5x", -2.0, [(40 / 7, C)])
    mc.check("raise 3x", -19 / 7, [(48 / 7, C)])
    mc.check("all-in", -585 / 7, [(1200 / 7, ("AsKs", "7c7d"))])
    assert o["fold"].ev_chips == 0.0
    assert o["raise 2.5x"].put == 4
    assert o["raise 2.5x"].branches[-1].label == "Villain raises to 15 — Hero folds"
    assert o["raise 3x"].branches[-1].label == "Villain raises to 18 — Hero folds"
    assert set(o["raise 2.5x"].simplifications) == {"preflop_size", "realisation", "reraise_reply"}
    assert set(o["all-in"].simplifications) == {"preflop_size", "realisation"}
    assert mc.sol.category_breakdown is None


# P2 pre-flop BB vs open (call). BTN opens to 5; Hero BB (seat 1) KdQd; P = 7; call put 3,
# pot odds 3/10.  D = AcAd .5, 5c5d 1, Js9s 1; |D| = 2.5.
#   call = 10·eq(D) − 3.
#   Villain vs a 3-bet: Js9s folds; 5c5d calls; AcAd jams 200.  vs all-in: AcAd, 5c5d call.
#   3-bet to 12 (put 10, vcall 7): F .4; call .4: 24·eq(55) − 10;
#     jam .2: s3 pot = 200 + 12 = 212, c = 188, final 400; fold (−10) when
#     400·eq(AA) − 198 < −10, i.e. eq(AA) < 188/400 (asserted).
#     EV = 2.8 + .4·(24·eq(55) − 10) − 2 = −3.2 + 9.6·eq(55).
#   3-bet to 15 (put 13, vcall 10): 2.8 + .4·(30·eq(55) − 13) − .2·13 = −5 + 12·eq(55).
#   all-in (put 198, vcall 195): F .4; C = AcAd .5, 5c5d (.6):
#     2.8 + .6·(400·eq(C) − 198) = −116 + 240·eq(C).
@pytest.mark.slow
def test_p2_preflop_bb_vs_open():
    s0 = new_hand(0)
    s = apply(s0, raise_to(s0, 2.5))
    assert s.to_act == 1 and total_pot(s) == 7
    hero = cards("KdQd")
    D = vrange("AcAd:0.5, 5c5d, Js9s", hero, ())

    def table(s2):
        if legal_actions(s2).aggressive is None:
            return facing(s2, fold={"Js9s": 1}, call={"AcAd": 1, "5c5d": 1})
        jam = allin(s2)
        assert jam.to == 200
        return facing(s2, fold={"Js9s": 1}, call={"5c5d": 1}, raises=[(jam, {"AcAd": 1})])

    mc = preflop_mc(s, hero, D, responder(D, table), seed=22)
    sol, o = mc.sol, by_label(mc.sol)
    assert list(o) == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    assert [x.option.action.to for x in o.values()][1:] == [5, 12, 15, 200]
    assert sol.pot_odds == pytest.approx(3 / 10, abs=EXACT)
    assert mc.eq("AcAd") < 188 / 400
    mc.check_eq(sol.equity, sol.equity_std_error, *all_names(D))
    mc.check("call", -3.0, [(10.0, all_names(D))])
    mc.check("raise 2.5x", -3.2, [(9.6, ("5c5d",))])
    mc.check("raise 3x", -5.0, [(12.0, ("5c5d",))])
    mc.check("all-in", -116.0, [(240.0, ("AcAd", "5c5d"))])
    assert o["raise 2.5x"].branches[-1].label == "Villain raises to 200 — Hero folds"
    assert o["call"].simplifications == ("realisation",)


# P3 pre-flop BTN vs 3-bet, Hero jams. BTN opens to 5, BB 3-bets 3x to 15; Hero (BTN)
# JhJs; P = 20; options fold, call (put 10), all-in (to 200, put 195); pot odds 10/30.
#   D = AcKd 1, QsQh 1, 8c8d .5, As5s 1; |D| = 3.5.
#   call = 30·eq(D) − 10.
#   vs the jam (vcall 185): 8c8d, As5s fold (F = 1.5/3.5 = 3/7); AcKd, QsQh call (4/7):
#     60/7 + 4/7·(400·eq(AK,QQ) − 195) = −720/7 + 1600/7·eq(AK,QQ).
@pytest.mark.slow
def test_p3_preflop_btn_vs_3bet_jam():
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, raise_to(s, 3.0))
    assert s.history[-1].to == 15 and s.to_act == 0 and total_pot(s) == 20
    hero = cards("JhJs")
    D = vrange("AcKd, QsQh, 8c8d:0.5, As5s", hero, ())

    def table(s2):
        assert legal_actions(s2).aggressive is None  # Hero is all-in
        return facing(s2, fold={"8c8d": 1, "As5s": 1}, call={"AcKd": 1, "QsQh": 1})

    mc = preflop_mc(s, hero, D, responder(D, table), seed=23)
    sol, o = mc.sol, by_label(mc.sol)
    assert list(o) == ["fold", "call", "all-in"]
    assert o["all-in"].option.action.to == 200 and o["all-in"].put == 195
    assert sol.pot_odds == pytest.approx(10 / 30, abs=EXACT)
    mc.check_eq(sol.equity, sol.equity_std_error, *all_names(D))
    mc.check("call", -10.0, [(30.0, all_names(D))])
    mc.check("all-in", -720 / 7, [(1600 / 7, ("AcKd", "QsQh"))])
    assert o["all-in"].fold_freq == pytest.approx(3 / 7, abs=EXACT)
    jam = o["all-in"]
    mc.check_eq(jam.equity_vs_continue, jam.equity_vs_continue_se, "AcKd", "QsQh")
