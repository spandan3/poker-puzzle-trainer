import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.state import (
    BB,
    Action,
    ActionKind,
    HandState,
    Street,
    amount_to_call,
    apply,
    deal,
    is_terminal,
    last_aggressor,
    legal_actions,
    needs_board,
    new_hand,
    position_name,
    pot_odds,
    total_pot,
)

K = ActionKind


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    assert s.to_act is not None
    return apply(s, Action(s.to_act, kind, s.street, to))


def test_new_hand_blinds():
    s = new_hand(0)
    assert s.stacks == (199, 198)
    assert s.street_bets == (1, 2)
    assert s.to_act == 0
    assert pot_odds(s) == 1 / 4
    assert amount_to_call(s) == 1
    assert total_pot(s) == 3
    assert position_name(s, 0) == "BTN" and position_name(s, 1) == "BB"
    lg = legal_actions(s)
    assert lg.aggressive == K.RAISE
    assert lg.min_to == 4
    assert lg.fold and not lg.check and lg.call == 1


def test_preflop_bb_option():
    s = act(new_hand(0), K.CALL)
    assert s.to_act == 1
    lg = legal_actions(s)
    assert lg.check and not lg.fold
    s = act(s, K.CHECK)
    assert needs_board(s)
    assert s.to_act is None


def test_min_raise():
    s = act(new_hand(0), K.RAISE, 6)
    lg = legal_actions(s)
    assert lg.min_to == 10
    assert lg.max_to == 200


def test_short_allin_does_not_reopen():
    s = new_hand(0, stacks=(200, 9))
    s = act(s, K.RAISE, 6)
    s = act(s, K.RAISE, 9)
    assert s.to_act == 0
    lg = legal_actions(s)
    assert lg.aggressive is None
    assert lg.call == 3


def test_short_stack_min_equals_max():
    s = act(new_hand(0, stacks=(200, 9)), K.RAISE, 6)
    lg = legal_actions(s)
    assert lg.min_to == lg.max_to == 9


def test_allin_called_needs_only_board():
    s = act(new_hand(0), K.RAISE, 200)
    s = act(s, K.CALL)
    assert s.to_act is None and needs_board(s)
    assert s.stacks == (0, 0)
    s = deal(s, parse_cards("2c 3d 4h"))
    assert needs_board(s)
    s = deal(s, parse_cards("5s"))
    s = deal(s, parse_cards("6s"))
    assert is_terminal(s) and not needs_board(s)
    assert total_pot(s) == 400
    with pytest.raises(ValueError):
        legal_actions(s)


def test_fold_terminal():
    s = act(new_hand(0), K.FOLD)
    assert is_terminal(s) and s.folded == 0 and s.to_act is None
    assert not needs_board(s)


def test_postflop_order():
    s = act(act(new_hand(0), K.CALL), K.CHECK)
    s = deal(s, parse_cards("2c 3d 4h"))
    assert s.to_act == 1 and s.street == Street.FLOP
    assert s.pot == 4 and s.street_bets == (0, 0) and s.last_raise == BB
    lg = legal_actions(s)
    assert lg.aggressive == K.BET and lg.min_to == 2
    s = act(s, K.CHECK)
    assert s.to_act == 0
    s = act(s, K.CHECK)
    assert needs_board(s)


def test_last_aggressor():
    s = act(new_hand(0), K.RAISE, 6)
    s = act(s, K.CALL)
    assert last_aggressor(s, Street.PREFLOP) == 0
    assert last_aggressor(s, Street.FLOP) is None


def test_illegal_actions_raise():
    s = new_hand(0)
    with pytest.raises(ValueError, match="illegal action"):
        apply(s, Action(1, K.CALL, Street.PREFLOP))
    with pytest.raises(ValueError, match="illegal action"):
        act(s, K.CHECK)
    with pytest.raises(ValueError, match="illegal action"):
        act(s, K.RAISE, 3)
    with pytest.raises(ValueError, match="illegal action"):
        act(s, K.RAISE, 201)
    f = deal(act(act(s, K.CALL), K.CHECK), parse_cards("2c 3d 4h"))
    with pytest.raises(ValueError, match="illegal action"):
        act(f, K.FOLD)
    with pytest.raises(ValueError, match="illegal action"):
        act(f, K.BET, 1)
    with pytest.raises(ValueError, match="illegal action"):
        act(f, K.RAISE, 4)


def test_deal_rejects_duplicates():
    s = act(act(new_hand(0), K.CALL), K.CHECK)
    s = deal(s, parse_cards("2c 3d 4h"))
    s = act(act(s, K.CHECK), K.CHECK)
    with pytest.raises(ValueError, match="duplicate"):
        deal(s, parse_cards("2c"))


@settings(max_examples=150, deadline=None)
@given(
    st.data(),
    st.integers(1, 300),
    st.integers(1, 300),
    st.integers(0, 1),
    st.permutations(list(range(52))),
)
def test_chips_conserved_property(data, a, b, button, deck):
    s = new_hand(button, (a, b))
    total = a + b
    assert s.total_chips == total
    deck = list(deck)
    n = 0
    while not is_terminal(s):
        assert min(s.stacks) >= 0
        assert sum(s.stacks) + s.pot + sum(s.street_bets) == total
        if needs_board(s):
            k = 3 if s.street == Street.PREFLOP else 1
            s = deal(s, tuple(deck[:k]))
            deck = deck[k:]
            continue
        lg = legal_actions(s)
        opts = []
        if lg.fold:
            opts.append(K.FOLD)
        if lg.check:
            opts.append(K.CHECK)
        if lg.call:
            opts.append(K.CALL)
        if lg.aggressive is not None and n < 12:
            opts.append(lg.aggressive)
        kind = data.draw(st.sampled_from(opts))
        to = 0
        if kind in (K.BET, K.RAISE):
            to = data.draw(st.integers(lg.min_to, lg.max_to))
        s = act(s, kind, to)
        n += 1
    assert min(s.stacks) >= 0
    assert sum(s.stacks) + s.pot + sum(s.street_bets) == total
