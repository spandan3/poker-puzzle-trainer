"""Play vs Bots: the database side of sessions and hands. No FastAPI here.

A session is one saved cash game, heads-up against one bot (a profile snapshot in the
``profile*`` columns) or 5-max against four (``seats``: per bot seat its display name, stack
and ``SeatBot`` snapshot); a hand is a ``HandRecord`` stored as rows (button, stacks, deck, the
bots' seed and the actions so far) and rebuilt by replay. Every query filters by ``user_id``. A hand's actions are written
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
from poker_trainer.api.service import (
    MAX_ID,
    ConcurrentSubmit,
    InvalidAnswer,
    NotFound,
    ServiceError,
)
from poker_trainer.api.views import action_log, option_ev_to_dict
from poker_trainer.db.blob import encode_puzzle
from poker_trainer.db.models import PlayDecisionRow, PlayHandRow, PlaySessionRow, UserSettings
from poker_trainer.explain.facts import Facts, build_facts
from poker_trainer.explain.template import explain
from poker_trainer.game.state import Action, ActionKind, Street, new_hand, position_name
from poker_trainer.play.analyse import DecisionAnalysis, analyse_decision, hero_decisions
from poker_trainer.play.hand import (
    HERO_SEAT,
    HandOutcome,
    HandOutcome5,
    HandRecord,
    SeatBot,
    abandon,
    advance,
    advance_seats,
    hero_act,
    hero_act_seats,
    replay,
)
from poker_trainer.play.session import (
    SEATS5,
    START,
    new_record,
    new_record5,
    next_button,
    next_stacks,
    next_stacks5,
)
from poker_trainer.puzzle.model import load_config
from poker_trainer.puzzle.options import custom_action, hero_options
from poker_trainer.villain import strategy
from poker_trainer.villain.features import load_thresholds
from poker_trainer.villain.preflop5 import load_fivemax, load_ranking
from poker_trainer.villain.profiles import PROFILE_NAMES, Profile, profile_data, profile_from_dict
from poker_trainer.villain.strategy import STRATEGY_VERSION

PlayRng = Callable[[], random.Random]

_IN_PROGRESS = "in_progress"
_COMPLETE = "complete"
HEADS_UP = 2
FIVEMAX_LABEL = "5-max"
NO_FIVEMAX_ANALYSIS = "Analysis of 5-max hands comes in a later version."


class AnalysisUnavailable(ServiceError):
    """The hand cannot be analysed yet (5-max hands)."""

    status_code = 409


Outcome = HandOutcome | HandOutcome5


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
        start_stacks=tuple(int(x) for x in row.start_stacks),
        deck=tuple(row.deck),
        bot_seed=row.bot_seed,
        actions=tuple(_action_from_dict(a) for a in row.actions),
        abandoned=row.abandoned,
    )


def _profile(sess: PlaySessionRow) -> Profile:
    """The session's profile as it was dealt; never the live profile file. In 5-max this is
    Bot 1's (the legacy columns hold its snapshot); nothing there reads it."""
    return profile_from_dict(sess.profile, sess.profile_data)


def _five_max(sess: PlaySessionRow) -> bool:
    return sess.table_size != HEADS_UP


def _seats(sess: PlaySessionRow) -> list[dict[str, Any]]:
    assert sess.seats is not None, "a 5-max session has seats"
    return list(sess.seats)


def _seat_bots(sess: PlaySessionRow) -> dict[int, SeatBot]:
    """Each 5-max bot seat's snapshot as it sat down; never the live data files."""
    return {int(e["seat"]): SeatBot.from_dict(e["bot"]) for e in _seats(sess)}


def _bot_infos(sess: PlaySessionRow) -> tuple[play_views.SeatBotInfo, ...] | None:
    """The 5-max bot seats for the views (None heads-up: the views use the profile)."""
    if not _five_max(sess):
        return None
    bots = _seat_bots(sess)
    return tuple(
        play_views.SeatBotInfo(int(e["seat"]), str(e["name"]), bots[int(e["seat"])].profile)
        for e in _seats(sess)
    )


def _outcome(record: HandRecord) -> Outcome | None:
    return play_views.hand_outcome(record)


def _award_dicts(out: Outcome) -> list[dict[str, Any]] | None:
    """The stored pots of a finished 5-max hand (None heads-up: the column stays null)."""
    if not isinstance(out, HandOutcome5):
        return None
    return [
        {
            "amount": int(p.amount),
            "eligible": [int(i) for i in p.eligible],
            "winners": [int(i) for i in p.winners],
        }
        for p in out.pots
    ]


