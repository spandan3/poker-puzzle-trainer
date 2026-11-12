"""SQLAlchemy 2.0 models: users, their settings, frozen puzzles and graded attempts.

Every row carries a ``user_id``. Timestamps are always UTC-aware (``UTCDateTime``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Dialect,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

DEFAULT_USER_ID = 1
DEFAULT_USER_NAME = "local"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Aware datetimes only; stored in UTC and read back with UTC attached (SQLite drops it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UTCDateTime needs an aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    show_pot_odds: Mapped[bool] = mapped_column(default=True)
    show_profile: Mapped[bool] = mapped_column(default=True)
    profile: Mapped[str | None] = mapped_column(String(16))  # None = random
    daily_goal: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PuzzleRow(Base):
    """A frozen puzzle. ``data`` is the ``db.blob`` encoding; never regenerated from ``seed``."""

    __tablename__ = "puzzles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    seed: Mapped[int] = mapped_column(BigInteger)
    street: Mapped[str] = mapped_column(String(8))
    profile: Mapped[str] = mapped_column(String(16))
    profile_version: Mapped[int] = mapped_column(Integer)
    categories_version: Mapped[int] = mapped_column(Integer)
    config_version: Mapped[int] = mapped_column(Integer)
    format: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class AttemptRow(Base):
    """One answer to a puzzle with its full grade, stored so it is never recomputed on read."""

    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("puzzle_id", "attempt_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    puzzle_id: Mapped[int] = mapped_column(ForeignKey("puzzles.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)  # 1 is the first
    is_first: Mapped[bool] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    # Inputs
    option_index: Mapped[int | None] = mapped_column(Integer)
    custom_to: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[dict[str, Any]] = mapped_column(JSON)  # seat / kind / street / to
    equity_guess: Mapped[float] = mapped_column()
    range_read_guess: Mapped[float | None] = mapped_column()
    intent: Mapped[str | None] = mapped_column(String(16))

    # Grade
    verdict: Mapped[str] = mapped_column(String(8), index=True)
    action_kind: Mapped[str] = mapped_column(String(8), index=True)
    best_kind: Mapped[str] = mapped_column(String(8))
    ev_loss_chips: Mapped[float] = mapped_column()
    equity_error: Mapped[float] = mapped_column()
    equity_score: Mapped[str] = mapped_column(String(8))
    range_read_error: Mapped[float | None] = mapped_column()
    range_read_score: Mapped[str | None] = mapped_column(String(8))
    intent_truth: Mapped[str | None] = mapped_column(String(16))
    intent_flag: Mapped[str | None] = mapped_column(Text)
    bluff_required: Mapped[float | None] = mapped_column()
    bluff_actual: Mapped[float | None] = mapped_column()
    chosen: Mapped[dict[str, Any]] = mapped_column(JSON)  # OptionEV dict, puzzle_to_dict shape
    chosen_label: Mapped[str] = mapped_column(String(64))  # history reads this, never ``chosen``
    best_label: Mapped[str] = mapped_column(String(64))
    best_ev_chips: Mapped[float] = mapped_column()
    config_version: Mapped[int] = mapped_column(Integer)  # live load_config().version at grading

    # Stats facts, from the puzzle at submit time, so stats never decode a puzzle blob.
    # Null on rows the 0003 backfill couldn't fill.
    true_equity: Mapped[float | None] = mapped_column()  # solution.equity
    ahead_now: Mapped[float | None] = mapped_column()  # solution.ahead_now; null on the river
    hero_category: Mapped[str | None] = mapped_column(String(16))  # CategoryCode; null pre-flop
