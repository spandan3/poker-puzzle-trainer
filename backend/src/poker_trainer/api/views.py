"""Pure functions turning a frozen ``Puzzle`` / stored grade into JSON-safe dicts.

No database and no web framework. ``puzzle_view`` shows only what Hero sees at the table;
``attempt_result`` is the full reveal, built from the stored attempt plus the decoded puzzle.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

import numpy as np

from poker_trainer.api.text import (
    CATEGORY_NAMES,
    HAND_CLASS_NAMES,
    JUDGED_ON_RANGE,
    simplification_text,
)
from poker_trainer.engine.cards import card_str
from poker_trainer.engine.combos import COMBOS, HAND_CLASSES, combos_of_class, grid_position
from poker_trainer.engine.evaluator import evaluate, hand_class
from poker_trainer.engine.ranges import Range
from poker_trainer.game.state import (
    ActionKind,
    HandState,
    Street,
    amount_to_call,
    apply,
    deal,
    legal_actions,
    needs_board,
    new_hand,
    position_name,
    total_pot,
)
from poker_trainer.puzzle.model import (
    OptionEV,
    Puzzle,
    RangeView,
    Spot,
    option_ev_from_dict,
    option_ev_to_dict,
)
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.narrowing import describe
from poker_trainer.villain.profiles import load_profile

__all__ = [
    "action_log",
    "attempt_result",
    "custom_allowed",
    "custom_bounds",
    "option_ev_from_dict",
    "option_ev_to_dict",
    "option_view",
    "puzzle_view",
    "range_combos",
    "range_grid",
    "showdown",
    "villain_model_current",
]


def _street_name(street: Street) -> str:
    return street.name.lower()


def _cards(cards: Sequence[int]) -> list[str]:
    return [card_str(int(c)) for c in cards]


def _opt_float(x: float | None) -> float | None:
    return None if x is None else float(x)


def _opt_bb(x: float | None) -> float | None:
    return None if x is None else float(x) / 2


# ---------------------------------------------------------------------------
# Action log
# ---------------------------------------------------------------------------


def _replay(spot: Spot) -> tuple[list[dict[str, Any]], HandState]:
    """Rebuild the hand from ``spot.state.history``, dealing board cards from ``spot.runout``."""
    target = len(spot.state.board)
    s = new_hand(spot.state.button)

    def deal_pending(st: HandState) -> HandState:
        while needs_board(st) and len(st.board) < target:
            n = 3 if st.street == Street.PREFLOP else 1
            k = len(st.board)
            st = deal(st, tuple(spot.runout[k : k + n]))
        return st

    log: list[dict[str, Any]] = []
    for a in spot.state.history:
        s = deal_pending(s)
        log.append(
            {
                "street": _street_name(a.street),
                "actor": "hero" if a.seat == spot.hero_seat else "villain",
                "kind": a.kind.value,
                "to": int(a.to),
                "text": describe(a, s),
            }
        )
        s = apply(s, a)
    return log, deal_pending(s)


def action_log(spot: Spot) -> list[dict[str, Any]]:
    """One entry per action so far: ``street``, ``actor``, ``kind``, ``to``, ``text``."""
    return _replay(spot)[0]


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------


def range_grid(r: Range, dead: Collection[int]) -> list[list[float | None]]:
    """13x13 grid of the mean weight over each class's *unblocked* combos.

    A combo is blocked when it holds a card in ``dead``; a cell with no unblocked combo is None.
    """
    dead_set = {int(c) for c in dead}
    grid: list[list[float | None]] = [[None] * 13 for _ in range(13)]
    for label in HAND_CLASSES:
        live = [i for i in combos_of_class(label) if not (set(COMBOS[i]) & dead_set)]
        row, col = grid_position(label)
        grid[row][col] = float(np.mean(r[live])) if live else None
    return grid


def range_combos(r: Range) -> list[list[Any]]:
    """``[[combo_str, weight], ...]`` for every combo with weight > 0 (e.g. ``["AsKd", 1.0]``)."""
    return [
        [card_str(COMBOS[i][0]) + card_str(COMBOS[i][1]), float(r[i])]
        for i in np.flatnonzero(r > 0)
    ]


def _dead(p: Puzzle) -> tuple[int, ...]:
    return (*p.spot.hero, *p.spot.state.board)


# ---------------------------------------------------------------------------
# Showdown
# ---------------------------------------------------------------------------


def showdown(spot: Spot) -> dict[str, str]:
    """Hand classes and winner from the frozen hole cards and the full 5-card run-out."""
    if len(spot.runout) != 5:
        raise ValueError("showdown needs the full 5-card run-out")
    hero = evaluate((*spot.hero, *spot.runout))
    villain = evaluate((*spot.villain_hole, *spot.runout))
    winner = "hero" if hero < villain else "villain" if villain < hero else "split"
    return {
        "hero_hand": HAND_CLASS_NAMES[hand_class(hero)],
        "villain_hand": HAND_CLASS_NAMES[hand_class(villain)],
        "winner": winner,
    }


# ---------------------------------------------------------------------------
# Custom sizes
# ---------------------------------------------------------------------------


def custom_bounds(p: Puzzle) -> tuple[int | None, int | None]:
    """``(min_to, max_to)`` of a legal post-flop bet or raise, else ``(None, None)``."""
    s = p.spot.state
    if s.street == Street.PREFLOP or s.to_act is None:
        return None, None
    lg = legal_actions(s)
    if lg.aggressive is None or lg.min_to is None or lg.max_to is None:
        return None, None
    return int(lg.min_to), int(lg.max_to)


def villain_model_current(p: Puzzle) -> bool:
    """True when the live profile and category thresholds match the puzzle's versions.

    The single source of this check: ``custom_allowed`` (the view) and the service's 409 on a
    custom size both use it, so they can't drift apart.
    """
    return (
        load_profile(p.spot.profile).version == p.spot.profile_version
        and load_thresholds().version == p.spot.categories_version
    )


def custom_allowed(p: Puzzle) -> bool:
    """Custom sizes need a post-flop legal bet/raise and current Villain model versions."""
    lo, hi = custom_bounds(p)
    if lo is None or hi is None:
        return False
    return villain_model_current(p)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _has_call(p: Puzzle) -> bool:
    return any(o.option.action.kind == ActionKind.CALL for o in p.solution.options)


def _pot_odds(p: Puzzle) -> float | None:
    return float(p.solution.pot_odds) if _has_call(p) else None


def puzzle_view(
    puzzle_id: int, p: Puzzle, *, custom_sizes_allowed: bool, attempts_so_far: int
) -> dict[str, Any]:
    """What Hero sees before answering. Nothing Villain-side or undealt appears here."""
    sp = p.spot
    s = sp.state
    villain_seat = 1 - sp.hero_seat
    prof = load_profile(sp.profile)
    lo, hi = custom_bounds(p)
    allowed = bool(custom_sizes_allowed) and lo is not None
    return {
        "id": int(puzzle_id),
        "street": _street_name(s.street),
        "hero_seat": int(sp.hero_seat),
        "hero_position": position_name(s, sp.hero_seat),
        "villain_position": position_name(s, villain_seat),
        "hero_cards": _cards(sp.hero),
        "board": _cards(s.board),
        "stacks": [int(x) for x in s.stacks],
        "street_bets": [int(x) for x in s.street_bets],
        "pot": int(total_pot(s)),
        "to_call": int(amount_to_call(s)),
        "pot_odds": _pot_odds(p),
        "history": action_log(sp),
        "villain_profile": {
            "name": prof.name,
            "label": prof.label,
            "description": prof.description,
        },
        "options": [
            {
                "index": i,
                "label": o.option.label,
                "kind": o.option.action.kind.value,
                "to": int(o.option.action.to),
            }
            for i, o in enumerate(p.solution.options)
        ],
        "custom": {
            "allowed": allowed,
            "min_to": lo if allowed else None,
            "max_to": hi if allowed else None,
        },
        "range_read_asked": s.street != Street.RIVER,
        "attempts_so_far": int(attempts_so_far),
    }


def option_view(o: OptionEV, *, best: bool, chosen: bool, dead: Collection[int]) -> dict[str, Any]:
    """One option's full numbers for the results view."""
    return {
        "label": o.option.label,
        "kind": o.option.action.kind.value,
        "to": int(o.option.action.to),
        "ev_chips": float(o.ev_chips),
        "ev_bb": float(o.ev_chips) / 2,
        "fold_freq": _opt_float(o.fold_freq),
        "equity_vs_continue": _opt_float(o.equity_vs_continue),
        "equity_vs_continue_se": _opt_float(o.equity_vs_continue_se),
        "ahead_vs_continue": _opt_float(o.ahead_vs_continue),
        "required_fold_equity": _opt_float(o.required_fold_equity),
        "put": int(o.put),
        "branches": [
            {
                "label": b.label,
                "share": float(b.share),
                "equity": _opt_float(b.equity),
                "value_chips": float(b.value_chips),
                "value_bb": float(b.value_chips) / 2,
            }
            for b in o.branches
        ],
        "simplifications": list(o.simplifications),
        "continue_grid": None if o.continue_range is None else range_grid(o.continue_range, dead),
        "is_best": bool(best),
        "is_chosen": bool(chosen),
    }


