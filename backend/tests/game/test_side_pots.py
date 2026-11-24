"""Side-pot settlement: layers, uncalled bets, folded chips, odd chips, conservation."""

from __future__ import annotations

import random

import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.settle import PotAward, settle, settle_pots
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    deal,
    is_terminal,
    legal_actions,
    live_seats,
    needs_board,
    new_hand,
    total_pot,
)
from poker_trainer.game.state import apply as apply_action

K = ActionKind


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    assert s.to_act is not None
    if kind == K.CALL:
        to = s.street_bets[s.to_act] + legal_actions(s).call
    return apply_action(s, Action(s.to_act, kind, s.street, to))


def h(text: str) -> tuple[int, int]:
    a, b = parse_cards(text)
    return a, b


def run_out(s: HandState, board: str) -> HandState:
    cards = parse_cards(board)
    while needs_board(s) or s.to_act is not None:
        if needs_board(s):
            k = len(s.board)
            s = deal(s, tuple(cards[k : k + (3 if k == 0 else 1)]))
        else:
            s = act(s, K.CHECK)
    return s


def test_three_all_ins_at_different_levels():
    start = (50, 100, 200, 400)  # BTN 0, SB 1, BB 2, CO 3 (acts first)
    s = new_hand(0, start)
    assert legal_actions(s).max_to == 200  # capped at what the BB can match
    s = act(s, K.RAISE, 200)  # CO jams
    s = act(s, K.CALL)  # BTN all-in for 50
    s = act(s, K.CALL)  # SB all-in for 100
    s = act(s, K.CALL)  # BB all-in for 200
    s = run_out(s, "2c3d4h8s9c")
    # BTN has the best hand, then SB, then BB, then CO.
    holes = (h("AsAh"), h("KsKh"), h("QsQh"), h("7c7d"))
    out = settle_pots(s, holes, start)
    assert out.pots == (
        PotAward(200, (0, 1, 2, 3), (0,)),
        PotAward(150, (1, 2, 3), (1,)),
        PotAward(200, (2, 3), (2,)),
    )
    assert out.stacks == (200, 150, 200, 200)
    assert sum(out.stacks) == sum(start)
    assert settle(s, holes) == out.stacks


def test_folded_seat_chips_stay_in_the_layers():
    start = (200, 200, 60, 200)  # BTN 0, SB 1, BB 2 (58 behind), CO 3
    s = new_hand(0, start)
    s = act(s, K.RAISE, 20)  # CO opens
    s = act(s, K.CALL)  # BTN calls 20
    s = act(s, K.FOLD)  # SB folds its 1
    s = act(s, K.RAISE, 60)  # BB jams 60
    s = act(s, K.CALL)  # CO calls
    s = act(s, K.FOLD)  # BTN folds its 20
    s = run_out(s, "2c3d4h8s9c")
    holes = (None, None, h("AsAh"), h("KsKh"))
    out = settle_pots(s, holes, start)
    # Main pot: 60 + 60 from BB and CO, plus the folded 20 and 1.
    assert out.pots == (PotAward(141, (2, 3), (2,)),)
    assert out.stacks == (180, 199, 141, 140)
    assert sum(out.stacks) == sum(start)


def test_folded_chips_above_an_all_in_go_to_the_side_pot():
    start = (30, 300, 300)  # BTN 0, SB 1, BB 2
    s = new_hand(0, start)
    s = act(s, K.RAISE, 30)  # BTN all-in for 30
    s = act(s, K.RAISE, 100)  # SB raises to 100
    s = act(s, K.FOLD)  # BB folds its 2
    s = run_out(s, "2c3d4h8s9c")
    # BTN beats SB: BTN takes the main pot; the SB's 70 above 30 is uncalled and returned.
    out = settle_pots(s, (h("AsAh"), h("KsKh"), None), start)
    assert out.pots == (PotAward(62, (0, 1), (0,)),)
    assert out.stacks == (62, 270, 298)


def test_uncalled_bet_is_returned_not_listed():
    start = (200, 200, 40)  # BTN 0, SB 1, BB 2
    s = new_hand(0, start)
    s = act(s, K.RAISE, 200)  # BTN jams: the SB could still call it
    s = act(s, K.FOLD)  # SB
    s = act(s, K.CALL)  # BB all-in
    s = deal(s, tuple(parse_cards("2c3d4h")))
    assert s.to_act is None  # one seat with chips: run out
    s = run_out(s, "2c3d4h8s9c")
    out = settle_pots(s, (h("7c7d"), None, h("AsAh")), start)
    assert out.pots == (PotAward(81, (0, 2), (2,)),)
    assert out.stacks == (160, 199, 81)


def test_uncalled_raise_over_an_all_in_is_returned():
    start = (400, 400, 400, 400, 50)  # BTN 0, SB 1, BB 2, UTG 3, CO 4
    s = new_hand(0, start)
    s = act(s, K.RAISE, 50)  # UTG
    s = act(s, K.CALL)  # CO all-in for 50
    s = act(s, K.RAISE, 400)  # BTN jams 400
    s = act(s, K.FOLD)  # SB
    s = act(s, K.FOLD)  # BB
    s = act(s, K.FOLD)  # UTG folds its 50
    assert s.folded is None  # BTN and the all-in CO are still in
    s = run_out(s, "2c3d4h8s9c")
    out = settle_pots(s, (h("AsAh"), None, None, None, h("KsKh")), start)
    # Main pot: 50 x 3 (UTG, CO, BTN) + 1 + 2. The BTN's other 350 is returned.
    assert out.pots == (PotAward(153, (0, 4), (0,)),)
    assert out.stacks == (503, 399, 398, 350, 0)