def _finished_values(record: HandRecord, out: Outcome) -> dict[str, Any]:
    values = {
        "actions": [_action_dict(a) for a in record.actions],
        "action_count": len(record.actions),
        "abandoned": record.abandoned,
        "status": _COMPLETE,
        "ended_by": out.ended_by,
        "winner": out.winner,
        "hero_delta_chips": int(out.hero_delta),
        "decision_count": len(hero_decisions(record)),
    }
    pots = _award_dicts(out)
    if pots is not None:
        values["pots"] = pots
    return values


def _settle_session(sess: PlaySessionRow, button: int, out: Outcome) -> None:
    """A finished hand moves the session: its stacks, the hand count and the button."""
    if _five_max(sess):
        sess.hero_stack = int(out.stacks[HERO_SEAT])
        sess.seats = [{**e, "stack": int(out.stacks[int(e["seat"])])} for e in _seats(sess)]
        sess.next_button = next_button(button, SEATS5)
    else:
        sess.hero_stack, sess.bot_stack = int(out.stacks[0]), int(out.stacks[1])
        sess.next_button = 1 - button
    sess.hands_played += 1


def _show_profile(db: Session, user_id: int) -> bool:
    """The user's "show profile" setting, read without creating the settings row."""
    row = db.get(UserSettings, user_id)
    return True if row is None else bool(row.show_profile)


def _hand_view(sess: PlaySessionRow, hand: PlayHandRow) -> dict[str, Any]:
    five = _five_max(sess)
    return play_views.hand_view(
        hand.id,
        hand.hand_no,
        sess.id,
        _record(hand),
        None if five else _profile(sess),
        decision_count=hand.decision_count,
        bots=_bot_infos(sess),
    )


def _view(db: Session, sess: PlaySessionRow, hand: PlayHandRow | None) -> dict[str, Any]:
    show = _show_profile(db, sess.user_id)
    hv = None if hand is None else _hand_view(sess, hand)
    if _five_max(sess):
        infos = _bot_infos(sess)
        assert infos is not None
        stacks = {int(e["seat"]): int(e["stack"]) for e in _seats(sess)}
        profile = None
        bot_stack = None
        bots = [
            {
                "seat": b.seat,
                "name": b.name,
                "profile": play_views.profile_info(b.profile) if show else None,
                "stack": stacks[b.seat],
            }
            for b in infos
        ]
    else:
        p = _profile(sess)
        profile = play_views.profile_info(p)
        bot_stack = sess.bot_stack
        bots = [
            {
                "seat": 1,
                "name": play_views.HU_BOT_NAME,
                "profile": profile if show else None,
                "stack": sess.bot_stack,
            }
        ]
    return play_views.session_view(
        {
            "id": sess.id,
            "open": sess.ended_at is None,
            "profile": profile,
            "hero_stack": sess.hero_stack,
            "bot_stack": bot_stack,
            "hero_bought_chips": sess.hero_bought_chips,
            "hands_played": sess.hands_played,
            "table_size": sess.table_size,
            "bots": bots,
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
    stacks: tuple[int, ...],
    rng: random.Random,
) -> PlayHandRow:
    """Deal hand ``hand_no`` and advance the bots to Hero's turn; settle it at once if it is
    already over (heads-up the bot folded the button; in 5-max the bots folded round to Hero's
    big blind). The insert is flushed first, so a doubled "next hand" hits the
    ``(session_id, hand_no)`` constraint before anything else changes."""
    button = sess.next_button
    five = _five_max(sess)
    if five:
        record = advance_seats(new_record5(button, stacks, rng), _seat_bots(sess))
        ranking_version, _ = load_ranking()
        bot_versions = {"hand_ranking": ranking_version, "fivemax": load_fivemax().version}
    else:
        record = advance(new_record(button, (stacks[0], stacks[1]), rng), _profile(sess))
        bot_versions = None
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
        table_size=sess.table_size,
        bot_versions=bot_versions,
    )
    db.add(row)
    db.flush()
    out = _outcome(record)
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


