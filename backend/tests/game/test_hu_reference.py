"""Heads-up is identical to the frozen pre-M12 engine (``tests/reference/hu_engine.py``).

Seeded random heads-up hands (stacks 2 to 600 chips) are driven through both engines with the
same legal choices: folds, checks, calls, and bets/raises at the minimum, the maximum (all-in),
pot-sized and random sizes. Every step compares the legal actions, the seat to act, stacks,
street bets, pot, history, ``folded`` and ``is_terminal``; every finished hand compares the
settled stacks (and ``settle_pots`` agrees with ``settle``).
"""

from __future__ import annotations

import random

import reference.hu_engine as ref

from poker_trainer.game import settle as new_settle
from poker_trainer.game import state as new

HANDS = 3000


def _legal_key(lg) -> tuple:
    kind = None if lg.aggressive is None else lg.aggressive.value
    return (lg.fold, lg.check, lg.call, kind, lg.min_to, lg.max_to)


def _hist(history) -> tuple:
    return tuple((a.seat, a.kind.value, int(a.street), a.to) for a in history)


def _same(n: new.HandState, r: ref.HandState) -> None:
    assert n.button == r.button
    assert n.to_act == r.to_act
    assert n.stacks == r.stacks
    assert n.street_bets == r.street_bets
    assert n.pot == r.pot
    assert int(n.street) == int(r.street)
    assert n.board == r.board
    assert _hist(n.history) == _hist(r.history)
    assert n.last_raise == r.last_raise
    assert n.folded == r.folded
    assert n.total_chips == r.total_chips
    assert new.is_terminal(n) == ref.is_terminal(r)
    assert new.needs_board(n) == ref.needs_board(r)
    if n.to_act is not None:
        assert _legal_key(new.legal_actions(n)) == _legal_key(ref.legal_actions(r))
        assert new.amount_to_call(n) == ref.amount_to_call(r)


def _choose(rng: random.Random, s: new.HandState) -> tuple[str, int]:
    lg = new.legal_actions(s)
    me = s.to_act
    assert me is not None
    options: list[tuple[str, int]] = []
    if lg.fold:
        options.append(("fold", 0))
    if lg.check:
        options += [("check", 0)] * 3
    if lg.call:
        options += [("call", s.street_bets[me] + lg.call)] * 3
    if lg.aggressive is not None:
        assert lg.min_to is not None and lg.max_to is not None
        kind = lg.aggressive.value
        pot_to = max(s.street_bets) + new.total_pot(s) + lg.call
        sizes = {
            lg.min_to,
            lg.max_to,
            rng.randint(lg.min_to, lg.max_to),
            min(max(pot_to, lg.min_to), lg.max_to),
        }
        options += [(kind, to) for to in sorted(sizes)]
    return rng.choice(options)


def _play_one(seed: int) -> None:
    rng = random.Random(f"hu-reference:{seed}")
    stacks = (rng.randint(2, 600), rng.randint(2, 600))
    button = rng.randrange(2)
    deck = list(range(52))
    rng.shuffle(deck)
    holes = ((deck[0], deck[1]), (deck[2], deck[3]))
    board = tuple(deck[4:9])

    n, r = new.new_hand(button, stacks), ref.new_hand(button, stacks)
    _same(n, r)
    while not new.is_terminal(n):
        if new.needs_board(n):
            k = len(n.board)
            cards = board[k : k + (3 if k == 0 else 1)]
            n, r = new.deal(n, cards), ref.deal(r, cards)
        else:
            kind, to = _choose(rng, n)
            seat, street = n.to_act, n.street
            n = new.apply(n, new.Action(seat, new.ActionKind(kind), street, to))
            r = ref.apply(r, ref.Action(seat, ref.ActionKind(kind), ref.Street(int(street)), to))
        _same(n, r)

    out = new_settle.settle(n, holes)
    assert out == ref.settle(r, holes)
    assert sum(out) == n.total_chips
    pots = new_settle.settle_pots(n, holes, stacks)
    assert pots.stacks == out
    assert sum(p.amount for p in pots.pots) == new.total_pot(n)


def test_heads_up_matches_frozen_reference():
    for seed in range(HANDS):
        _play_one(seed)
