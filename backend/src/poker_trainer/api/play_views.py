"""Pure functions turning a played hand's record into the JSON the table shows.

No database and no web framework, like ``api/views.py``. A hand is rebuilt by replaying its
``HandRecord``. The views show only what Hero may see: the bot's hole cards appear in a
``PlayOutcome`` only when the hand ended in a showdown, and the deck, the bot's seed and the
undealt board never appear at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from poker_trainer.api import views
from poker_trainer.api.text import JUDGED_ON_RANGE
from poker_trainer.db.blob import decode_puzzle
from poker_trainer.db.models import PlayDecisionRow
from poker_trainer.explain.template import explain
from poker_trainer.game.state import (
    HandState,
    Street,
    amount_to_call,
    legal_actions,
    position_name,
    pot_odds,
    total_pot,
)
from poker_trainer.play.analyse import hero_decisions
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandOutcome,
    HandRecord,
    bot_cards,
    hero_cards,
    outcome,
    replay,
)
from poker_trainer.play.session import START, must_rebuy
from poker_trainer.puzzle.model import Puzzle
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import Profile

__all__ = [
    "decision_review",
    "decision_table",
    "explanation_result",
    "frames",
    "hand_analysis",
    "hand_view",
    "session_view",
    "table_view",
]

_NO_CUSTOM = {"allowed": False, "min_to": None, "max_to": None}


def _hero_to_act(s: HandState, out: HandOutcome | None) -> bool:
    return out is None and s.to_act == HERO_SEAT


def table_view(record: HandRecord, profile: Profile) -> dict[str, Any]:
    """The table as ``PuzzleView`` shows it, without the answer-form fields.

    A finished hand shows the settled stacks, zero bets in front and the awarded pot. The
    profile's label and description come from ``profile`` (the session's snapshot), never
    from the live profile file.
    """
    s = replay(record)
    out = outcome(record)
    log, _ = views.replay_log(
        record.button,
        record.start_stacks,
        record.actions,
        record.deck[4:9],
        HERO_SEAT,
        len(s.board),
    )
    to_call = amount_to_call(s) if _hero_to_act(s, out) else 0
    return {
        "street": views._street_name(s.street),
        "hero_seat": HERO_SEAT,
        "hero_position": position_name(s, HERO_SEAT),
        "villain_position": position_name(s, 1 - HERO_SEAT),
        "hero_cards": views._cards(hero_cards(record)),
        "board": views._cards(s.board),
        "stacks": [int(x) for x in (out.stacks if out else s.stacks)],
        "street_bets": [0, 0] if out else [int(x) for x in s.street_bets],
        "pot": int(total_pot(s)),
        "to_call": int(to_call),
        "pot_odds": float(pot_odds(s)) if to_call > 0 else None,
        "history": log,
        "villain_profile": {
            "name": profile.name,
            "label": profile.label,
            "description": profile.description,
        },
    }


def frames(record: HandRecord) -> list[dict[str, Any]]:
    """The table after the first ``k`` actions, for ``k`` from 0 to ``len(record.actions)``.

    These describe the table during play, before any pot award: after a showdown the last frame
    still shows the bets and the full board. ``to_act`` is null when nobody is to act (the hand
    is over, or all-in and running out).
    """
    result: list[dict[str, Any]] = []
    n = len(record.actions)
    for k in range(n + 1):
        s = replay(replace(record, actions=record.actions[:k]))
        to_act = None if s.to_act is None else "hero" if s.to_act == HERO_SEAT else "villain"
        if record.abandoned and k == n:
            to_act = None
        result.append(
            {
                "stacks": [int(x) for x in s.stacks],
                "street_bets": [int(x) for x in s.street_bets],
                "pot": int(total_pot(s)),
                "board_len": len(s.board),
                "to_act": to_act,
            }
        )
    return result


def _outcome_view(record: HandRecord, out: HandOutcome) -> dict[str, Any]:
    shown = out.ended_by == "showdown"
    return {
        "ended_by": out.ended_by,
        "winner": out.winner,
        "hero_delta_chips": int(out.hero_delta),
        "hero_delta_bb": float(out.hero_delta) / 2,
        "villain_cards": views._cards(bot_cards(record)) if shown else None,
        "showdown": (
            views.showdown_of(hero_cards(record), bot_cards(record), replay(record).board)
            if shown
            else None
        ),
    }


def hand_view(
    hand_id: int,
    hand_no: int,
    session_id: int,
    record: HandRecord,
    profile: Profile,
    *,
    decision_count: int,
) -> dict[str, Any]:
    """One hand as it stands: the table, its frames, Hero's menu and (once over) the outcome."""
    s = replay(record)
    out = outcome(record)
    options: list[dict[str, Any]] = []
    custom = dict(_NO_CUSTOM)
    if _hero_to_act(s, out):
        options = [
            {
                "index": i,
                "label": o.label,
                "kind": o.action.kind.value,
                "to": int(o.action.to),
            }
            for i, o in enumerate(hero_options(s))
        ]
        lg = legal_actions(s)
        if s.street != Street.PREFLOP and lg.min_to is not None and lg.max_to is not None:
            custom = {"allowed": True, "min_to": int(lg.min_to), "max_to": int(lg.max_to)}
    return {
        "id": int(hand_id),
        "hand_no": int(hand_no),
        "session_id": int(session_id),
        "status": "in_progress" if out is None else "complete",
        "action_count": len(record.actions),
        "decision_count": int(decision_count),
        "table": table_view(record, profile),
        "frames": frames(record),
        "options": options,
        "custom": custom,
        "outcome": None if out is None else _outcome_view(record, out),
    }


