"""Play vs Bots: the database side of sessions and hands. No FastAPI here.

A session is one saved cash game against the bot with a profile snapshot; a hand is a
``HandRecord`` stored as rows (button, stacks, deck, the bot's seed and the actions so far) and
rebuilt by replay. Every query filters by ``user_id``. A hand's actions are written
compare-and-set on ``action_count`` so a stale or doubled click cannot act twice, and finishing a
hand updates the hand row and its session row in one transaction.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from poker_trainer.api import play_views, service
from poker_trainer.api.service import MAX_ID, ConcurrentSubmit, InvalidAnswer, NotFound
from poker_trainer.db.models import PlayHandRow, PlaySessionRow
from poker_trainer.game.state import Action, ActionKind, Street, new_hand, position_name
from poker_trainer.play.analyse import hero_decisions
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandOutcome,
    HandRecord,
    abandon,
    advance,
    hero_act,
    outcome,
    replay,
)
from poker_trainer.play.session import START, new_record, next_stacks
from poker_trainer.puzzle.model import load_config
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, profile_data, profile_from_dict
from poker_trainer.villain.strategy import STRATEGY_VERSION

PlayRng = Callable[[], random.Random]

_IN_PROGRESS = "in_progress"
_COMPLETE = "complete"


# ---------------------------------------------------------------------------
# Rows <-> records
# ---------------------------------------------------------------------------


def _action_dict(a: Action) -> dict[str, Any]:
    return {"seat": int(a.seat), "kind": a.kind.value, "street": int(a.street), "to": int(a.to)}


def _action_from_dict(d: dict[str, Any]) -> Action:
    return Action(d["seat"], ActionKind(d["kind"]), Street(d["street"]), d["to"])


def _record(row: PlayHandRow) -> HandRecord:
    return HandRecord(
        button=row.button,
        start_stacks=(row.start_stacks[0], row.start_stacks[1]),
        deck=tuple(row.deck),
        bot_seed=row.bot_seed,
        actions=tuple(_action_from_dict(a) for a in row.actions),
        abandoned=row.abandoned,
    )


def _profile(sess: PlaySessionRow) -> Profile:
    """The session's profile as it was dealt; never the live profile file."""
    return profile_from_dict(sess.profile, sess.profile_data)


def _finished_values(record: HandRecord, out: HandOutcome) -> dict[str, Any]:
    return {
        "actions": [_action_dict(a) for a in record.actions],
        "action_count": len(record.actions),
        "abandoned": record.abandoned,
        "status": _COMPLETE,
        "ended_by": out.ended_by,
        "winner": out.winner,
        "hero_delta_chips": int(out.hero_delta),
        "decision_count": len(hero_decisions(record)),
    }


def _settle_session(sess: PlaySessionRow, button: int, out: HandOutcome) -> None:
    """A finished hand moves the session: its stacks, the hand count and the button."""
    sess.hero_stack, sess.bot_stack = int(out.stacks[0]), int(out.stacks[1])
    sess.hands_played += 1
    sess.next_button = 1 - button


