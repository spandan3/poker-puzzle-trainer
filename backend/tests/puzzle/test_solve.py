import math
import random

import numpy as np
import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.engine.combos import COMBOS, combo_index
from poker_trainer.engine.equity import combo_equity, equity_vs_range
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
from poker_trainer.puzzle.model import SIMPLIFICATIONS, visible_range
from poker_trainer.puzzle.options import hero_options
from poker_trainer.puzzle.solve import evaluate_action, solve, villain_respond
from poker_trainer.villain.profiles import load_profile
from poker_trainer.villain.strategy import allin, bet_to, raise_to

HERO = parse_cards("KhQh")
BOARD = parse_cards("Ks7h2c4d9s")
AK = combo_index(*parse_cards("AsKd"))
JT = combo_index(*parse_cards("JcTc"))


def _check(s: HandState) -> HandState:
    return apply(s, Action(s.to_act, ActionKind.CHECK, s.street))


def _to_river() -> HandState:
    """BTN (seat 0) raises to 5, BB calls; checked down to the river; BB to act, P = 10."""
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    s = deal(s, BOARD[:3])
    s = _check(_check(s))
    s = deal(s, BOARD[3:4])
    s = _check(_check(s))
    return deal(s, BOARD[4:])


def river_spot(variant: str) -> HandState:
    s = _to_river()
    if variant == "facing":  # BB bets 8 into 10; Hero (seat 0) faces 8 with P = 18
        return apply(s, Action(1, ActionKind.BET, Street.RIVER, 8))
    if variant == "checked":  # BB checks; Hero (seat 0) in position, P = 10
        return _check(s)
    assert variant == "oop"  # Hero is seat 1 (BB) and acts first, P = 10
    return s


def D() -> np.ndarray:
    return visible_range(parse_range("AsKd, JcTc"), HERO, BOARD)


def arr(**weights: float) -> np.ndarray:
    a = np.zeros(len(COMBOS))
    names = {"ak": AK, "jt": JT}
    for k, w in weights.items():
        a[names[k]] = w
    return a


def ce_for(s: HandState):
    return combo_equity(HERO, s.board, D(), rng=random.Random(0), samples=2000)


def facing_respond(fold: np.ndarray, call: np.ndarray, raise_: dict[int, np.ndarray] | None = None):
    """Villain facing a bet: explicit fold / call / raise-to arrays."""

    def respond(s2: HandState):
        me, st = s2.to_act, s2.street
        out = {
            Action(me, ActionKind.FOLD, st): fold,
            Action(me, ActionKind.CALL, st, s2.street_bets[me] + legal_actions(s2).call): call,
        }
        for to, a in (raise_ or {}).items():
            out[Action(me, ActionKind.RAISE, st, to)] = a
        return out

    return respond


def generic_respond(s2: HandState):
    """AsKd calls any bet, JcTc folds; Villain checks behind when not facing a bet."""
    if legal_actions(s2).call > 0:
        return facing_respond(arr(jt=1), arr(ak=1))(s2)
    return {Action(s2.to_act, ActionKind.CHECK, s2.street): arr(ak=1, jt=1)}


def option(s, label):
    return next(o for o in hero_options(s) if o.label == label).action


# ---------------------------------------------------------------------------


def test_river_call_ev():
    s = river_spot("facing")
    assert total_pot(s) == 18
    sol = solve(s, HERO, D(), generic_respond, rng=random.Random(0), samples=2000)
    evs = {o.option.label: o for o in sol.options}
    assert sol.equity == 0.5
    assert evs["call"].ev_chips == pytest.approx(0.5 * 26 - 8)  # == 5.0
    assert evs["call"].put == 8
    assert evs["fold"].ev_chips == 0
    assert sol.pot_odds == pytest.approx(8 / 26)
    assert sol.ahead_now is None


def test_river_bet_ev():
    s = river_spot("checked")
    assert total_pot(s) == 10
    sol = solve(s, HERO, D(), generic_respond, rng=random.Random(0), samples=2000)
    evs = {o.option.label: o for o in sol.options}
    bet = evs["bet 50%"]
    assert bet.option.action.to == 5
    assert bet.fold_freq == pytest.approx(0.5)
    assert bet.equity_vs_continue == 0.0
    assert bet.ahead_vs_continue == 0.0  # river: equity vs C_all
    assert bet.ev_chips == pytest.approx(0.5 * 10 + 0.5 * (0 * 20 - 5))  # == 2.5
    assert bet.required_fold_equity == pytest.approx(5 / 15)
    assert np.array_equal(bet.continue_range, arr(ak=1))
    assert evs["check"].ev_chips == pytest.approx(5.0)
    assert sol.options[sol.best].option.label == "check"
    assert [b.label for b in bet.branches] == ["Villain folds", "Villain calls"]


