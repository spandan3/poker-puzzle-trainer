"""Pure functions turning a played hand's record into the JSON the table shows.

No database and no web framework, like ``api/views.py``. A hand is rebuilt by replaying its
``HandRecord``. The views show only what Hero may see: a bot's hole cards appear only for a
seat still in at a showdown (built through ``hole`` for those seats alone), and the deck, the
bots' seed and the undealt board never appear at all. Heads-up and 5-max share the views; a
5-max table names its bots "Bot 1" to "Bot 4" and has no single villain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from poker_trainer.api import views
from poker_trainer.api.text import JUDGED_ON_RANGE
from poker_trainer.db.blob import decode_puzzle
from poker_trainer.db.models import PlayDecisionRow
from poker_trainer.explain.template import explain
from poker_trainer.game.settle import PotAward, settle_pots
from poker_trainer.game.state import (
    HandState,
    Street,
    amount_to_call,
    folded_seats,
    legal_actions,
    live_seats,
    position_name,
    pot_odds,
    total_pot,
)
from poker_trainer.play.analyse import hero_decisions
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandOutcome,
    HandOutcome5,
    HandRecord,
    bot_cards,
    hero_cards,
    hole,
    holes,
    num_seats,
    outcome,
    outcome5,
    replay,
)
from poker_trainer.play.session import START, must_rebuy
from poker_trainer.puzzle.model import Puzzle
from poker_trainer.puzzle.options import hero_options
from poker_trainer.villain.profiles import Profile

__all__ = [
    "HERO_NAME",
    "HU_BOT_NAME",
    "SeatBotInfo",
    "bot_name",
    "decision_review",
    "decision_table",
    "explanation_result",
    "frames",
    "hand_analysis",
    "hand_outcome",
    "hand_view",
    "heads_up_bots",
    "pot_label",
    "profile_info",
    "session_view",
    "table_view",
]

_NO_CUSTOM = {"allowed": False, "min_to": None, "max_to": None}

HERO_NAME = "You"
HU_BOT_NAME = "Villain"


@dataclass(frozen=True)
class SeatBotInfo:
    """What the views show of one bot seat: its seat, display name and profile snapshot."""

    seat: int
    name: str
    profile: Profile


def bot_name(seat: int, table_size: int) -> str:
    """ "Villain" heads-up, "Bot 1" to "Bot 4" in 5-max."""
    return HU_BOT_NAME if table_size == 2 else f"Bot {seat}"


def heads_up_bots(profile: Profile) -> tuple[SeatBotInfo, ...]:
    return (SeatBotInfo(1, HU_BOT_NAME, profile),)


def pot_label(k: int) -> str:
    """ "main pot" for the first pot, then "side pot 1", "side pot 2", ..."""
    return "main pot" if k == 0 else f"side pot {k}"


Outcome = HandOutcome | HandOutcome5


def hand_outcome(record: HandRecord) -> Outcome | None:
    """``outcome`` heads-up, ``outcome5`` with more seats; None while the hand runs."""
    return outcome(record) if num_seats(record) == 2 else outcome5(record)


def profile_info(profile: Profile) -> dict[str, str]:
    return {"name": profile.name, "label": profile.label, "description": profile.description}


def _hero_to_act(s: HandState, out: Outcome | None) -> bool:
    return out is None and s.to_act == HERO_SEAT


def _bots(
    record: HandRecord, profile: Profile | None, bots: Sequence[SeatBotInfo] | None
) -> dict[int, SeatBotInfo]:
    if bots is None:
        if profile is None or num_seats(record) != 2:
            raise ValueError("a table with more than two seats needs its bot seats")
        bots = heads_up_bots(profile)
    by_seat = {b.seat: b for b in bots}
    if set(by_seat) != set(range(1, num_seats(record))):
        raise ValueError(f"bot seats {sorted(by_seat)} don't match the table")
    return by_seat


def _awards(record: HandRecord, out: Outcome) -> tuple[PotAward, ...]:
    """The pots of a finished hand (none when it was abandoned)."""
    if isinstance(out, HandOutcome5):
        return out.pots
    if out.ended_by == "abandoned":
        return ()
    return settle_pots(replay(record), holes(record), record.start_stacks).pots


def _shown(record: HandRecord, out: Outcome | None) -> tuple[int, ...]:
    """The bot seats whose cards are revealed: only seats still in at a showdown."""
    if out is None or out.ended_by != "showdown":
        return ()
    if isinstance(out, HandOutcome5):
        return out.shown
    return (1 - HERO_SEAT,)


def _seat_views(
    record: HandRecord, s: HandState, out: Outcome | None, bots: dict[int, SeatBotInfo]
) -> list[dict[str, Any]]:
    n = num_seats(record)
    folded = folded_seats(s)
    shown = set(_shown(record, out))
    seats = []
    for i in range(n):
        if i == HERO_SEAT:
            name, profile, cards = HERO_NAME, None, views._cards(hole(record, i))
        else:
            bot = bots[i]
            name, profile = bot.name, profile_info(bot.profile)
            # a bot's cards only through ``hole`` for a seat shown at the showdown
            cards = views._cards(hole(record, i)) if i in shown else None
        seats.append(
            {
                "seat": i,
                "name": name,
                "position": position_name(s, i),
                "stack": int(out.stacks[i] if out else s.stacks[i]),
                "street_bet": 0 if out else int(s.street_bets[i]),
                "folded": i in folded,
                "all_in": out is None and i not in folded and s.stacks[i] == 0,
                "is_hero": i == HERO_SEAT,
                "is_button": i == record.button,
                "profile": profile,
                "cards": cards,
            }
        )
    return seats


def table_view(
    record: HandRecord,
    profile: Profile | None,
    *,
    bots: Sequence[SeatBotInfo] | None = None,
) -> dict[str, Any]:
    """The table as ``PuzzleView`` shows it, without the answer-form fields.

    A finished hand shows the settled stacks, zero bets in front and the awarded pot. Heads-up
    the bot's profile is ``profile`` (the session's snapshot, never the live profile file); in
    5-max ``profile`` is None and ``bots`` gives every bot seat.
    """
    by_seat = _bots(record, profile, bots)
    n = num_seats(record)
    s = replay(record)
    out = hand_outcome(record)
    log, _ = views.replay_log(
        record.button,
        record.start_stacks,
        record.actions,
        record.deck[2 * n : 2 * n + 5],
        HERO_SEAT,
        len(s.board),
    )
    to_call = amount_to_call(s) if _hero_to_act(s, out) else 0
    pot = total_pot(s)
    if isinstance(out, HandOutcome5) and out.ended_by != "abandoned":
        pot = sum(p.amount for p in out.pots)  # an uncalled bet went back: not awarded
    heads_up = n == 2
    return {
        "street": views._street_name(s.street),
        "hero_seat": HERO_SEAT,
        "hero_position": position_name(s, HERO_SEAT),
        "villain_position": position_name(s, 1 - HERO_SEAT) if heads_up else None,
        "hero_cards": views._cards(hero_cards(record)),
        "board": views._cards(s.board),
        "stacks": [int(x) for x in (out.stacks if out else s.stacks)],
        "street_bets": [0] * n if out else [int(x) for x in s.street_bets],
        "pot": int(pot),
        "to_call": int(to_call),
        "pot_odds": float(pot_odds(s)) if to_call > 0 else None,
        "history": log,
        "villain_profile": profile_info(by_seat[1].profile) if heads_up else None,
        "table_size": n,
        "seats": _seat_views(record, s, out, by_seat),
    }


def _live_pots(s: HandState, start_stacks: Sequence[int]) -> list[int]:
    """The pots as they stand, main pot first, counting the chips in the middle only.

    Each seat's chips in the middle are what it has put in on the streets that are over (its
    contribution less its bet in front). Layers are built as ``settle_pots`` builds them: a
    layer is contested by the live seats that paid into it in full, adjacent layers with the
    same seats are one pot, and a layer only one seat paid into is an uncalled excess that
    will go back, so it is left out.
    """
    n = len(s.stacks)
    paid = [int(start_stacks[i]) - s.stacks[i] - s.street_bets[i] for i in range(n)]
    live = live_seats(s)
    pots: list[tuple[int, tuple[int, ...]]] = []
    prev = 0
    for level in sorted({c for c in paid if c > 0}):
        amount = sum(min(c, level) - min(c, prev) for c in paid)
        payers = [i for i in range(n) if paid[i] >= level]
        eligible = tuple(i for i in live if paid[i] >= level)
        prev = level
        if len(payers) == 1:
            continue
        if pots and (pots[-1][1] == eligible or not eligible):
            pots[-1] = (pots[-1][0] + amount, pots[-1][1])
        else:
            pots.append((amount, eligible))
    return [amount for amount, _ in pots]


def frames(record: HandRecord) -> list[dict[str, Any]]:
    """The table after the first ``k`` actions, for ``k`` from 0 to ``len(record.actions)``.

    These describe the table during play, before any pot award: after a showdown the last frame
    still shows the bets and the full board. ``to_act`` is null when nobody is to act (the hand
    is over, or all-in and running out); ``to_act_seat`` is the seat to act; ``folded`` flags
    each seat that has folded; ``pots`` are the pots in the middle (``_live_pots``).
    """
    result: list[dict[str, Any]] = []
    n = len(record.actions)
    seats = num_seats(record)
    for k in range(n + 1):
        s = replay(replace(record, actions=record.actions[:k]))
        seat = s.to_act
        if record.abandoned and k == n:
            seat = None
        to_act = None if seat is None else "hero" if seat == HERO_SEAT else "villain"
        folded = folded_seats(s)
        result.append(
            {
                "stacks": [int(x) for x in s.stacks],
                "street_bets": [int(x) for x in s.street_bets],
                "pot": int(total_pot(s)),
                "board_len": len(s.board),
                "to_act": to_act,
                "to_act_seat": None if seat is None else int(seat),
                "folded": [i in folded for i in range(seats)],
                "pots": _live_pots(s, record.start_stacks),
            }
        )
    return result


def _outcome_view(record: HandRecord, out: Outcome) -> dict[str, Any]:
    heads_up_showdown = isinstance(out, HandOutcome) and out.ended_by == "showdown"
    return {
        "ended_by": out.ended_by,
        "winner": out.winner,
        "hero_delta_chips": int(out.hero_delta),
        "hero_delta_bb": float(out.hero_delta) / 2,
        "villain_cards": views._cards(bot_cards(record)) if heads_up_showdown else None,
        "showdown": (
            views.showdown_of(hero_cards(record), bot_cards(record), replay(record).board)
            if heads_up_showdown
            else None
        ),
        "pots": [
            {
                "amount": int(p.amount),
                "eligible": [int(i) for i in p.eligible],
                "winners": [int(i) for i in p.winners],
                "label": pot_label(k),
            }
            for k, p in enumerate(_awards(record, out))
        ],
        "shown": [
            {"seat": int(seat), "cards": views._cards(hole(record, seat))}
            for seat in _shown(record, out)
        ],
    }


def hand_view(
    hand_id: int,
    hand_no: int,
    session_id: int,
    record: HandRecord,
    profile: Profile | None,
    *,
    decision_count: int,
    bots: Sequence[SeatBotInfo] | None = None,
) -> dict[str, Any]:
    """One hand as it stands: the table, its frames, Hero's menu and (once over) the outcome.

    ``profile`` and ``bots`` as in ``table_view``."""
    s = replay(record)
    out = hand_outcome(record)
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
        "table": table_view(record, profile, bots=bots),
        "frames": frames(record),
        "options": options,
        "custom": custom,
        "outcome": None if out is None else _outcome_view(record, out),
    }


def session_view(session: dict[str, Any], hand: dict[str, Any] | None) -> dict[str, Any]:
    """A session with its latest hand.

    ``session`` holds ``id``, ``open``, ``profile`` (name, label, description; None in 5-max),
    ``hero_stack``, ``bot_stack`` (None in 5-max), ``hero_bought_chips`` and ``hands_played``,
    and optionally ``table_size`` (default 2) and ``bots`` (``{seat, name, profile, stack}`` per
    bot seat, the profile None when hidden; heads-up it defaults to the one bot with
    ``profile`` and ``bot_stack``). The stacks are those after the last finished hand, so the
    tally counts finished hands only. The next-hand choices are offered only to an open session
    whose latest hand is over.
    """
    hero = int(session["hero_stack"])
    net = hero - int(session["hero_bought_chips"])
    between_hands = bool(session["open"]) and (hand is None or hand["status"] == "complete")
    rebuy = between_hands and must_rebuy(hero)
    profile = None if session["profile"] is None else dict(session["profile"])
    bot_stack = None if session["bot_stack"] is None else int(session["bot_stack"])
    bots = session.get("bots")
    if bots is None:
        bots = [{"seat": 1, "name": HU_BOT_NAME, "profile": profile, "stack": bot_stack}]
    return {
        "id": int(session["id"]),
        "open": bool(session["open"]),
        "profile": profile,
        "hero_stack": hero,
        "bot_stack": bot_stack,
        "hero_bought_chips": int(session["hero_bought_chips"]),
        "net_chips": net,
        "net_bb": net / 2,
        "hands_played": int(session["hands_played"]),
        "must_rebuy": rebuy,
        "can_top_up": between_hands and not rebuy and hero < START,
        "hand": hand,
        "table_size": int(session.get("table_size", 2)),
        "bots": [
            {
                "seat": int(b["seat"]),
                "name": str(b["name"]),
                "profile": None if b["profile"] is None else dict(b["profile"]),
                "stack": int(b["stack"]),
            }
            for b in bots
        ],
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
        "explanation": explain(result, puzzle, views.action_log(puzzle.spot), subject="hand"),
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