def _new_session_row(user_id: int, rng: random.Random, table_size: int) -> PlaySessionRow:
    """A new session row. Heads-up draws the profile then the button from ``rng``, exactly as
    before 5-max; 5-max draws four profiles (repeats allowed) then the button."""
    if table_size == HEADS_UP:
        name = rng.choice(PROFILE_NAMES)
        data = profile_data(name)
        profile = profile_from_dict(name, data)
        return PlaySessionRow(
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
            table_size=HEADS_UP,
        )
    if table_size != SEATS5:
        raise InvalidAnswer(f"table_size must be 2 or {SEATS5}")
    bots = [SeatBot.live(rng.choice(PROFILE_NAMES)) for _ in range(1, SEATS5)]
    first = bots[0].to_dict()
    return PlaySessionRow(
        user_id=user_id,
        created_at=service.utcnow(),
        # the legacy NOT NULL columns hold Bot 1's snapshot; nothing reads them in 5-max
        profile=first["profile"],
        profile_version=bots[0].profile.version,
        profile_data=first["profile_data"],
        hero_stack=START,
        bot_stack=0,  # heads-up only
        hero_bought_chips=START,
        next_button=rng.randrange(SEATS5),
        hands_played=0,
        table_size=SEATS5,
        seats=[
            {
                "seat": seat,
                "name": play_views.bot_name(seat, SEATS5),
                "stack": START,
                "bot": bot.to_dict(),
            }
            for seat, bot in enumerate(bots, start=1)
        ],
    )


def start_session(
    db: Session, user_id: int, play_rng: PlayRng, table_size: int = HEADS_UP
) -> dict[str, Any]:
    """Start a session at a heads-up (2) or 5-max (5) table and deal its first hand."""
    if _open_session(db, user_id) is not None:
        raise ConcurrentSubmit("a session is already open")
    rng = play_rng()
    sess = _new_session_row(user_id, rng, table_size)
    stacks = (START,) * sess.table_size
    try:
        db.add(sess)
        db.flush()
        hand = _deal(db, user_id, sess, 1, stacks, rng)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConcurrentSubmit("a session is already open")
    return _view(db, sess, hand)


def current_session(db: Session, user_id: int) -> dict[str, Any]:
    sess = _open_session(db, user_id)
    if sess is None:
        raise NotFound("no open session")
    return _view(db, sess, _latest_hand(db, user_id, sess.id))


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
    stacks: tuple[int, ...]
    values: dict[str, Any]
    if _five_max(sess):
        seats = _seats(sess)
        hero, bots, bought = next_stacks5(
            sess.hero_stack, [int(e["stack"]) for e in seats], top_up=top_up
        )
        new_seats = [{**e, "stack": int(b)} for e, b in zip(seats, bots, strict=True)]
        stacks = (hero, *bots)
        values = {"hero_stack": hero, "seats": new_seats}
    else:
        hero, bot, bought = next_stacks(sess.hero_stack, sess.bot_stack, top_up=top_up)
        stacks = (hero, bot)
        values = {"hero_stack": hero, "bot_stack": bot}
    # the session write is conditional: another tab may have ended it since it was loaded
    res = db.execute(
        update(PlaySessionRow)
        .where(PlaySessionRow.id == sess.id, PlaySessionRow.ended_at.is_(None))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        db.rollback()
        raise ConcurrentSubmit("the session has ended")
    for k, v in values.items():
        setattr(sess, k, v)
    sess.hero_bought_chips += bought
    hand_no = 1 if last is None else last.hand_no + 1
    try:
        hand = _deal(db, user_id, sess, hand_no, stacks, play_rng())
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConcurrentSubmit("another request dealt the next hand")
    return _view(db, sess, hand)


# ---------------------------------------------------------------------------
# Acting
# ---------------------------------------------------------------------------


def _write_hand(
    db: Session,
    row: PlayHandRow,
    expected: int,
    record: HandRecord,
    out: Outcome | None,
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
    try:  # only Hero's own answer is a 422; a bot failing below is a server error
        if option is not None:
            options = hero_options(s)
            if not 0 <= option < len(options):
                raise ValueError(f"option must be in [0, {len(options) - 1}]")
            action = options[option].action
        else:
            assert custom_to is not None
            action = custom_action(s, custom_to)
    except ValueError as e:
        raise InvalidAnswer(str(e))
    if _five_max(sess):
        new = hero_act_seats(record, _seat_bots(sess), action)
    else:
        new = hero_act(record, profile, action)
    out = _outcome(new)
    _write_hand(db, row, expected_actions, new, out)
    if out is not None:
        _settle_session(sess, row.button, out)
    db.commit()
    _refresh(db, sess, row)
    return _view(db, sess, row)


def end_session(db: Session, user_id: int, session_id: int) -> dict[str, Any]:
    """End the session; a running hand is abandoned (Hero keeps what is behind; heads-up the bot
    takes the pot, in 5-max see ``outcome5``). Ending twice returns the same view."""
    sess = _load_session(db, user_id, session_id)
    hand = _latest_hand(db, user_id, sess.id)
    if sess.ended_at is not None:
        return _view(db, sess, hand)
    res = db.execute(
        update(PlaySessionRow)
        .where(PlaySessionRow.id == sess.id, PlaySessionRow.ended_at.is_(None))
        .values(ended_at=service.utcnow())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]  # ended by another request meanwhile
        db.rollback()
        return _view(db, _load_session(db, user_id, session_id), hand)
    if hand is not None and hand.status == _IN_PROGRESS:
        record = abandon(_record(hand))
        out = _outcome(record)
        assert out is not None
        _write_hand(db, hand, hand.action_count, record, out)
        _settle_session(sess, hand.button, out)
    db.commit()
    _refresh(db, sess, hand)
    return _view(db, sess, hand)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_hand(db: Session, user_id: int, hand_id: int) -> dict[str, Any]:
    row, sess, _, _ = load_hand(db, user_id, hand_id)
    return _hand_view(sess, row)


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
            "profile_label": FIVEMAX_LABEL if _five_max(r) else _profile(r).label,
            "hands_played": r.hands_played,
            "net_bb": (r.hero_stack - r.hero_bought_chips) / 2,
            "open": r.ended_at is None,
            "table_size": r.table_size,
        }
        for r in rows
    ]