def session_view(session: dict[str, Any], hand: dict[str, Any] | None) -> dict[str, Any]:
    """A session with its latest hand.

    ``session`` holds ``id``, ``open``, ``profile`` (name, label, description), ``hero_stack``,
    ``bot_stack``, ``hero_bought_chips`` and ``hands_played``. The stacks are those after the
    last finished hand, so the tally counts finished hands only. The next-hand choices are
    offered only to an open session whose latest hand is over.
    """
    hero = int(session["hero_stack"])
    net = hero - int(session["hero_bought_chips"])
    between_hands = bool(session["open"]) and (hand is None or hand["status"] == "complete")
    rebuy = between_hands and must_rebuy(hero)
    return {
        "id": int(session["id"]),
        "open": bool(session["open"]),
        "profile": dict(session["profile"]),
        "hero_stack": hero,
        "bot_stack": int(session["bot_stack"]),
        "hero_bought_chips": int(session["hero_bought_chips"]),
        "net_chips": net,
        "net_bb": net / 2,
        "hands_played": int(session["hands_played"]),
        "must_rebuy": rebuy,
        "can_top_up": between_hands and not rebuy and hero < START,
        "hand": hand,
    }


# ---------------------------------------------------------------------------
# Hand analysis
# ---------------------------------------------------------------------------

GRADED = "graded"
NOT_GRADED = "not_graded"
# in play Hero states no intent, so the grade has none and no flag about one
_NO_GUESS = ("intent", "intent_flag")


def decision_table(record: HandRecord, profile: Profile, n: int) -> dict[str, Any]:
    """The table as it stood when Hero made decision ``n`` (0-based)."""
    i = hero_decisions(record)[n]
    return table_view(replace(record, actions=record.actions[:i], abandoned=False), profile)


