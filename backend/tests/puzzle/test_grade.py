import random
from dataclasses import replace

import pytest
from test_solve import HERO, D, arr, facing_respond, generic_respond, river_spot

from poker_trainer.game.state import Action, ActionKind, Street, new_hand, total_pot
from poker_trainer.puzzle.grade import Answer, grade
from poker_trainer.puzzle.model import Option, OptionEV, Puzzle, RangeView, Solution, Spot
from poker_trainer.puzzle.solve import solve
from poker_trainer.villain.profiles import load_profile


def _ev(label, action, ev, *, fold=None, eq_c=None, ahead_c=None, req=None, put=0):
    return OptionEV(
        option=Option(label, action),
        ev_chips=ev,
        fold_freq=fold,
        equity_vs_continue=eq_c,
        ahead_vs_continue=ahead_c,
        equity_vs_continue_se=None,
        required_fold_equity=req,
        put=put,
        continue_range=None,
        branches=(),
        simplifications=(),
    )


def _puzzle(*, evs=None, equity=0.5, ahead_now=None, profile_version=None):
    """River puzzle (Hero in position, P = 10) with a hand-built Solution."""
    s = river_spot("checked")
    me = s.to_act
    sol0 = solve(s, HERO, D(), generic_respond, rng=random.Random(0), samples=2000)
    options = tuple(evs) if evs is not None else sol0.options
    sol = Solution(
        equity=equity,
        equity_std_error=0.0,
        equity_exact=True,
        ahead_now=ahead_now,
        pot_odds=0.0,
        options=options,
        best=max(range(len(options)), key=lambda i: options[i].ev_chips),
        combo_equity=sol0.combo_equity,
        category_breakdown=None,
        simplifications=(),
    )
    prof = load_profile("tag")
    spot = Spot(
        seed=0,
        attempt=0,
        state=s,
        hero_seat=me,
        hero=HERO,
        villain_hole=(0, 1),
        runout=(),
        profile="tag",
        profile_version=prof.version if profile_version is None else profile_version,
        categories_version=1,
        steps=(RangeView("d", s.street, D()),),
    )
    return Puzzle(spot, sol), me


def _verdict_puzzle(loss_chips):
    """P = 10; best EV 5.0, chosen (bet) EV 5.0 - loss."""
    p, me = _puzzle(
        evs=[
            _ev("check", Action(1 - 1, ActionKind.CHECK, Street.RIVER), 5.0),
            _ev("bet 50%", Action(0, ActionKind.BET, Street.RIVER, 5), 5.0 - loss_chips),
        ]
    )
    return p, Action(me, ActionKind.BET, Street.RIVER, 5)


@pytest.mark.parametrize(
    "loss,expected",
    [
        (0.0, "best"),
        (0.5, "best"),
        (1.0, "fine"),  # 0.10 * P
        (1.01, "mistake"),
        (2.5, "mistake"),
        (2.51, "blunder"),
    ],
)
def test_verdict_boundaries(loss, expected):
    p, bet = _verdict_puzzle(loss)
    g = grade(p, Answer(bet, 0.5))
    assert g.verdict == expected
    assert g.ev_loss_chips == pytest.approx(loss)
    assert g.ev_loss_bb == pytest.approx(loss / 2)


def test_pot_is_total_pot():
    p, _ = _verdict_puzzle(0)
    assert total_pot(p.spot.state) == 10


@pytest.mark.parametrize("err,expected", [(0.05, "great"), (0.10, "good"), (0.1001, "off")])
def test_equity_score_boundaries(err, expected):
    p, bet = _verdict_puzzle(0)
    g = grade(p, Answer(bet, 0.5 + err))
    assert g.equity_score == expected
    assert g.equity_error == pytest.approx(err)


def test_no_range_read_on_river():
    p, bet = _verdict_puzzle(0)
    g = grade(p, Answer(bet, 0.5, range_read_guess=0.9))
    assert g.range_read_error is None and g.range_read_score is None


def _flop_puzzle(options, ahead_now=0.6):
    p, _ = _puzzle()
    s = p.spot.state
    flop = replace(s, street=Street.FLOP, board=s.board[:3])
    sol = replace(p.solution, options=tuple(options), best=0, ahead_now=ahead_now)
    return Puzzle(replace(p.spot, state=flop), sol)


def test_range_read_scored_before_river():
    bet = Action(0, ActionKind.BET, Street.FLOP, 5)
    chk = Action(0, ActionKind.CHECK, Street.FLOP)
    p = _flop_puzzle([_ev("bet", bet, 1.0), _ev("chk", chk, 0.0)])
    g = grade(p, Answer(bet, 0.5, range_read_guess=0.65))
    assert g.range_read_error == pytest.approx(0.05)
    assert g.range_read_score == "great"
    assert grade(p, Answer(bet, 0.5, range_read_guess=0.45)).range_read_score == "off"
    assert grade(p, Answer(bet, 0.5)).range_read_score is None


