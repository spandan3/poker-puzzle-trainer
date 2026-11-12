"""Results built the way the API builds them: ``service`` grades and stores the fields,
``views.attempt_result`` turns them into the result dict."""

from __future__ import annotations

from functools import cache
from typing import Any

from poker_trainer.api import service, views
from poker_trainer.api.schemas import AttemptIn
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.puzzle.grade import Answer, grade
from poker_trainer.puzzle.model import Puzzle

# The attempt fixtures' puzzles (``dev_fixtures.search()``'s seeds) and their answers.
FIXTURE_SEEDS = {
    "flop_unopened": (3, "flop"),  # attempt_bet
    "facing_postflop_raise": (17, "flop"),  # attempt_fold, attempt_call
    "preflop_bb_facing_open": (3, "preflop"),  # attempt_raise_preflop
    "preflop_btn_first_in": (1, "preflop"),  # attempt_fold_preflop
    "river": (1, "river"),  # attempt_check_river
    "custom_allowed": (1, "flop"),  # attempt_custom
}


@cache
def puzzle(seed: int, street: str) -> Puzzle:
    return generate_puzzle(seed, street=street)


def result(
    p: Puzzle,
    *,
    option: int | None = None,
    custom_to: int | None = None,
    equity_guess: float = 0.45,
    range_read_guess: float | None = 0.5,
    intent: str | None = None,
) -> dict[str, Any]:
    """The result dict of an answer, as ``POST /api/puzzles/{id}/attempts`` returns it."""
    inp = AttemptIn(
        option=option,
        custom_to=custom_to,
        equity_guess=equity_guess,
        range_read_guess=range_read_guess,
        intent=intent,
    )
    action = service._resolve_action(p, inp)
    g = grade(p, Answer(action, inp.equity_guess, inp.range_read_guess, inp.intent))
    fields = service._grade_fields(p, inp, action, g)
    attempt = {
        "id": 1,
        "puzzle_id": 1,
        "attempt_no": 1,
        "is_first": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        **{k: fields[k] for k in _STORED},
    }
    return views.attempt_result(attempt=attempt, puzzle=p, chosen=g.chosen)


_STORED = (
    "option_index",
    "custom_to",
    "action",
    "equity_guess",
    "range_read_guess",
    "intent",
    "verdict",
    "ev_loss_chips",
    "equity_error",
    "equity_score",
    "range_read_error",
    "range_read_score",
    "intent_truth",
    "intent_flag",
    "bluff_required",
    "bluff_actual",
    "best_label",
)
