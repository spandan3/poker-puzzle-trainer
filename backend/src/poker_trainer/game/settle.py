"""Pot settlement: the final stacks of a finished hand, with side pots.

``settle`` keeps the heads-up interface and results. ``settle_pots`` builds the pots in layers
from each seat's total contribution:

- a layer's chips come from every seat that paid into it, folded seats included, and it is
  contested by the live seats that paid into it in full;
- a layer only one seat paid into is an uncalled bet: it goes back to that seat and is not
  listed;
- adjacent layers contested by the same seats form one pot;
- each pot goes to the best hand among its seats; a tie splits it evenly, and odd chips go one
  at a time to the winners in clockwise order from ``button+1``;
- if only one live seat is left, it takes everything as one pot.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from poker_trainer.engine.cards import ensure_distinct
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.game.state import (
    BB,
    SB,
    ActionKind,
    HandState,
    Street,
    is_terminal,
    live_seats,
    total_pot,
)


@dataclass(frozen=True)
class PotAward:
    amount: int
    eligible: tuple[int, ...]  # the seats contesting this pot, in seat order
    winners: tuple[int, ...]  # in seat order


@dataclass(frozen=True)
class Settlement:
    stacks: tuple[int, ...]
    pots: tuple[PotAward, ...]  # the main pot first, then the side pots


def settle(s: HandState, holes: Sequence[tuple[int, int] | None]) -> tuple[int, ...]:
    """Final stacks of the terminal state ``s``; ``holes[seat]`` is that seat's hole cards.

    Heads-up: a fold gives the whole pot to the other seat. At showdown the stronger hand takes
    the pot and a tie splits it evenly. With three or more seats this is ``settle_pots`` with
    the contributions read from the history. Raises ``ValueError`` when the hand is not over.
    """
    if len(s.stacks) > 2:
        return settle_pots(s, holes, _start_stacks(s)).stacks
    if not is_terminal(s):
        raise ValueError("cannot settle a hand that is not over")
    pot = total_pot(s)
    if s.folded is not None:
        winner = 1 - s.folded
        return _award(s.stacks, winner, pot)
    if len(s.board) != 5:
        raise ValueError(f"showdown needs a 5-card board, got {len(s.board)}")
    h0, h1 = holes
    assert h0 is not None and h1 is not None
    ensure_distinct(s.board, h0, h1)
    ranks = [evaluate((*h, *s.board)) for h in (h0, h1)]
    if ranks[0] == ranks[1]:
        # Bets are capped at the effective stack, so both seats put in the same chips.
        assert pot % 2 == 0, f"odd pot at showdown: {pot}"
        return s.stacks[0] + pot // 2, s.stacks[1] + pot // 2
    return _award(s.stacks, 0 if ranks[0] < ranks[1] else 1, pot)  # lower rank is stronger


def _award(stacks: tuple[int, ...], seat: int, pot: int) -> tuple[int, ...]:
    return (stacks[0] + pot, stacks[1]) if seat == 0 else (stacks[0], stacks[1] + pot)


def _start_stacks(s: HandState) -> tuple[int, ...]:
    """Each seat's stack before the blinds, rebuilt from the history (three or more seats).

    A seat's street bet at the end of a street is its last ``to`` there (or its blind); with
    three or more seats the blinds are always posted in full.
    """
    n = len(s.stacks)
    paid = [0] * n
    for street in Street:
        bets = [0] * n
        if street == Street.PREFLOP:
            bets[(s.button + 1) % n] = SB
            bets[(s.button + 2) % n] = BB
        for a in s.history:
            if a.street == street and a.kind not in (ActionKind.FOLD, ActionKind.CHECK):
                bets[a.seat] = a.to
        paid = [p + b for p, b in zip(paid, bets, strict=True)]
    if sum(paid) != total_pot(s):
        raise ValueError("history does not account for the pot")
    return tuple(x + p for x, p in zip(s.stacks, paid, strict=True))


def settle_pots(
    s: HandState,
    holes: Sequence[tuple[int, int] | None],
    start_stacks: Sequence[int],
) -> Settlement:
    """Settle the terminal state ``s`` by side-pot layers.

    ``start_stacks`` are the seats' stacks before the blinds (``new_hand``'s input); each seat's
    contribution is ``start_stacks[i] - s.stacks[i]``. ``holes[seat]`` is needed only for seats
    still live at a showdown; others may be None.
    """
    if not is_terminal(s):
        raise ValueError("cannot settle a hand that is not over")
    n = len(s.stacks)
    if len(start_stacks) != n or len(holes) != n:
        raise ValueError("start_stacks and holes need one entry per seat")
    paid = [int(start_stacks[i]) - s.stacks[i] for i in range(n)]
    if min(paid) < 0 or sum(paid) != total_pot(s):
        raise ValueError(f"start stacks {tuple(start_stacks)} don't match the state")
    stacks = list(s.stacks)
    live = live_seats(s)

    if len(live) == 1:
        (seat,) = live
        stacks[seat] += total_pot(s)
        return Settlement(tuple(stacks), (PotAward(total_pot(s), live, live),))

    if len(s.board) != 5:
        raise ValueError(f"showdown needs a 5-card board, got {len(s.board)}")
    shown = []
    for seat in live:
        h = holes[seat]
        if h is None:
            raise ValueError(f"seat {seat} is at showdown without hole cards")
        shown.append(h)
    ensure_distinct(s.board, *shown)
    rank = {seat: evaluate((*h, *s.board)) for seat, h in zip(live, shown, strict=True)}

    # Layers between consecutive contribution levels; same-seat layers merge into one pot.
    layers: list[tuple[int, tuple[int, ...]]] = []
    prev = 0
    for level in sorted({c for c in paid if c > 0}):
        amount = sum(min(c, level) - min(c, prev) for c in paid)
        payers = [i for i in range(n) if paid[i] >= level]
        eligible = tuple(i for i in live if paid[i] >= level)
        prev = level
        if len(payers) == 1:  # only the top layer can have a single payer
            stacks[payers[0]] += amount  # uncalled: returned, not a pot
            continue
        assert eligible, "a contested layer must have a live seat"
        if layers and layers[-1][1] == eligible:
            layers[-1] = (layers[-1][0] + amount, eligible)
        else:
            layers.append((amount, eligible))

    pots = []
    for amount, eligible in layers:
        best = min(rank[i] for i in eligible)  # lower rank is stronger
        winners = tuple(i for i in eligible if rank[i] == best)
        share, odd = divmod(amount, len(winners))
        for i in winners:
            stacks[i] += share
        for i in sorted(winners, key=lambda i: (i - s.button - 1) % n)[:odd]:
            stacks[i] += 1
        pots.append(PotAward(amount, eligible, winners))
    assert sum(stacks) == s.total_chips
    return Settlement(tuple(stacks), tuple(pots))
