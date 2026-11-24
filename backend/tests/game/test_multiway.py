"""N-seat betting rules: blinds, order of action, the bet cap, reopening, run-outs."""

from __future__ import annotations

import pytest

from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    Street,
    active_seats,
    apply,
    deal,
    folded_seats,
    is_terminal,
    legal_actions,
    live_seats,
    needs_board,
    new_hand,
    position_name,
    total_pot,
)

K = ActionKind
FLOP = (0, 5, 10)


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    assert s.to_act is not None
    if kind == K.CALL:
        to = s.street_bets[s.to_act] + legal_actions(s).call
    return apply(s, Action(s.to_act, kind, s.street, to))


def chips(s: HandState) -> int:
    return sum(s.stacks) + total_pot(s)


def test_three_seat_blinds_and_first_actor():
    s = new_hand(0, (200, 200, 200))
    assert s.street_bets == (0, 1, 2)
    assert s.stacks == (200, 199, 198)
    assert s.to_act == 0  # button+3 is the button itself three-handed
    assert [position_name(s, i) for i in range(3)] == ["BTN", "SB", "BB"]


def test_five_seat_blinds_and_first_actor():
    s = new_hand(3, (200,) * 5)
    assert s.street_bets == (2, 0, 0, 0, 1)  # SB seat 4, BB seat 0
    assert s.to_act == 1  # UTG
    assert [position_name(s, i) for i in range(5)] == ["BB", "UTG", "CO", "BTN", "SB"]
    assert s.total_chips == 1000
    assert s.last_raise == 2


def test_four_and_six_seat_position_names():
    assert [position_name(new_hand(0, (200,) * 4), i) for i in range(4)] == [
        "BTN",
        "SB",
        "BB",
        "CO",
    ]
    assert [position_name(new_hand(0, (200,) * 6), i) for i in range(6)] == [
        "BTN",
        "SB",
        "BB",
        "UTG",
        "HJ",
        "CO",
    ]


def test_multiway_blinds_need_stacks_above_the_big_blind():
    with pytest.raises(ValueError, match="exceed the big blind"):
        new_hand(0, (200, 200, 2))
    with pytest.raises(ValueError, match="exceed the big blind"):
        new_hand(1, (200, 1, 200, 200))
    with pytest.raises(ValueError):
        new_hand(0, (200,) * 7)
    with pytest.raises(ValueError):
        new_hand(5, (200,) * 5)


def test_folds_around_to_the_big_blind_end_the_hand():
    s = new_hand(0, (200,) * 5)  # UTG 3, CO 4, BTN 0, SB 1, BB 2
    for seat in (3, 4, 0):
        assert s.to_act == seat
        s = act(s, K.FOLD)
        assert s.folded is None
    assert s.to_act == 1
    s = act(s, K.FOLD)
    assert s.folded == 1 and is_terminal(s) and s.to_act is None
    assert folded_seats(s) == {3, 4, 0, 1}
    assert live_seats(s) == (2,)


def test_open_and_calls_then_post_flop_order():
    s = new_hand(0, (200,) * 5)
    s = act(s, K.RAISE, 5)  # UTG opens
    s = act(s, K.FOLD)  # CO
    s = act(s, K.CALL)  # BTN
    s = act(s, K.FOLD)  # SB
    assert s.to_act == 2
    s = act(s, K.CALL)  # BB closes
    assert s.to_act is None and needs_board(s)
    s = deal(s, FLOP)
    assert s.pot == 5 * 3 + 1
    assert s.street_bets == (0,) * 5
    # First live seat clockwise from the button: SB folded, so the BB.
    assert s.to_act == 2
    s = act(s, K.CHECK)
    assert s.to_act == 3
    s = act(s, K.BET, 10)
    assert s.to_act == 0
    s = act(s, K.CALL)
    assert s.to_act == 2
    s = act(s, K.FOLD)
    assert s.to_act is None and s.folded is None and needs_board(s)
    assert live_seats(s) == (0, 3)
    assert chips(s) == s.total_chips