def test_three_way_tie_odd_chip_clockwise_from_the_small_blind():
    start = (200, 200, 200, 200)  # BTN 3 below, so SB 0, BB 1, CO 2
    s = new_hand(3, start)  # first to act: seat 2
    s = act(s, K.RAISE, 6)  # seat 2
    s = act(s, K.CALL)  # BTN 3
    s = act(s, K.CALL)  # SB 0
    s = act(s, K.FOLD)  # BB 1 folds its 2: pot 6 * 3 + 2 = 20
    s = run_out(s, "AsKsQsJsTs")  # a royal flush on board: every live seat ties
    holes = (h("2c3d"), None, h("2d3c"), h("2h3h"))
    out = settle_pots(s, holes, start)
    assert out.pots == (PotAward(20, (0, 2, 3), (0, 2, 3)),)
    # 20 = 3 * 6 + 2: the odd chips go to seat 0 (button+1), then seat 2.
    assert out.stacks == (194 + 7, 198, 194 + 7, 194 + 6)


def test_odd_chip_order_wraps_round_the_table():
    start = (200, 200, 200)  # BTN 1, SB 2, BB 0
    s = new_hand(1, start)
    s = act(s, K.RAISE, 7)  # BTN
    s = act(s, K.FOLD)  # SB folds its 1
    s = act(s, K.CALL)  # BB: pot 15
    s = run_out(s, "AsKsQsJsTs")
    out = settle_pots(s, (h("2c3d"), h("2d3c"), None), start)
    assert out.pots == (PotAward(15, (0, 1), (0, 1)),)
    # Clockwise from button+1 (seat 2, folded): seat 0 comes before seat 1.
    assert out.stacks == (193 + 8, 193 + 7, 199)


def test_everyone_folds_to_one_seat():
    start = (200, 200, 200, 200, 200)
    s = new_hand(0, start)
    s = act(s, K.RAISE, 5)  # UTG
    for _ in range(4):
        s = act(s, K.FOLD)
    assert is_terminal(s) and live_seats(s) == (3,)
    out = settle_pots(s, (None,) * 5, start)
    assert out.pots == (PotAward(8, (3,), (3,)),)
    assert out.stacks == (200, 199, 198, 203, 200)
    assert settle(s, (None,) * 5) == out.stacks


def test_settle_pots_rejects_unfinished_and_mismatched():
    start = (200, 200, 200)
    s = new_hand(0, start)
    with pytest.raises(ValueError):
        settle_pots(s, (None,) * 3, start)
    s = act(s, K.FOLD)
    s = act(s, K.FOLD)
    with pytest.raises(ValueError):
        settle_pots(s, (None,) * 3, (200, 200, 201))


def _random_hand(seed: int) -> None:
    rng = random.Random(f"five-seat-conservation:{seed}")
    n = 5
    start = tuple(rng.choice([rng.randint(3, 40), rng.randint(3, 600)]) for _ in range(n))
    deck = list(range(52))
    rng.shuffle(deck)
    holes = tuple((deck[2 * i], deck[2 * i + 1]) for i in range(n))
    board = deck[2 * n : 2 * n + 5]
    s = new_hand(rng.randrange(n), start)
    while not is_terminal(s):
        assert sum(s.stacks) + total_pot(s) == s.total_chips
        if needs_board(s):
            k = len(s.board)
            s = deal(s, tuple(board[k : k + (3 if k == 0 else 1)]))
            continue
        lg = legal_actions(s)
        me = s.to_act
        assert me is not None and s.stacks[me] > 0
        options = []
        if lg.fold:
            options.append(Action(me, K.FOLD, s.street))
        if lg.check:
            options += [Action(me, K.CHECK, s.street)] * 2
        if lg.call:
            options += [Action(me, K.CALL, s.street, s.street_bets[me] + lg.call)] * 3
        if lg.aggressive is not None:
            assert lg.min_to is not None and lg.max_to is not None
            for to in {lg.min_to, lg.max_to, rng.randint(lg.min_to, lg.max_to)}:
                options.append(Action(me, lg.aggressive, s.street, to))
        s = apply_action(s, rng.choice(options))
    out = settle_pots(s, holes, start)
    assert sum(out.stacks) == sum(start)
    assert all(x >= 0 for x in out.stacks)
    paid = [start[i] - s.stacks[i] for i in range(n)]
    returned = sum(out.stacks) - sum(s.stacks) - sum(p.amount for p in out.pots)
    assert returned >= 0
    assert sum(p.amount for p in out.pots) + returned == total_pot(s) == sum(paid)
    live = set(live_seats(s))
    for p in out.pots:
        assert p.amount > 0 and p.winners and set(p.winners) <= set(p.eligible) <= live
    for i in range(n):  # a seat that wins no pot gets back at most its uncalled excess
        if not any(i in p.winners for p in out.pots):
            excess = paid[i] - max(paid[j] for j in range(n) if j != i)
            assert out.stacks[i] == s.stacks[i] + max(excess, 0)
    assert settle(s, holes) == out.stacks


def test_conservation_over_random_five_seat_hands():
    for seed in range(2000):
        _random_hand(seed)