def _winner_names(sess: PlaySessionRow, row: PlayHandRow) -> list[str]:
    """Who took a pot in a finished hand, Hero as "You", in seat order. Heads-up it follows
    ``winner`` (an abandoned hand is the bot's); in 5-max the stored pots (none when
    abandoned)."""
    if row.status != _COMPLETE:
        return []
    if row.table_size == HEADS_UP:
        hero, bot = play_views.HERO_NAME, play_views.HU_BOT_NAME
        return {"hero": [hero], "villain": [bot], "split": [hero, bot]}.get(row.winner or "", [])
    names = {int(e["seat"]): str(e["name"]) for e in _seats(sess)}
    names[HERO_SEAT] = play_views.HERO_NAME
    winners = sorted({int(w) for p in row.pots or [] for w in p["winners"]})
    return [names[w] for w in winners]


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
            "analysed": r.table_size == HEADS_UP and r.ev_loss_chips is not None,
            "ev_loss_bb": None if r.ev_loss_chips is None else r.ev_loss_chips / 2,
            "table_size": r.table_size,
            "winner_names": _winner_names(sess, r),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Hand analysis
# ---------------------------------------------------------------------------


def _heads_up_hand(
    db: Session, user_id: int, hand_id: int
) -> tuple[PlayHandRow, PlaySessionRow, HandRecord, Profile]:
    """``load_hand`` for the analysis routes: a 5-max hand is refused (409)."""
    row, sess, record, profile = load_hand(db, user_id, hand_id)
    if row.table_size != HEADS_UP:
        raise AnalysisUnavailable(NO_FIVEMAX_ANALYSIS)
    return row, sess, record, profile


def _finished_hand(
    db: Session, user_id: int, hand_id: int
) -> tuple[PlayHandRow, HandRecord, Profile]:
    row, _, record, profile = _heads_up_hand(db, user_id, hand_id)
    if row.status != _COMPLETE:
        raise ConcurrentSubmit("the hand is still being played")
    return row, record, profile


def _check_decision(record: HandRecord, n: int) -> None:
    if not 0 <= n < len(hero_decisions(record)):
        raise NotFound("decision not found")


def _stored_decision(db: Session, user_id: int, hand_id: int, n: int) -> PlayDecisionRow | None:
    return db.scalar(
        select(PlayDecisionRow).where(
            PlayDecisionRow.hand_id == hand_id,
            PlayDecisionRow.n == n,
            PlayDecisionRow.user_id == user_id,
        )
    )


def _stored_decisions(db: Session, user_id: int, hand_id: int) -> list[PlayDecisionRow]:
    return list(
        db.scalars(
            select(PlayDecisionRow)
            .where(PlayDecisionRow.hand_id == hand_id, PlayDecisionRow.user_id == user_id)
            .order_by(PlayDecisionRow.n)
        ).all()
    )


def _model_changed(row: PlayHandRow) -> bool:
    """True when the Villain model the hand was played with is not today's (looked up now)."""
    return (
        row.strategy_version != strategy.STRATEGY_VERSION
        or row.categories_version != load_thresholds().version
        or row.config_version != load_config().version
    )