def _view(sess: PlaySessionRow, hand: PlayHandRow | None) -> dict[str, Any]:
    profile = _profile(sess)
    hv = (
        None
        if hand is None
        else play_views.hand_view(
            hand.id,
            hand.hand_no,
            sess.id,
            _record(hand),
            profile,
            decision_count=hand.decision_count,
        )
    )
    return play_views.session_view(
        {
            "id": sess.id,
            "open": sess.ended_at is None,
            "profile": {
                "name": profile.name,
                "label": profile.label,
                "description": profile.description,
            },
            "hero_stack": sess.hero_stack,
            "bot_stack": sess.bot_stack,
            "hero_bought_chips": sess.hero_bought_chips,
            "hands_played": sess.hands_played,
        },
        hv,
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_session(db: Session, user_id: int, session_id: int) -> PlaySessionRow:
    if not 0 < session_id <= MAX_ID:
        raise NotFound("session not found")
    sess = db.scalar(
        select(PlaySessionRow).where(
            PlaySessionRow.id == session_id, PlaySessionRow.user_id == user_id
        )
    )
    if sess is None:
        raise NotFound("session not found")
    return sess


def _latest_hand(db: Session, user_id: int, session_id: int) -> PlayHandRow | None:
    return db.scalar(
        select(PlayHandRow)
        .where(PlayHandRow.session_id == session_id, PlayHandRow.user_id == user_id)
        .order_by(PlayHandRow.hand_no.desc())
        .limit(1)
    )


def _open_session(db: Session, user_id: int) -> PlaySessionRow | None:
    return db.scalar(
        select(PlaySessionRow).where(
            PlaySessionRow.user_id == user_id, PlaySessionRow.ended_at.is_(None)
        )
    )


def load_hand(
    db: Session, user_id: int, hand_id: int
) -> tuple[PlayHandRow, PlaySessionRow, HandRecord, Profile]:
    """A hand with its session, its record and the session's profile snapshot (404 if not the
    user's)."""
    if not 0 < hand_id <= MAX_ID:
        raise NotFound("hand not found")
    row = db.scalar(
        select(PlayHandRow).where(PlayHandRow.id == hand_id, PlayHandRow.user_id == user_id)
    )
    if row is None:
        raise NotFound("hand not found")
    sess = db.get(PlaySessionRow, row.session_id)
    assert sess is not None
    return row, sess, _record(row), _profile(sess)


# ---------------------------------------------------------------------------
# Dealing
# ---------------------------------------------------------------------------


def _deal(
    db: Session,
    user_id: int,
    sess: PlaySessionRow,
    hand_no: int,
    stacks: tuple[int, int],
    rng: random.Random,
) -> PlayHandRow:
    """Deal hand ``hand_no`` and advance the bot to Hero's turn; settle it at once if it is
    already over (the bot folded the button). The insert is flushed first, so a doubled "next
    hand" hits the ``(session_id, hand_no)`` constraint before anything else changes."""
    button = sess.next_button
    record = advance(new_record(button, stacks, rng), _profile(sess))
    row = PlayHandRow(
        user_id=user_id,
        session_id=sess.id,
        hand_no=hand_no,
        created_at=service.utcnow(),
        button=button,
        start_stacks=list(record.start_stacks),
        deck=list(record.deck),
        bot_seed=record.bot_seed,
        actions=[_action_dict(a) for a in record.actions],
        action_count=len(record.actions),
        abandoned=False,
        status=_IN_PROGRESS,
        decision_count=len(hero_decisions(record)),
        strategy_version=STRATEGY_VERSION,
        categories_version=load_thresholds().version,
        config_version=load_config().version,
    )
    db.add(row)
    db.flush()
    out = outcome(record)
    if out is not None:
        for k, v in _finished_values(record, out).items():
            setattr(row, k, v)
        _settle_session(sess, button, out)
    return row


def _refresh(db: Session, *rows: Any) -> None:
    """Reload rows after a commit: the sessionmaker keeps instances loaded, and compare-and-set
    updates go around the ORM, so the instances are stale."""
    for r in rows:
        if r is not None:
            db.refresh(r)


def start_session(db: Session, user_id: int, play_rng: PlayRng) -> dict[str, Any]:
    if _open_session(db, user_id) is not None:
        raise ConcurrentSubmit("a session is already open")
    rng = play_rng()
    name = rng.choice(PROFILE_NAMES)
    data = profile_data(name)
    profile = profile_from_dict(name, data)
    sess = PlaySessionRow(
        user_id=user_id,
        created_at=service.utcnow(),
        profile=name,
        profile_version=profile.version,
        profile_data=data,
        hero_stack=START,
        bot_stack=START,
        hero_bought_chips=START,
        next_button=rng.randrange(2),
        hands_played=0,
    )
    try:
        db.add(sess)
        db.flush()
        hand = _deal(db, user_id, sess, 1, (START, START), rng)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConcurrentSubmit("a session is already open")
    return _view(sess, hand)


def current_session(db: Session, user_id: int) -> dict[str, Any]:
    sess = _open_session(db, user_id)
    if sess is None:
        raise NotFound("no open session")
    return _view(sess, _latest_hand(db, user_id, sess.id))


def next_hand(
    db: Session,
    user_id: int,
    session_id: int,
    *,
    expected_hands: int,
    top_up: bool,
    play_rng: PlayRng,
) -> dict[str, Any]:
    sess = _load_session(db, user_id, session_id)
    if sess.ended_at is not None:
        raise ConcurrentSubmit("the session has ended")
    if expected_hands != sess.hands_played:
        raise ConcurrentSubmit("the table has moved on; reload it")
    last = _latest_hand(db, user_id, sess.id)
    if last is not None and last.status != _COMPLETE:
        raise ConcurrentSubmit("the current hand is still being played")
    hero, bot, bought = next_stacks(sess.hero_stack, sess.bot_stack, top_up=top_up)
    sess.hero_stack, sess.bot_stack = hero, bot
    sess.hero_bought_chips += bought
    hand_no = 1 if last is None else last.hand_no + 1
    try:
        hand = _deal(db, user_id, sess, hand_no, (hero, bot), play_rng())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConcurrentSubmit("another request dealt the next hand")
    return _view(sess, hand)


# ---------------------------------------------------------------------------
# Acting
# ---------------------------------------------------------------------------


def _write_hand(
    db: Session,
    row: PlayHandRow,
    expected: int,
    record: HandRecord,
    out: HandOutcome | None,
) -> None:
    """Compare-and-set the hand's actions; no row updated means another request got there."""
    values: dict[str, Any] = (
        _finished_values(record, out)
        if out is not None
        else {
            "actions": [_action_dict(a) for a in record.actions],
            "action_count": len(record.actions),
            "abandoned": record.abandoned,
            "decision_count": len(hero_decisions(record)),
        }
    )
    res = db.execute(
        update(PlayHandRow)
        .where(
            PlayHandRow.id == row.id,
            PlayHandRow.action_count == expected,
            PlayHandRow.status == _IN_PROGRESS,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        raise ConcurrentSubmit("the hand changed; reload the table")


def act(
    db: Session,
    user_id: int,
    hand_id: int,
    *,
    expected_actions: int,
    option: int | None,
    custom_to: int | None,
) -> dict[str, Any]:
    row, sess, record, profile = load_hand(db, user_id, hand_id)
    if row.status != _IN_PROGRESS:
        raise ConcurrentSubmit("the hand is over")
    if sess.ended_at is not None:
        raise ConcurrentSubmit("the session has ended")
    if expected_actions != row.action_count:
        raise ConcurrentSubmit("the table has moved on; reload it")
    s = replay(record)
    try:
        if option is not None:
            options = hero_options(s)
            if not 0 <= option < len(options):
                raise ValueError(f"option must be in [0, {len(options) - 1}]")
            action = options[option].action
        else:
            assert custom_to is not None
            action = custom_action(s, custom_to)
        new = hero_act(record, profile, action)
    except ValueError as e:
        raise InvalidAnswer(str(e))
    out = outcome(new)
    _write_hand(db, row, expected_actions, new, out)
    if out is not None:
        _settle_session(sess, row.button, out)
    db.commit()
    _refresh(db, sess, row)
    return _view(sess, row)


def end_session(db: Session, user_id: int, session_id: int) -> dict[str, Any]:
    """End the session; a running hand is abandoned (Hero keeps what is behind, the bot takes
    the pot). Ending twice returns the same view."""
    sess = _load_session(db, user_id, session_id)
    hand = _latest_hand(db, user_id, sess.id)
    if sess.ended_at is not None:
        return _view(sess, hand)
    res = db.execute(
        update(PlaySessionRow)
        .where(PlaySessionRow.id == sess.id, PlaySessionRow.ended_at.is_(None))
        .values(ended_at=service.utcnow())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]  # ended by another request meanwhile
        db.rollback()
        return _view(_load_session(db, user_id, session_id), hand)
    if hand is not None and hand.status == _IN_PROGRESS:
        record = abandon(_record(hand))
        out = outcome(record)
        assert out is not None
        _write_hand(db, hand, hand.action_count, record, out)
        _settle_session(sess, hand.button, out)
    db.commit()
    _refresh(db, sess, hand)
    return _view(sess, hand)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_hand(db: Session, user_id: int, hand_id: int) -> dict[str, Any]:
    row, sess, record, profile = load_hand(db, user_id, hand_id)
    return play_views.hand_view(
        row.id, row.hand_no, sess.id, record, profile, decision_count=row.decision_count
    )


def list_sessions(db: Session, user_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(PlaySessionRow)
        .where(PlaySessionRow.user_id == user_id)
        .order_by(PlaySessionRow.created_at.desc(), PlaySessionRow.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat(),
            "ended_at": None if r.ended_at is None else r.ended_at.isoformat(),
            "profile_label": _profile(r).label,
            "hands_played": r.hands_played,
            "net_bb": (r.hero_stack - r.hero_bought_chips) / 2,
            "open": r.ended_at is None,
        }
        for r in rows
    ]


def list_hands(db: Session, user_id: int, session_id: int) -> list[dict[str, Any]]:
    sess = _load_session(db, user_id, session_id)
    rows = db.scalars(
        select(PlayHandRow)
        .where(PlayHandRow.session_id == sess.id, PlayHandRow.user_id == user_id)
        .order_by(PlayHandRow.hand_no)
    ).all()
    return [
        {
            "id": r.id,
            "hand_no": r.hand_no,
            "hero_position": position_name(new_hand(r.button, tuple(r.start_stacks)), HERO_SEAT),
            "result_bb": None if r.hero_delta_chips is None else r.hero_delta_chips / 2,
            "ended_by": r.ended_by,
            "decision_count": r.decision_count,
            "analysed": r.ev_loss_chips is not None,
            "ev_loss_bb": None if r.ev_loss_chips is None else r.ev_loss_chips / 2,
        }
        for r in rows
    ]


__all__ = [
    "PlayRng",
    "act",
    "current_session",
    "end_session",
    "get_hand",
    "list_hands",
    "list_sessions",
    "load_hand",
    "next_hand",
    "start_session",
]