def _graded(
    row: PlayDecisionRow, record: HandRecord, profile: Profile
) -> tuple[Puzzle, dict[str, Any], dict[str, Any]]:
    """``(puzzle, core, result)`` of a graded decision: ``views.decision_core`` from the stored
    row, and the result dict ``explain`` and ``build_facts`` read."""
    assert row.puzzle is not None and row.chosen is not None
    puzzle = decode_puzzle(row.puzzle)
    chosen = views.option_ev_from_dict(row.chosen)
    bluff = (
        None
        if row.bluff_required is None or row.bluff_actual is None
        else (float(row.bluff_required), float(row.bluff_actual))
    )
    assert row.verdict is not None and row.ev_loss_chips is not None
    assert row.best_label is not None and row.best_ev_chips is not None
    core = views.decision_core(
        puzzle,
        chosen,
        verdict=row.verdict,
        ev_loss_chips=row.ev_loss_chips,
        best_label=row.best_label,
        best_ev_chips=row.best_ev_chips,
        intent=None,
        intent_truth=row.intent_truth,
        intent_flag=None,
        bluff=bluff,
    )
    core["grade"] = {k: v for k, v in core["grade"].items() if k not in _NO_GUESS}
    action = record.actions[hero_decisions(record)[row.n]]
    result = {
        "grade": core["grade"],
        "options": core["options"],
        "categories": core["categories"],
        "range_steps": core["range_steps"],
        "answer": {
            "custom_to": row.custom_to,
            "action": {"kind": action.kind.value, "to": int(action.to)},
            "chosen_label": chosen.option.label,
        },
        "reveal": {"profile": {"label": profile.label, "description": profile.description}},
    }
    return puzzle, core, result


def explanation_result(
    row: PlayDecisionRow, record: HandRecord, profile: Profile
) -> tuple[dict[str, Any], Puzzle]:
    """The result dict of a graded decision with exactly the keys ``explain`` and
    ``build_facts`` read, and its puzzle. The profile's label and description are the session's
    snapshot."""
    puzzle, _, result = _graded(row, record, profile)
    return result, puzzle


def decision_review(row: PlayDecisionRow, record: HandRecord, profile: Profile) -> dict[str, Any]:
    """A stored decision as the results view shows it. Nothing is regraded."""
    base = {
        "index": int(row.n),
        "status": row.status,
        "reason": row.reason,
        "view": decision_table(record, profile, row.n),
    }
    if row.status != GRADED:
        return {
            **base,
            "grade": None,
            "options": [],
            "simplifications": [],
            "categories": None,
            "range_steps": [],
            "chosen_label": None,
            "explanation": None,
        }
    puzzle, core, result = _graded(row, record, profile)
    return {
        **base,
        "grade": core["grade"],
        "options": core["options"],
        "simplifications": core["simplifications"],
        "categories": core["categories"],
        "range_steps": core["range_steps"],
        "chosen_label": core["grade"]["chosen_label"],
        "explanation": explain(result, puzzle, views.action_log(puzzle.spot)),
    }


def _summary(rows: Sequence[PlayDecisionRow]) -> dict[str, Any]:
    graded = [(r.n, float(r.ev_loss_chips or 0.0)) for r in rows if r.status == GRADED]
    worst = max(graded, key=lambda g: (g[1], -g[0]), default=None)
    return {
        "ev_loss_bb": sum(loss for _, loss in graded) / 2,
        "worst_index": None if worst is None or worst[1] <= 0 else int(worst[0]),
    }


def _reveal(record: HandRecord, profile: Profile) -> dict[str, Any]:
    out = outcome(record)
    board = replay(record).board
    shown = out is not None and out.ended_by == "showdown"
    return {
        "villain_cards": views._cards(bot_cards(record)),
        "board": views._cards(board),
        "profile": {
            "name": profile.name,
            "label": profile.label,
            "description": profile.description,
            "version": int(profile.version),
        },
        "showdown": views.showdown_of(hero_cards(record), bot_cards(record), board)
        if shown
        else None,
    }


def hand_analysis(
    hand_id: int,
    record: HandRecord,
    profile: Profile,
    rows: Sequence[PlayDecisionRow | None],
    *,
    model_changed: bool,
) -> dict[str, Any]:
    """A finished hand's analysis so far: ``rows[n]`` is decision ``n``'s stored row or None.
    The summary appears once every decision is stored."""
    done = [r for r in rows if r is not None]
    return {
        "hand_id": int(hand_id),
        "decisions": [None if r is None else decision_review(r, record, profile) for r in rows],
        "summary": _summary(done) if rows and len(done) == len(rows) else None,
        "reveal": _reveal(record, profile),
        "model_changed": bool(model_changed),
        "judged_on_range_note": JUDGED_ON_RANGE,
    }