def _intent_puzzle(*, ahead, eq_c, equity=0.5):
    bet = Action(0, ActionKind.BET, Street.RIVER, 5)
    chk = Action(0, ActionKind.CHECK, Street.RIVER)
    p, _ = _puzzle(
        evs=[
            _ev("check", chk, 1.0),
            _ev("bet 50%", bet, 2.0, fold=0.4, eq_c=eq_c, ahead_c=ahead, req=0.25, put=5),
        ],
        equity=equity,
    )
    return p, bet


def test_intent_truths_and_flag():
    p, bet = _intent_puzzle(ahead=0.7, eq_c=0.7)
    g = grade(p, Answer(bet, 0.5, intent="value"))
    assert g.intent_truth == "value" and g.intent_flag is None
    p, bet = _intent_puzzle(ahead=0.1, eq_c=0.1)  # river: no semi-bluff
    g = grade(p, Answer(bet, 0.5, intent="value"))
    assert g.intent_truth == "bluff"
    assert g.intent_flag == "You called this a value bet, but only better hands continue (bluff)."
    p, bet = _intent_puzzle(ahead=None, eq_c=None, equity=0.3)
    assert grade(p, Answer(bet, 0.5)).intent_truth == "bluff"
    p, bet = _intent_puzzle(ahead=None, eq_c=None, equity=0.7)
    g = grade(p, Answer(bet, 0.5))
    assert g.intent_truth == "value" and g.intent_flag is None


def test_semi_bluff_truth_before_river():
    bet = Action(0, ActionKind.BET, Street.FLOP, 5)
    chk = Action(0, ActionKind.CHECK, Street.FLOP)
    p = _flop_puzzle(
        [_ev("bet", bet, 2.0, fold=0.4, eq_c=0.35, ahead_c=0.2, req=0.25, put=5), _ev("c", chk, 1)]
    )
    g = grade(p, Answer(bet, 0.5, intent="bluff"))
    assert g.intent_truth == "semi_bluff"
    assert g.intent_flag is not None and "(semi_bluff)" in g.intent_flag
    p = _flop_puzzle(
        [_ev("bet", bet, 2.0, fold=0.4, eq_c=0.25, ahead_c=0.2, req=0.25, put=5), _ev("c", chk, 1)]
    )
    assert grade(p, Answer(bet, 0.5)).intent_truth == "bluff"


def test_bluff_check_and_none_for_non_aggressive():
    p, bet = _intent_puzzle(ahead=0.7, eq_c=0.7)
    assert grade(p, Answer(bet, 0.5)).bluff_check == (0.25, 0.4)
    chk = Action(0, ActionKind.CHECK, Street.RIVER)
    g = grade(p, Answer(chk, 0.5, intent="value"))
    assert g.bluff_check is None and g.intent_truth is None and g.intent_flag is None


def test_custom_size_scored_via_evaluate_action():
    p, me = _puzzle()
    custom = Action(me, ActionKind.BET, Street.RIVER, 7)
    respond = facing_respond(arr(jt=1), arr(ak=1))
    g = grade(p, Answer(custom, 0.5), respond=respond)
    assert g.chosen.option.action == custom
    assert g.chosen.put == 7
    assert g.chosen.fold_freq == pytest.approx(0.5)
    assert g.chosen.ev_chips == pytest.approx(0.5 * 10 + 0.5 * (0 * 24 - 7))
    assert g.bluff_check == pytest.approx((7 / 17, 0.5))


def test_illegal_custom_rejected():
    p, me = _puzzle()
    with pytest.raises(ValueError):
        grade(
            p,
            Answer(Action(me, ActionKind.BET, Street.RIVER, 10_000), 0.5),
            respond=generic_respond,
        )
    with pytest.raises(ValueError):
        grade(p, Answer(Action(me, ActionKind.CALL, Street.RIVER, 3), 0.5), respond=generic_respond)


def test_preflop_custom_rejected():
    p, _ = _puzzle()
    p = Puzzle(replace(p.spot, state=new_hand(0)), p.solution)
    with pytest.raises(ValueError):
        grade(
            p, Answer(Action(0, ActionKind.RAISE, Street.PREFLOP, 7), 0.5), respond=generic_respond
        )


def test_profile_version_mismatch_raises():
    p, me = _puzzle(profile_version=load_profile("tag").version + 1)
    custom = Action(me, ActionKind.BET, Street.RIVER, 7)
    with pytest.raises(ValueError, match="profile changed since this puzzle was generated"):
        grade(p, Answer(custom, 0.5))


def test_listed_option_needs_no_profile():
    p, _ = _puzzle(profile_version=999)
    opt = p.solution.options[0]
    assert grade(p, Answer(opt.option.action, 0.5)).chosen is opt
