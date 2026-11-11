"""Persistence: models, engine/session helpers, migrations, puzzle blobs."""

from poker_trainer.db.blob import decode_puzzle, encode_puzzle
from poker_trainer.db.models import (
    DEFAULT_USER_ID,
    AttemptRow,
    Base,
    PuzzleRow,
    User,
    UserSettings,
)
from poker_trainer.db.session import (
    alembic_config,
    ensure_default_user,
    make_engine,
    make_sessionmaker,
    migrate,
)

__all__ = [
    "DEFAULT_USER_ID",
    "AttemptRow",
    "Base",
    "PuzzleRow",
    "User",
    "UserSettings",
    "alembic_config",
    "decode_puzzle",
    "encode_puzzle",
    "ensure_default_user",
    "make_engine",
    "make_sessionmaker",
    "migrate",
]
