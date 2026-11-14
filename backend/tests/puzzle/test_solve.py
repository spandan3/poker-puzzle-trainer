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
from poker_trainer.puzzle.solve import (
    _category_breakdown,
    evaluate_action,
    realisation,
    solve,
    villain_respond,
)
from poker_trainer.villain.narrowing import RangeTracker
from poker_trainer.villain.profiles import PROFILE_NAMES, load_profile
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
    assert o.simplifications == ("check_reply",)


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
        assert r.win + r.tie + r.lose == pytest.approx(1.0)
        assert r.win + r.tie / 2 == pytest.approx(r.ahead)  # exact river equity
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
    assert "realisation_position" in o.simplifications
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
    for r in sol.category_breakdown:
        assert r.win + r.tie + r.lose == pytest.approx(1.0)
        assert min(r.win, r.tie, r.lose) >= 0.0
        assert r.win + r.tie / 2 == pytest.approx(r.ahead)
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


def test_check_reply_only_on_out_of_position_checks():
    oop = river_spot("oop")  # river OOP: look-ahead
    o = evaluate_action(oop, HERO, D(), ce_for(oop), option(oop, "check"), generic_respond)
    assert o.simplifications == ("check_reply",)
    ip = river_spot("checked")  # river IP: closes the street
    o = evaluate_action(ip, HERO, D(), ce_for(ip), option(ip, "check"), generic_respond)
    assert o.simplifications == ()

    _, hero, d = _flop_facing_bet()
    f = new_hand(0)
    f = apply(f, raise_to(f, 2.5))
    f = apply(f, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    f = deal(f, BOARD[:3])
    ce = combo_equity(hero, f.board, d, rng=random.Random(0), samples=2000)
    o = evaluate_action(f, hero, d, ce, option(f, "check"), generic_respond)  # flop OOP
    assert o.simplifications == ("check_reply", "realisation_position")
    f_ip = _check(f)
    o = evaluate_action(f_ip, hero, d, ce, option(f_ip, "check"), generic_respond)  # flop IP
    assert o.simplifications == ("realisation_position",)


def test_pot_odds_zero_without_call_option():
    s = new_hand(0)  # BTN first in: fold / raise / all-in, no call
    hero = parse_cards("AhJd")
    d = visible_range(parse_range("22+, A2s+, KTo+"), hero, ())
    sol = solve(s, hero, d, villain_respond(load_profile("tag")), rng=random.Random(1), samples=500)
    assert all(o.option.action.kind != ActionKind.CALL for o in sol.options)
    assert sol.pot_odds == 0.0


def test_near_empty_continue_range_counts_as_empty():
    s = river_spot("checked")
    tiny = 1e-13
    respond = facing_respond(arr(ak=1 - tiny, jt=1), arr(ak=tiny))
    o = evaluate_action(s, HERO, D(), ce_for(s), option(s, "bet 50%"), respond)
    assert o.ev_chips == 10.0
    assert o.fold_freq == 1.0
    assert o.equity_vs_continue is None and o.ahead_vs_continue is None
    assert [b.label for b in o.branches] == ["Villain folds"]


def test_respond_must_sum_to_one():
    s = river_spot("checked")
    bad = facing_respond(arr(jt=1), arr(ak=0.5))  # AsKd sums to 0.5
    with pytest.raises(ValueError, match="sum to 1"):
        evaluate_action(s, HERO, D(), ce_for(s), option(s, "bet 50%"), bad)
    oop = river_spot("oop")

    def bad_check(s2):
        return {Action(s2.to_act, ActionKind.CHECK, s2.street): arr(ak=1)}  # JcTc missing

    with pytest.raises(ValueError, match="sum to 1"):
        evaluate_action(oop, HERO, D(), ce_for(oop), option(oop, "check"), bad_check)


def test_breakdown_rejects_board_blocked_weight():
    s = river_spot("checked")
    d = np.array(D())
    d[combo_index(*parse_cards("Ks2h"))] = 1.0  # Ks is on the board
    with pytest.raises(ValueError, match="blocked"):
        _category_breakdown(s, HERO, d, ce_for(s), 2000)


# ---------------------------------------------------------------------------
# Position-aware equity realisation (M9 "Realisation factor")
# ---------------------------------------------------------------------------

EXACT = 1e-9


def _never(s2: HandState):
    raise AssertionError("respond must not be called for fold/call/check options")


def _flop_oop() -> HandState:
    """BTN (seat 0) opens to 5, BB calls; flop Ks 7h 2c; BB (seat 1, Hero) acts first, P = 10."""
    s = new_hand(0)
    s = apply(s, raise_to(s, 2.5))
    s = apply(s, Action(1, ActionKind.CALL, Street.PREFLOP, 5))
    return deal(s, BOARD[:3])


def _ce(s: HandState, d: np.ndarray):
    return combo_equity(HERO, tuple(s.board), d, rng=random.Random(0), samples=2000)


def test_realisation_values():
    assert realisation(Street.PREFLOP, False, False) == 0.80
    assert realisation(Street.FLOP, False, False) == 0.88
    assert realisation(Street.TURN, False, False) == 0.94
    assert realisation(Street.RIVER, False, False) == 1.0
    for st in Street:
        assert realisation(st, True, False) == 1.0


def test_realisation_all_in_is_one():
    for st in Street:
        for ip in (True, False):
            assert realisation(st, ip, True) == 1.0
    d = D()

    # Pre-flop: BTN jams to 200, Hero (BB, out of position) calls: nothing behind, r = 1.
    s0 = new_hand(0)
    s = apply(s0, allin(s0))
    assert s.to_act == 1 and total_pot(s) == 202
    ce = _ce(s, d)
    e = float(ce.vs(d).equity)
    o = evaluate_action(s, HERO, d, ce, option(s, "call"), _never)
    assert o.put == 198
    assert o.realisation == 1.0
    assert o.ev_chips == pytest.approx(e * (202 + 198) - 198, abs=EXACT)

    # Flop: Hero (BB, out of position) jams 195; AsKd calls all-in, JcTc folds: r = 1.
    f = _flop_oop()
    ce = _ce(f, d)
    o = evaluate_action(f, HERO, d, ce, allin(f), facing_respond(arr(jt=1), arr(ak=1)))
    called = next(b for b in o.branches if b.label == "Villain calls")
    e_ak = float(ce.vs(arr(ak=1)).equity)
    assert called.realisation == 1.0
    assert called.value_chips == pytest.approx(e_ak * (10 + 195 + 195) - 195, abs=EXACT)

    # Flop: Hero bets 5, JcTc jams to 195 and Hero calls the jam: s3 pot = 10 + 5 + 195,
    # c = 190, final 400; value = e·400 − (5 + 190), r = 1.
    respond = facing_respond(arr(ak=1), arr(), {195: arr(jt=1)})
    o = evaluate_action(f, HERO, d, ce, option(f, "bet 50%"), respond)
    jam = o.branches[-1]
    e_jt = float(ce.vs(arr(jt=1)).equity)
    assert jam.label == "Villain raises to 195 — Hero calls"
    assert jam.realisation == 1.0
    assert jam.value_chips == pytest.approx(e_jt * 400 - 195, abs=EXACT)


def test_call_ev_uses_realisation():
    # BTN opens to 5; Hero is BB (out of position) facing it: P = 7, put = 3, r = 0.80.
    s0 = new_hand(0)
    s = apply(s0, raise_to(s0, 2.5))
    assert s.to_act == 1 and total_pot(s) == 7
    d = D()
    ce = _ce(s, d)
    e = float(ce.vs(d).equity)
    o = evaluate_action(s, HERO, d, ce, option(s, "call"), _never)
    assert o.put == 3
    assert o.realisation == 0.8
    assert o.ev_chips == pytest.approx(0.8 * e * (7 + 3) - 3, abs=EXACT)

    # Hero in position (BTN facing a 3-bet to 15): r = 1.
    s3 = apply(s, raise_to(s, 3.0))
    assert s3.to_act == 0 and total_pot(s3) == 20
    o = evaluate_action(s3, HERO, d, ce, option(s3, "call"), _never)
    assert o.realisation == 1.0
    assert o.ev_chips == pytest.approx(e * (20 + 10) - 10, abs=EXACT)


def test_check_ev_uses_realisation():
    f = _flop_oop()
    d = D()
    ce = _ce(f, d)
    e = float(ce.vs(d).equity)
    o = evaluate_action(f, HERO, d, ce, option(f, "check"), _never)
    assert o.realisation == 0.88
    assert o.ev_chips == pytest.approx(0.88 * e * 10, abs=EXACT)
    ip = _check(f)  # BTN checks behind: in position, r = 1
    o = evaluate_action(ip, HERO, d, ce, option(ip, "check"), _never)
    assert o.realisation == 1.0
    assert o.ev_chips == pytest.approx(e * 10, abs=EXACT)


def test_bet_called_branch_uses_realisation():
    # Flop, Hero (BB) bets 5 into 10 out of position; JcTc folds, AsKd calls (vcall 5).
    f = _flop_oop()
    d = D()
    ce = _ce(f, d)
    o = evaluate_action(f, HERO, d, ce, option(f, "bet 50%"), facing_respond(arr(jt=1), arr(ak=1)))
    folds, calls = o.branches
    e = float(ce.vs(arr(ak=1)).equity)
    assert folds.label == "Villain folds" and folds.realisation == 1.0
    assert folds.value_chips == 10.0
    assert calls.label == "Villain calls" and calls.realisation == 0.88
    assert calls.value_chips == pytest.approx(0.88 * e * (10 + 5 + 5) - 5, abs=EXACT)
    assert o.realisation == 1.0  # a bet's factors live on its branches
    assert o.ev_chips == pytest.approx(0.5 * 10 + 0.5 * calls.value_chips, abs=EXACT)


def test_reraise_call_branch_uses_realisation():
    # Flop, Hero (BB) bets 5; JcTc raises to 15 (not all-in) and Hero calls: s3 pot =
    # 10 + 5 + 15 = 30, c = 10, final 40; value = 0.88·e·40 − (5 + 10).
    f = _flop_oop()
    d = D()
    ce = _ce(f, d)
    respond = facing_respond(arr(ak=1), arr(), {15: arr(jt=1)})
    o = evaluate_action(f, HERO, d, ce, option(f, "bet 50%"), respond)
    rr = o.branches[-1]
    e = float(ce.vs(arr(jt=1)).equity)
    assert rr.label == "Villain raises to 15 — Hero calls"
    assert rr.realisation == 0.88
    assert rr.value_chips == pytest.approx(0.88 * e * 40 - 15, abs=EXACT)

    # AsKd raises instead: the realised call is worse than −put, Hero folds, r is unused (1).
    respond = facing_respond(arr(jt=1), arr(), {15: arr(ak=1)})
    o = evaluate_action(f, HERO, d, ce, option(f, "bet 50%"), respond)
    rr = o.branches[-1]
    assert rr.label == "Villain raises to 15 — Hero folds"
    assert rr.value_chips == -5.0 and rr.realisation == 1.0


# BB facing a BTN open to 5 (M9 Task 7), for every profile's BTN: hands with whole-range
# equity < 0.40 are gated, 0.40-0.45 hands (plausible 3-bet bluffs) are only reported in the
# sign-off table.
TRASH_GATED = ("9h5s", "7d5s", "6c4h", "Jc3d")
TRASH_REPORTED = ("Qs2h", "Qs3c", "Jd6d", "Jc5h")
TRASH_GAP_MAX_BB = 0.25


def bb_vs_open(hand: str, profile: str = "tag", samples: int = 40_000):
    """``solve()`` for Hero in the BB facing ``profile``'s BTN open to 5 with ``hand``."""
    villain = load_profile(profile)
    s0 = new_hand(0)
    open_ = raise_to(s0, 2.5)
    tracker = RangeTracker(villain, 0)
    tracker.observe(s0, open_)
    s = apply(s0, open_)
    hero = parse_cards(hand)
    d = visible_range(tracker.current, hero, ())
    return solve(s, hero, d, villain_respond(villain), rng=random.Random(0), samples=samples)


def raise_gap_bb(sol) -> float:
    """Best raise (any size, all-in included) minus the better of call and fold, in bb."""
    kinds = {o.option.action.kind: o for o in sol.options}
    base = max(kinds[ActionKind.CALL].ev_chips, kinds[ActionKind.FOLD].ev_chips)
    best_raise = max(o.ev_chips for o in sol.options if o.option.action.kind == ActionKind.RAISE)
    return (best_raise - base) / 2


@pytest.mark.slow
@pytest.mark.parametrize("profile", PROFILE_NAMES)
def test_bb_trash_3bet_not_best(profile):
    """A hand under 0.40 equity against the open range gains at most 0.25 bb by 3-betting
    (Jc3d is 0.41 against LAG's wider open, so it is reported there, not gated)."""
    gated = 0
    for hand in TRASH_GATED:
        sol = bb_vs_open(hand, profile)
        if sol.equity >= 0.40:
            continue
        gated += 1
        gap = raise_gap_bb(sol)
        assert gap <= TRASH_GAP_MAX_BB, (hand, gap)
    assert gated >= 3