def test_river_oop_check_lookahead():
    s = river_spot("oop")
    assert s.to_act == 1 and total_pot(s) == 10

    def respond(s2):
        b = bet_to(s2, 0.75)
        assert b.to == 8
        return {Action(0, ActionKind.CHECK, Street.RIVER): arr(jt=1), b: arr(ak=1)}

    chk = Action(1, ActionKind.CHECK, Street.RIVER)
    o = evaluate_action(s, HERO, D(), ce_for(s), chk, respond)
    assert o.ev_chips == pytest.approx(0.5 * (1.0 * 10) + 0.5 * max(0, 0 * 26 - 8))  # == 5.0
    labels = {b.label: b for b in o.branches}
    assert labels["Villain checks back"].value_chips == pytest.approx(10.0)
    assert labels["Villain bets 8 — Hero folds"].value_chips == 0.0
    assert o.simplifications == ()


def test_river_oop_check_villain_always_bets_hero_calls():
    s = river_spot("oop")

    def respond(s2):
        return {bet_to(s2, 0.75): arr(ak=1, jt=1)}

    chk = Action(1, ActionKind.CHECK, Street.RIVER)
    o = evaluate_action(s, HERO, D(), ce_for(s), chk, respond)
    # eq 0.5 vs both, b = 8: max(0, 0.5*26 - 8) = 5.0
    assert o.ev_chips == pytest.approx(5.0)
    assert [b.label for b in o.branches] == ["Villain bets 8 — Hero calls"]


def test_no_continue_ev_is_pot():
    s = river_spot("checked")
    o = evaluate_action(
        s, HERO, D(), ce_for(s), option(s, "bet 50%"), facing_respond(arr(ak=1, jt=1), arr())
    )
    assert o.ev_chips == 10.0
    assert o.fold_freq == 1.0
    assert o.equity_vs_continue is None
    assert o.ahead_vs_continue is None
    assert o.equity_vs_continue_se is None
    assert [b.label for b in o.branches] == ["Villain folds"]


def test_always_continue():
    s = river_spot("checked")
    o = evaluate_action(
        s, HERO, D(), ce_for(s), option(s, "bet 50%"), facing_respond(arr(), arr(ak=1, jt=1))
    )
    eq, P, b = 0.5, 10, 5
    assert o.fold_freq == 0.0
    assert o.equity_vs_continue == eq
    assert o.ev_chips == pytest.approx(eq * (P + 2 * b) - b)  # == 5.0
    assert [br.label for br in o.branches] == ["Villain calls"]


def test_allin_villain_only_fold_call():
    s = river_spot("checked")
    jam = allin(s)
    assert jam.to == 195
    real = villain_respond(load_profile("tag"))
    keys = real(apply(s, jam))
    assert {k.kind for k in keys} <= {ActionKind.FOLD, ActionKind.CALL}
    o = evaluate_action(s, HERO, D(), ce_for(s), jam, real)
    assert math.isfinite(o.ev_chips)
    assert not any("raises" in b.label for b in o.branches)
    # Explicit: AK calls (eq 0), JT folds -> 0.5*10 + 0.5*(0*400 - 195) = -92.5
    o2 = evaluate_action(s, HERO, D(), ce_for(s), jam, facing_respond(arr(jt=1), arr(ak=1)))
    assert o2.ev_chips == pytest.approx(-92.5)
    assert o2.option.label == "all-in"


def test_reraise_lookahead():
    s = river_spot("checked")
    # JcTc folds; AsKd raises to 15 half the time and calls half the time.
    respond = facing_respond(arr(jt=1), arr(ak=0.5), {15: arr(ak=0.5)})
    o = evaluate_action(s, HERO, D(), ce_for(s), option(s, "bet 50%"), respond)
    # Call branch: 0*20 - 5 = -5. Raise branch: final = 40, max(-5, 0*40 - 15) = -5.
    assert o.ev_chips == pytest.approx(0.5 * 10 + 0.5 * (-5))  # == 2.5
    assert [b.label for b in o.branches] == [
        "Villain folds",
        "Villain calls",
        "Villain raises to 15 — Hero folds",
    ]
    assert [b.share for b in o.branches] == [0.5, 0.25, 0.25]
    assert o.branches[2].value_chips == -5.0
    assert "reraise_reply" in o.simplifications


def test_reraise_hero_calls_when_ahead():
    s = river_spot("checked")
    # JcTc raises to 15 (eq 1), AsKd folds: final = 40, max(-5, 1*40 - 15) = 25.
    respond = facing_respond(arr(ak=1), arr(), {15: arr(jt=1)})
    o = evaluate_action(s, HERO, D(), ce_for(s), option(s, "bet 50%"), respond)
    assert o.ev_chips == pytest.approx(0.5 * 10 + 0.5 * 25)  # == 17.5
    assert o.branches[-1].label == "Villain raises to 15 — Hero calls"


