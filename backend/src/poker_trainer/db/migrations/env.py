"""Alembic environment. The URL comes from ``config.attributes["url"]`` (``db.migrate``) or,
for the CLI, from ``get_settings().database_url``."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from poker_trainer.db.models import Base
from poker_trainer.settings import get_settings

config = context.config

# Only the CLI has an ini file; never reconfigure logging inside the app (it would silence uvicorn).
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url")
    return url if url is not None else get_settings().database_url


def _options(url: str) -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        "render_as_batch": make_url(url).get_backend_name() == "sqlite",
        "compare_type": True,
    }


def run_migrations_offline() -> None:
    url = _url()
    context.configure(
        url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **_options(url)
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    # Deliberately not ``make_engine``: SQLite batch migrations recreate tables (copy, DROP,
    # rename), and with ``PRAGMA foreign_keys=ON`` dropping a referenced table such as
    # ``users`` fails once child rows exist. Migrations run with SQLite's default (FKs off).
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, **_options(url))
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