def _range_step(v: RangeView, dead: Collection[int]) -> dict[str, Any]:
    return {
        "label": v.label,
        "street": _street_name(v.street),
        "grid": range_grid(v.range, dead),
        "combos": range_combos(v.range),
    }


def attempt_result(*, attempt: dict[str, Any], puzzle: Puzzle, chosen: OptionEV) -> dict[str, Any]:
    """Full result of a stored attempt.

    ``attempt`` is the stored row as a plain dict with keys: ``id``, ``puzzle_id``,
    ``attempt_no``, ``is_first``, ``created_at`` (ISO string), ``option_index``, ``custom_to``,
    ``action``, ``equity_guess``, ``range_read_guess``, ``intent``, ``verdict``,
    ``ev_loss_chips``, ``equity_error``, ``equity_score``, ``range_read_error``,
    ``range_read_score``, ``intent_truth``, ``intent_flag``, ``bluff_required``,
    ``bluff_actual`` and ``best_label``. Nothing is regraded here.
    """
    a = attempt
    sp, sol = puzzle.spot, puzzle.solution
    dead = _dead(puzzle)

    stored = list(sol.options)
    chosen_action = chosen.option.action
    chosen_idx = next((i for i, o in enumerate(stored) if o.option.action == chosen_action), None)
    options = [
        option_view(o, best=i == sol.best, chosen=i == chosen_idx, dead=dead)
        for i, o in enumerate(stored)
    ]
    if chosen_idx is None:
        options.append(option_view(chosen, best=False, chosen=True, dead=dead))

    codes = list(dict.fromkeys([*sol.simplifications, *chosen.simplifications]))
    rows = sol.category_breakdown
    bluff = (
        None
        if a["bluff_required"] is None or a["bluff_actual"] is None
        else {"required": float(a["bluff_required"]), "actual": float(a["bluff_actual"])}
    )
    prof = load_profile(sp.profile)
    ev_loss = float(a["ev_loss_chips"])
    return {
        "attempt": {
            "id": a["id"],
            "puzzle_id": a["puzzle_id"],
            "attempt_no": a["attempt_no"],
            "is_first": bool(a["is_first"]),
            "created_at": a["created_at"],
        },
        "answer": {
            "option_index": a["option_index"],
            "custom_to": a["custom_to"],
            "action": dict(a["action"]),
            "equity_guess": float(a["equity_guess"]),
            "range_read_guess": _opt_float(a["range_read_guess"]),
            "intent": a["intent"],
            "chosen_label": chosen.option.label,
        },
        "grade": {
            "verdict": a["verdict"],
            "ev_loss_chips": ev_loss,
            "ev_loss_bb": ev_loss / 2,
            "chosen_label": chosen.option.label,
            "best_label": a["best_label"],
            "equity": float(sol.equity),
            "equity_std_error": float(sol.equity_std_error),
            "equity_exact": bool(sol.equity_exact),
            "equity_guess": float(a["equity_guess"]),
            "equity_error": float(a["equity_error"]),
            "equity_score": a["equity_score"],
            "ahead_now": _opt_float(sol.ahead_now),
            "range_read_guess": _opt_float(a["range_read_guess"]),
            "range_read_error": _opt_float(a["range_read_error"]),
            "range_read_score": a["range_read_score"],
            "intent": a["intent"],
            "intent_truth": a["intent_truth"],
            "intent_flag": a["intent_flag"],
            "bluff_check": bluff,
            "pot_odds": _pot_odds(puzzle),
        },
        "options": options,
        "simplifications": [{"code": c, "text": simplification_text(c)} for c in codes],
        "categories": None
        if rows is None
        else [
            {
                "category": r.category,
                "name": CATEGORY_NAMES[r.category],
                "share": float(r.share),
                "ahead": float(r.ahead),
                "equity": float(r.equity),
                "win": float(r.win),
                "tie": float(r.tie),
                "lose": float(r.lose),
            }
            for r in rows
        ],
        "range_steps": [_range_step(v, dead) for v in sp.steps],
        "reveal": {
            "villain_cards": _cards(sp.villain_hole),
            "runout": _cards(sp.runout),
            "profile": {
                "name": prof.name,
                "label": prof.label,
                "description": prof.description,
                "version": int(sp.profile_version),
            },
            "showdown": showdown(sp),
        },
        "judged_on_range_note": JUDGED_ON_RANGE,
    }