def test_big_blind_gets_its_option_after_limps():
    # The engine allows limps (the bots and Hero never limp): the BB may still check or raise.
    s = new_hand(0, (200, 200, 200))
    s = act(s, K.CALL)  # BTN limps
    s = act(s, K.CALL)  # SB completes
    assert s.to_act == 2
    lg = legal_actions(s)
    assert lg.check and lg.aggressive == K.RAISE
    s = act(s, K.CHECK)
    assert s.to_act is None and needs_board(s)


def test_all_in_seats_are_skipped():
    s = new_hand(0, (50, 200, 200, 200, 200))  # UTG 3, CO 4, BTN 0
    s = act(s, K.RAISE, 6)  # UTG
    s = act(s, K.FOLD)  # CO
    s = act(s, K.RAISE, 50)  # BTN all-in
    assert active_seats(s) == (1, 2, 3)
    s = act(s, K.FOLD)  # SB
    s = act(s, K.CALL)  # BB
    assert s.to_act == 3
    s = act(s, K.CALL)  # UTG
    assert s.to_act is None
    s = deal(s, FLOP)
    assert s.to_act == 2  # BB first post-flop; the BTN is all-in
    s = act(s, K.CHECK)
    assert s.to_act == 3
    s = act(s, K.BET, 20)
    assert s.to_act == 2  # skips the all-in button and the folded SB


def test_bet_cap_is_the_deepest_other_live_seat():
    s = new_hand(0, (500, 100, 300))  # BTN 0, SB 1, BB 2; BTN acts first
    lg = legal_actions(s)
    assert lg.max_to == 300  # the BB can match up to 300, the SB only 100
    s = act(s, K.RAISE, 6)
    lg = legal_actions(s)
    assert s.to_act == 1 and lg.max_to == 100  # the SB is capped by its own stack
    s = act(s, K.RAISE, 100)  # SB all-in
    assert s.to_act == 2
    lg = legal_actions(s)
    assert lg.max_to == 300  # the BB can still raise over the all-in: the BTN covers it
    s = act(s, K.RAISE, 300)
    lg = legal_actions(s)
    assert s.to_act == 0 and lg.aggressive is None and lg.call == 294
    s = act(s, K.CALL)
    assert s.to_act is None
    assert s.stacks == (200, 0, 0)  # the bet exceeds the SB's stack: a side pot


def test_cap_ignores_all_in_seats_when_nobody_can_match():
    s = new_hand(0, (500, 100, 300))
    s = act(s, K.RAISE, 300)  # BTN raises to what the BB can match
    s = act(s, K.CALL)  # SB calls all-in for less (100)
    assert s.street_bets == (300, 100, 2)
    s = act(s, K.CALL)  # BB calls all-in
    assert s.to_act is None
    assert active_seats(s) == (0,)


def test_short_all_in_does_not_reopen_raising():
    s = new_hand(0, (200, 200, 25))  # BTN 0, SB 1, BB 2 (23 behind after the blind)
    s = act(s, K.RAISE, 20)  # BTN opens to 20 (a raise of 18)
    s = act(s, K.CALL)  # SB calls 20
    s = act(s, K.RAISE, 25)  # BB all-in for 25: a raise of 5, short of 18
    assert s.last_raise == 18
    assert s.to_act == 0
    lg = legal_actions(s)
    assert lg.aggressive is None and lg.call == 5 and lg.fold
    s = act(s, K.CALL)
    assert s.to_act == 1
    lg = legal_actions(s)
    assert lg.aggressive is None
    s = act(s, K.CALL)
    assert s.to_act is None


