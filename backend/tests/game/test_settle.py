import pytest

from poker_trainer.engine.cards import parse_cards
from poker_trainer.game.settle import settle
from poker_trainer.game.state import (
    Action,
    ActionKind,
    HandState,
    deal,
    legal_actions,
    needs_board,
    new_hand,
)
from poker_trainer.game.state import apply as apply_action

K = ActionKind


def act(s: HandState, kind: ActionKind, to: int = 0) -> HandState:
    assert s.to_act is not None
    if kind == K.CALL:
        to = s.street_bets[s.to_act] + legal_actions(s).call
    return apply_action(s, Action(s.to_act, kind, s.street, to))


def run_out(s: HandState, board: tuple[int, ...]) -> HandState:
    """Deal the board whenever a betting round is complete, checking down any open street."""
    while needs_board(s) or s.to_act is not None:
        if needs_board(s):
            n = 3 if not s.board else 1
            k = len(s.board)
            s = deal(s, board[k : k + n])
        else:
            s = act(s, K.CHECK)
    return s


def h(text: str) -> tuple[int, int]:
    a, b = parse_cards(text)
    return a, b


def test_button_fold_preflop_gives_blinds_to_bb():
    s = act(new_hand(0), K.FOLD)
    assert settle(s, (h("2c7d"), h("AsAh"))) == (199, 201)
    assert sum(settle(s, (h("2c7d"), h("AsAh")))) == s.total_chips


def test_fold_with_uneven_start_stacks():
    s = new_hand(1, (120, 340))  # seat 1 is the button
    s = act(s, K.RAISE, 6)
    s = act(s, K.RAISE, 18)  # seat 0 3-bets
    s = act(s, K.FOLD)  # the button folds its 6
    out = settle(s, (h("AsAh"), h("2c7d")))
    assert out == (126, 334)
    assert sum(out) == s.total_chips


def test_river_showdown_named_winner():
    board = parse_cards("Ks7h2c4d9s")
    s = new_hand(0, (120, 340))
    s = act(s, K.RAISE, 6)
    s = act(s, K.CALL)
    s = run_out(s, board)
    # Seat 0 has kings with the ace kicker; seat 1 has kings with a queen.
    out = settle(s, (h("AsKd"), h("KhQh")))
    assert out == (126, 334)
    assert sum(out) == s.total_chips
    flipped = settle(s, (h("KhQh"), h("AsKd")))
    assert flipped == (114, 346)


def test_board_plays_splits_evenly():
    board = parse_cards("AsKsQsJsTs")
    s = new_hand(1, (120, 340))
    s = act(s, K.RAISE, 6)
    s = act(s, K.CALL)
    s = run_out(s, board)
    out = settle(s, (h("2c3d"), h("4h5h")))
    assert out == (120, 340)
    assert sum(out) == s.total_chips


def test_allin_preflop_run_out_settles():
    board = parse_cards("Ks7h2c4d9s")
    s = new_hand(0, (120, 340))
    s = act(s, K.RAISE, 120)  # seat 0 jams its whole stack
    s = act(s, K.CALL)
    assert s.stacks == (0, 220)
    s = run_out(s, board)
    assert s.board == board
    out = settle(s, (h("2d3d"), h("AhAd")))  # seat 1 wins with aces
    assert out == (0, 460)
    assert sum(out) == s.total_chips
    out = settle(s, (h("AhAd"), h("2d3d")))
    assert out == (240, 220)
    assert sum(out) == s.total_chips


@pytest.mark.parametrize("street_actions", [0, 1])
def test_non_terminal_raises(street_actions):
    s = new_hand(0, (120, 340))
    if street_actions:
        s = act(s, K.CALL)
        s = act(s, K.CHECK)  # flop not dealt yet: still not terminal
    with pytest.raises(ValueError):
        settle(s, (h("AsKd"), h("KhQh")))
