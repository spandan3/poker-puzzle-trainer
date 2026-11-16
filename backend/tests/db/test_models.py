from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError

from poker_trainer.db import (
    DEFAULT_USER_ID,
    AttemptRow,
    PlayDecisionRow,
    PlayHandRow,
    PlaySessionRow,
    PuzzleRow,
    User,
    UserSettings,
    ensure_default_user,
    make_engine,
    make_sessionmaker,
    migrate,
)


@pytest.fixture
def sessions(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    migrate(url)
    engine = make_engine(url)
    yield make_sessionmaker(engine)
    engine.dispose()


def _puzzle_row(user_id: int = DEFAULT_USER_ID) -> PuzzleRow:
    return PuzzleRow(
        user_id=user_id,
        seed=2**61 + 5,
        street="flop",
        profile="tag",
        profile_version=1,
        categories_version=1,
        config_version=1,
        format=1,
        data=b"\x00blob",
    )


def _attempt_row(puzzle_id: int, attempt_no: int = 1) -> AttemptRow:
    return AttemptRow(
        user_id=DEFAULT_USER_ID,
        puzzle_id=puzzle_id,
        attempt_no=attempt_no,
        is_first=attempt_no == 1,
        option_index=0,
        custom_to=None,
        action={"seat": 1, "kind": "check", "street": 1, "to": 0},
        equity_guess=0.5,
        range_read_guess=None,
        intent=None,
        verdict="best",
        action_kind="check",
        best_kind="check",
        ev_loss_chips=0.0,
        equity_error=0.01,
        equity_score="great",
        chosen={"label": "check"},
        chosen_label="check",
        best_label="check",
        best_ev_chips=1.5,
        config_version=1,
    )


def test_default_user_idempotent(sessions):
    with sessions() as db:
        u1 = ensure_default_user(db)
        db.commit()
        assert u1.id == DEFAULT_USER_ID == 1
    with sessions() as db:
        u2 = ensure_default_user(db)
        db.commit()
        assert u2.id == 1
        assert u2.name == "local"
        assert db.scalar(select(func.count()).select_from(User)) == 1
        assert db.scalar(select(func.count()).select_from(UserSettings)) == 1
        st = db.get(UserSettings, 1)
        assert st.show_pot_odds is True
        assert st.show_profile is True
        assert st.profile is None
        assert st.daily_goal == 10
        assert st.updated_at.tzinfo is not None


def test_attempt_unique_constraint(sessions):
    with sessions() as db:
        ensure_default_user(db)
        p = _puzzle_row()
        db.add(p)
        db.flush()
        db.add(_attempt_row(p.id, 1))
        db.flush()
        db.add(_attempt_row(p.id, 2))
        db.flush()
        db.add(_attempt_row(p.id, 1))
        with pytest.raises(IntegrityError):
            db.flush()


def test_foreign_keys_enforced(sessions):
    with sessions() as db:
        ensure_default_user(db)
        db.add(_attempt_row(puzzle_id=999))
        with pytest.raises(IntegrityError):
            db.flush()


def test_puzzle_row_round_trip(sessions):
    with sessions() as db:
        ensure_default_user(db)
        p = _puzzle_row()
        db.add(p)
        db.flush()
        a = _attempt_row(p.id)
        db.add(a)
        db.commit()
        pid, aid = p.id, a.id
    with sessions() as db:
        p = db.get(PuzzleRow, pid)
        assert p.seed == 2**61 + 5
        assert p.data == b"\x00blob"
        a = db.get(AttemptRow, aid)
        assert a.action == {"seat": 1, "kind": "check", "street": 1, "to": 0}
        assert a.is_first is True
        assert a.created_at.tzinfo is not None


def test_utc_round_trip(sessions):
    plus_two = timezone(timedelta(hours=2))
    with sessions() as db:
        db.add(User(id=7, name="tz", created_at=datetime(2026, 1, 1, 12, 0, tzinfo=plus_two)))
        db.commit()
    with sessions() as db:
        got = db.get(User, 7).created_at
        assert got == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        assert got.utcoffset() == timedelta(0)
        assert got.isoformat().endswith("+00:00")


def test_naive_datetime_rejected(sessions):
    with sessions() as db:
        db.add(User(id=8, name="naive", created_at=datetime(2026, 1, 1, 12, 0)))
        with pytest.raises(StatementError, match="aware"):
            db.flush()


def test_default_user_adds_missing_settings_row(sessions):
    with sessions() as db:
        db.add(User(id=DEFAULT_USER_ID, name="local"))
        db.commit()
    with sessions() as db:
        user = ensure_default_user(db)
        db.commit()
        assert user.id == DEFAULT_USER_ID
        assert db.scalar(select(func.count()).select_from(User)) == 1
        st = db.get(UserSettings, DEFAULT_USER_ID)
        assert st is not None
        assert st.daily_goal == 10


def test_foreign_keys_on_every_connection(sessions):
    engine = sessions.kw["bind"]
    with engine.connect() as a, engine.connect() as b:
        assert a.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert b.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# ---------------------------------------------------------------------------
# Play tables
# ---------------------------------------------------------------------------


def _play_session(user_id: int = DEFAULT_USER_ID, ended_at=None) -> PlaySessionRow:
    return PlaySessionRow(
        user_id=user_id,
        ended_at=ended_at,
        profile="tag",
        profile_version=1,
        profile_data={"name": "tag"},
        hero_stack=200,
        bot_stack=200,
        hero_bought_chips=200,
        next_button=0,
        hands_played=0,
    )


def _play_hand(session_id: int, hand_no: int = 1) -> PlayHandRow:
    return PlayHandRow(
        user_id=DEFAULT_USER_ID,
        session_id=session_id,
        hand_no=hand_no,
        button=0,
        start_stacks=[200, 200],
        deck=list(range(52)),
        bot_seed=2**61 + 3,
        actions=[],
        action_count=0,
        abandoned=False,
        status="in_progress",
        decision_count=0,
        strategy_version=1,
        categories_version=1,
        config_version=1,
    )


def _play_decision(hand_id: int, n: int = 0) -> PlayDecisionRow:
    return PlayDecisionRow(
        user_id=DEFAULT_USER_ID,
        hand_id=hand_id,
        n=n,
        status="not_graded",
        reason="unsupported",
        strategy_version=1,
        categories_version=1,
        config_version=1,
    )


def test_one_open_play_session_per_user(sessions):
    with sessions() as db:
        ensure_default_user(db)
        first = _play_session()
        db.add(first)
        db.commit()
        db.add(_play_session())
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        first = db.get(PlaySessionRow, first.id)
        first.ended_at = datetime(2026, 1, 1, tzinfo=UTC)
        db.commit()
        db.add(_play_session())  # allowed once the first has ended
        db.commit()
        db.add(_play_session(ended_at=datetime(2026, 1, 2, tzinfo=UTC)))  # ended ones pile up
        db.commit()


def test_play_hand_and_decision_numbers_are_unique(sessions):
    with sessions() as db:
        ensure_default_user(db)
        s = _play_session()
        db.add(s)
        db.commit()
        h = _play_hand(s.id)
        db.add(h)
        db.commit()
        db.add(_play_hand(s.id, hand_no=1))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(_play_hand(s.id, hand_no=2))
        db.commit()
        db.add(_play_decision(h.id))
        db.commit()
        db.add(_play_decision(h.id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(_play_decision(h.id, n=1))
        db.commit()
