"""Pot settlement: the final stacks of a finished heads-up hand."""

from __future__ import annotations

from poker_trainer.engine.cards import ensure_distinct
from poker_trainer.engine.evaluator import evaluate
from poker_trainer.game.state import HandState, is_terminal, total_pot


def settle(s: HandState, holes: tuple[tuple[int, int], tuple[int, int]]) -> tuple[int, int]:
    """Final stacks of the terminal state ``s``; ``holes[seat]`` is that seat's hole cards.

    A fold gives the whole pot to the other seat. At showdown the stronger hand takes the pot
    and a tie splits it evenly. Raises ``ValueError`` when the hand is not over.
    """
    if not is_terminal(s):
        raise ValueError("cannot settle a hand that is not over")
    pot = total_pot(s)
    if s.folded is not None:
        winner = 1 - s.folded
        return _award(s.stacks, winner, pot)
    if len(s.board) != 5:
        raise ValueError(f"showdown needs a 5-card board, got {len(s.board)}")
    ensure_distinct(s.board, *holes)
    ranks = [evaluate((*holes[seat], *s.board)) for seat in (0, 1)]
    if ranks[0] == ranks[1]:
        # Bets are capped at the effective stack, so both seats put in the same chips.
        assert pot % 2 == 0, f"odd pot at showdown: {pot}"
        return s.stacks[0] + pot // 2, s.stacks[1] + pot // 2
    return _award(s.stacks, 0 if ranks[0] < ranks[1] else 1, pot)  # lower rank is stronger


def _award(stacks: tuple[int, int], seat: int, pot: int) -> tuple[int, int]:
    return (stacks[0] + pot, stacks[1]) if seat == 0 else (stacks[0], stacks[1] + pot)