def test_category_breakdown_sums():
    s = river_spot("checked")
    sol = solve(s, HERO, D(), generic_respond, rng=random.Random(0), samples=2000)
    rows = sol.category_breakdown
    assert rows is not None and len(rows) >= 1
    assert sum(r.share for r in rows) == pytest.approx(1.0)
    for r in rows:
        assert r.share > 0
        assert r.ahead == r.equity
    assert sum(r.share * r.equity for r in rows) == pytest.approx(sol.equity)


def _flop_facing_bet() -> tuple[HandState, tuple[int, int], np.ndarray]:
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    s = deal(s, BOARD[:3])
    s = apply(s, bet_to(s, 0.5))
    rng_range = parse_range("22+, A2s+, K9s+, QTs+, JTs, ATo+, KJo+")
    return s, HERO, visible_range(rng_range, HERO, s.board)


def test_realisation_label_preriver():
    s, hero, d = _flop_facing_bet()
    ce = combo_equity(hero, s.board, d, rng=random.Random(0), samples=2000)
    call = option(s, "call")
    o = evaluate_action(s, hero, d, ce, call, villain_respond(load_profile("tag")))
    assert "realisation" in o.simplifications
    assert set(o.simplifications) <= set(SIMPLIFICATIONS)

    r = river_spot("facing")
    o2 = evaluate_action(r, HERO, D(), ce_for(r), option(r, "call"), generic_respond)
    assert o2.simplifications == ()


def test_solve_with_strategy_smoke():
    s, hero, d = _flop_facing_bet()  # BTN (seat 0) faces a flop bet
    _check_solution(s, hero, d)
    # Unopened flop: BB (seat 1) to act with KhQh
    u = new_hand(0)
    u = apply(u, raise_to(u, 2.5))
    u = apply(u, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    u = deal(u, BOARD[:3])
    _check_solution(u, hero, d)


def _check_solution(s, hero, d):
    sol = solve(
        s, hero, d, villain_respond(load_profile("tag")), rng=random.Random(3), samples=4000
    )
    assert 0 <= sol.best < len(sol.options)
    assert sol.ahead_now is not None
    assert sol.category_breakdown is not None
    assert sum(r.share for r in sol.category_breakdown) == pytest.approx(1.0)
    for o in sol.options:
        assert math.isfinite(o.ev_chips)
        if o.fold_freq is not None:
            assert 0.0 <= o.fold_freq <= 1.0
    assert set(sol.simplifications) <= set(SIMPLIFICATIONS)
    assert list(sol.simplifications) == sorted(sol.simplifications)


def test_solve_preflop_smoke():
    s0 = new_hand(0)
    s = apply(s0, raise_to(s0, 2.5))  # Hero is BB facing the open
    hero = parse_cards("AhJd")
    d = visible_range(parse_range("22+, A2s+, K2s+, Q8s+, J9s+, T9s, A8o+, KTo+, QJo"), hero, ())
    sol = solve(
        s, hero, d, villain_respond(load_profile("tag")), rng=random.Random(5), samples=4000
    )
    assert sol.category_breakdown is None
    assert sol.ahead_now is not None
    labels = [o.option.label for o in sol.options]
    assert labels == ["fold", "call", "raise 2.5x", "raise 3x", "all-in"]
    for o in sol.options:
        assert math.isfinite(o.ev_chips)
        if o.option.action.kind == ActionKind.RAISE:
            assert "preflop_size" in o.simplifications
            assert o.ahead_vs_continue is not None
    assert "preflop_size" in sol.simplifications


def test_best_tie_goes_to_earlier_option():
    s = river_spot("checked")
    # Villain always folds: every bet earns P = 10; check earns eq*P = 5.
    sol = solve(
        s, HERO, D(), facing_respond(arr(ak=1, jt=1), arr()), rng=random.Random(0), samples=10
    )
    assert sol.options[sol.best].option.label == "bet 33%"


def test_unsampled_subrange_falls_back_deterministically():
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    s = deal(s, BOARD[:3])  # BB (seat 1) to act, unopened
    d = visible_range(parse_range("AA, QQ, JcTc:0.000000001"), HERO, s.board)
    ce = combo_equity(HERO, s.board, d, rng=random.Random(0), samples=2000)
    assert ce.count[JT] == 0
    only_jt = np.where(np.arange(len(COMBOS)) == JT, d, 0.0)
    respond = facing_respond(np.where(np.arange(len(COMBOS)) == JT, 0.0, 1.0), arr(jt=1))
    o = evaluate_action(s, HERO, d, ce, option(s, "bet 50%"), respond, samples=2000)
    want = equity_vs_range(HERO, s.board, only_jt, rng=random.Random(0), samples=500)
    assert o.equity_vs_continue == want.equity
    assert math.isfinite(o.ev_chips)