def test_call_for_less_then_a_full_raise_leaves_the_next_seat_able_to_raise():
    s = new_hand(0, (200, 200, 200, 25))  # BTN 0, SB 1, BB 2, CO 3 (first)
    s = act(s, K.RAISE, 20)  # seat 3 acts first and opens to 20 (a raise of 18)
    assert s.history[-1].seat == 3
    s = act(s, K.CALL)  # BTN
    s = act(s, K.CALL)  # SB
    s = act(s, K.RAISE, 60)  # BB 3-bets to 60: full (40 >= 18)
    assert s.to_act == 3
    s = act(s, K.CALL)  # CO all-in for 25 total, for less
    assert s.stacks[3] == 0
    assert s.to_act == 0
    assert legal_actions(s).aggressive == K.RAISE  # the BB's full raise reopened it


def test_short_all_in_does_not_stop_an_unacted_seat_raising():
    s = new_hand(0, (200, 200, 200, 3, 200))  # BTN 0, SB 1, BB 2, UTG 3, CO 4
    s = act(s, K.RAISE, 3)  # UTG all-in for 3: a raise of 1, short of the 2 minimum
    assert s.stacks[3] == 0 and s.last_raise == 2
    assert s.to_act == 4
    lg = legal_actions(s)
    # The CO has not acted, so the short all-in does not close its raising.
    assert lg.aggressive == K.RAISE
    assert lg.min_to == 5


def test_short_all_in_after_full_raise_still_reopens():
    # BTN opens, SB 3-bets in full, BB jams short. The BTN acted before the full raise,
    # so it may re-raise (generalised rule: some full raise came after its last action).
    s = new_hand(0, (300, 300, 50))
    s = act(s, K.RAISE, 6)  # BTN (raise 4)
    s = act(s, K.RAISE, 20)  # SB (raise 14, full)
    s = act(s, K.RAISE, 50)  # BB all-in (raise 30, full)
    assert s.to_act == 0
    assert legal_actions(s).aggressive == K.RAISE
    s = new_hand(0, (300, 300, 30))
    s = act(s, K.RAISE, 6)
    s = act(s, K.RAISE, 20)  # SB full raise of 14
    s = act(s, K.RAISE, 30)  # BB all-in: a raise of 10, short of 14
    assert s.to_act == 0
    assert legal_actions(s).aggressive == K.RAISE  # the SB's full raise still counts for BTN
    s = act(s, K.CALL)
    assert s.to_act == 1
    assert legal_actions(s).aggressive is None  # only a short all-in since the SB's raise


def test_run_out_when_one_seat_can_still_bet():
    s = new_hand(0, (100, 100, 400))
    s = act(s, K.RAISE, 100)  # BTN all-in
    s = act(s, K.CALL)  # SB all-in
    assert s.to_act == 2
    s = act(s, K.CALL)  # BB calls; it alone has chips behind
    assert s.to_act is None and needs_board(s)
    s = deal(s, FLOP)
    assert s.to_act is None and needs_board(s)
    s = deal(s, (15,))
    s = deal(s, (20,))
    assert s.street == Street.RIVER and is_terminal(s)
    assert s.stacks == (0, 0, 300)


def test_last_active_seat_facing_an_all_in_must_still_act():
    s = new_hand(0, (100, 400, 400))
    s = act(s, K.RAISE, 100)  # BTN all-in
    s = act(s, K.FOLD)  # SB
    assert s.to_act == 2
    lg = legal_actions(s)
    assert lg.aggressive is None and lg.call == 98
    s = act(s, K.CALL)
    assert s.to_act is None and s.folded is None


def test_fold_leaving_an_all_in_seat_ends_the_hand():
    s = new_hand(0, (100, 400, 400))
    s = act(s, K.RAISE, 100)  # BTN all-in
    s = act(s, K.FOLD)  # SB
    s = act(s, K.FOLD)  # BB
    assert s.folded == 2 and is_terminal(s)
    assert live_seats(s) == (0,)


def test_fold_out_of_turn_and_wrong_seat_rejected():
    s = new_hand(0, (200,) * 5)
    with pytest.raises(ValueError):
        apply(s, Action(4, K.FOLD, Street.PREFLOP))
