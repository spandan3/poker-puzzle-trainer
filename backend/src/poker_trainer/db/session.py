"""Engine and session helpers, programmatic migrations and the default local user."""

from __future__ import annotations

from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from poker_trainer.db.models import (
    DEFAULT_USER_ID,
    DEFAULT_USER_NAME,
    User,
    UserSettings,
)

MIGRATIONS = "poker_trainer.db:migrations"


def _sqlite_fk_on(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(url: str) -> Engine:
    """SQLite gets ``check_same_thread=False`` and foreign keys switched on per connection."""
    if make_url(url).get_backend_name() == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _sqlite_fk_on)
        return engine
    return create_engine(url)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config(url: str | None = None) -> Config:
    """An in-memory Alembic config pointing at the packaged migrations.

    The URL travels in ``attributes`` (never ``set_main_option``: a ``%`` in a password breaks
    configparser interpolation).
    """
    cfg = Config()
    cfg.set_main_option("script_location", MIGRATIONS)
    if url is not None:
        cfg.attributes["url"] = url
    return cfg


def migrate(url: str) -> None:
    """``alembic upgrade head`` on ``url``; idempotent."""
    command.upgrade(alembic_config(url), "head")


def ensure_default_user(session: Session) -> User:
    """Create user 1 ("local") and its settings row if missing. The caller commits."""
    user = session.get(User, DEFAULT_USER_ID)
    if user is None:
        user = User(id=DEFAULT_USER_ID, name=DEFAULT_USER_NAME)
        session.add(user)
        session.flush()
    if session.get(UserSettings, DEFAULT_USER_ID) is None:
        session.add(UserSettings(user_id=DEFAULT_USER_ID))
        session.flush()
    return user