def _decision_fields(a: DecisionAnalysis) -> dict[str, Any]:
    """The stored columns of an analysed decision (live model versions included)."""
    fields: dict[str, Any] = {
        "strategy_version": strategy.STRATEGY_VERSION,
        "categories_version": load_thresholds().version,
        "config_version": load_config().version,
    }
    if a.puzzle is None or a.grade is None:
        return {**fields, "status": play_views.NOT_GRADED, "reason": a.not_graded}
    g = a.grade
    action = g.chosen.option.action
    listed = any(o.option.action == action for o in a.puzzle.solution.options)
    graded = {
        "status": play_views.GRADED,
        "puzzle": encode_puzzle(a.puzzle),
        "chosen": option_ev_to_dict(g.chosen),
        "custom_to": None if listed else int(action.to),
        "verdict": g.verdict,
        "ev_loss_chips": float(g.ev_loss_chips),
        "best_label": g.best.option.label,
        "best_ev_chips": float(g.best.ev_chips),
        "intent_truth": g.intent_truth,
        "bluff_required": None if g.bluff_check is None else float(g.bluff_check[0]),
        "bluff_actual": None if g.bluff_check is None else float(g.bluff_check[1]),
    }
    service._check_finite({k: v for k, v in graded.items() if k != "puzzle"}, "decision")
    return {**fields, **graded}


def _total_if_done(db: Session, user_id: int, hand_id: int, count: int) -> None:
    """Once every decision is stored, set the hand's total EV lost over the graded ones.

    Runs after each insert has committed, so of two requests storing the last decisions at once
    the later one sees both rows; the update only fills a total that is not set yet."""
    rows = _stored_decisions(db, user_id, hand_id)
    if len(rows) != count:
        return
    total = sum(float(r.ev_loss_chips or 0.0) for r in rows if r.status == play_views.GRADED)
    db.execute(
        update(PlayHandRow)
        .where(
            PlayHandRow.id == hand_id,
            PlayHandRow.user_id == user_id,
            PlayHandRow.ev_loss_chips.is_(None),
        )
        .values(ev_loss_chips=total)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def hand_analysis(db: Session, user_id: int, hand_id: int) -> dict[str, Any]:
    """What is stored of a finished hand's analysis; 409 while the hand is running."""
    row, record, profile = _finished_hand(db, user_id, hand_id)
    by_n = {r.n: r for r in _stored_decisions(db, user_id, hand_id)}
    count = len(hero_decisions(record))
    rows = [by_n.get(n) for n in range(count)]
    if row.ev_loss_chips is None and all(r is not None for r in rows):
        # every decision is stored but the total is not: a crash between the two; repair it
        _total_if_done(db, user_id, hand_id, count)
        db.refresh(row)
    return play_views.hand_analysis(
        row.id, record, profile, rows, model_changed=_model_changed(row)
    )


def analyse(
    db: Session, user_id: int, hand_id: int, n: int, *, samples: int | None
) -> dict[str, Any]:
    """Decision ``n`` of a finished hand, analysed and stored on the first request.

    The database transaction is released while solving. A decision stored meanwhile by another
    request (the unique ``(hand_id, n)`` constraint) is returned instead of this one's."""
    _, record, profile = _finished_hand(db, user_id, hand_id)
    _check_decision(record, n)
    stored = _stored_decision(db, user_id, hand_id, n)
    if stored is None:
        db.rollback()  # don't hold a transaction open during the CPU-bound solve
        a = analyse_decision(record, profile, n, samples=samples)
        new = PlayDecisionRow(
            user_id=user_id,
            hand_id=hand_id,
            n=n,
            created_at=service.utcnow(),
            **_decision_fields(a),
        )
        db.add(new)
        try:
            db.commit()
            stored = new
        except IntegrityError:
            db.rollback()
            stored = _stored_decision(db, user_id, hand_id, n)
            assert stored is not None
        _total_if_done(db, user_id, hand_id, len(hero_decisions(record)))
    return play_views.decision_review(stored, record, profile)


def decision_explanation_inputs(
    db: Session, user_id: int, hand_id: int, n: int
) -> tuple[dict[str, Any], Facts]:
    """A stored, graded decision's template explanation and the facts it was written from
    (404 for a decision that is not analysed or not graded; 409 for a 5-max hand)."""
    _, _, record, profile = _heads_up_hand(db, user_id, hand_id)
    _check_decision(record, n)
    row = _stored_decision(db, user_id, hand_id, n)
    if row is None or row.status != play_views.GRADED:
        raise NotFound("decision not analysed")
    result, puzzle = play_views.explanation_result(row, record, profile)
    log = action_log(puzzle.spot)
    return (
        explain(result, puzzle, log, subject="hand"),
        build_facts(result, puzzle, log, subject="hand"),
    )


__all__ = [
    "AnalysisUnavailable",
    "PlayRng",
    "act",
    "analyse",
    "current_session",
    "decision_explanation_inputs",
    "end_session",
    "get_hand",
    "hand_analysis",
    "list_hands",
    "list_sessions",
    "load_hand",
    "next_hand",
    "start_session",
]
