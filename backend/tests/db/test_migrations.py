import os
from importlib.resources import files

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from poker_trainer.db import (
    DEFAULT_USER_ID,
    Base,
    PuzzleRow,
    alembic_config,
    ensure_default_user,
    make_engine,
    make_sessionmaker,
    migrate,
)
from poker_trainer.settings import get_settings

TABLES = {"users", "user_settings", "puzzles", "attempts"}


def _url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_migrate_creates_tables(tmp_path):
    url = _url(tmp_path / "a.db")
    migrate(url)
    engine = make_engine(url)
    try:
        assert TABLES <= set(inspect(engine).get_table_names())
        head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
        with engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == head
        assert head == "0002_chosen_label"
    finally:
        engine.dispose()


def test_migrate_idempotent(tmp_path):
    url = _url(tmp_path / "a.db")
    migrate(url)
    migrate(url)


def test_models_match_migrations(tmp_path):
    url = _url(tmp_path / "a.db")
    migrate(url)
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            assert compare_metadata(ctx, Base.metadata) == []
    finally:
        engine.dispose()


def test_migrate_uses_given_url(tmp_path, monkeypatch):
    other = tmp_path / "b.db"
    monkeypatch.setenv("PPT_DATABASE_URL", _url(other))
    get_settings.cache_clear()
    try:
        url = _url(tmp_path / "a.db")
        migrate(url)
        engine = make_engine(url)
        try:
            assert TABLES <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert not other.exists()
    finally:
        get_settings.cache_clear()


_BATCH_REVISION = """
import sqlalchemy as sa
from alembic import op

revision = "9999_batch_probe"
down_revision = "0002_chosen_label"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", recreate="always") as b:
        b.add_column(sa.Column("probe", sa.Integer(), nullable=True))
"""


def test_batch_recreate_of_referenced_table(tmp_path):
    """A future SQLite batch migration that recreates ``users`` (DROP + rename) must work on a
    populated database: migrations must not run with ``PRAGMA foreign_keys=ON``."""
    url = _url(tmp_path / "a.db")
    migrate(url)
    engine = make_engine(url)
    try:
        with make_sessionmaker(engine)() as db:
            ensure_default_user(db)
            db.add(
                PuzzleRow(
                    user_id=DEFAULT_USER_ID,
                    seed=1,
                    street="flop",
                    profile="tag",
                    profile_version=1,
                    categories_version=1,
                    config_version=1,
                    format=1,
                    data=b"x",
                )
            )
            db.commit()
    finally:
        engine.dispose()

    extra = tmp_path / "versions"
    extra.mkdir()
    (extra / "9999_batch_probe.py").write_text(_BATCH_REVISION, encoding="utf-8")
    packaged = files("poker_trainer.db") / "migrations" / "versions"
    cfg = alembic_config(url)
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option("version_locations", os.pathsep.join([str(packaged), str(extra)]))
    command.upgrade(cfg, "head")

    engine = make_engine(url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("users")}
        assert "probe" in cols
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM puzzles").scalar() == 1
    finally:
        engine.dispose()


def test_chosen_label_backfilled(tmp_path):
    """0002 adds ``attempts.chosen_label`` and fills it from the stored ``chosen`` JSON."""
    url = _url(tmp_path / "a.db")
    command.upgrade(alembic_config(url), "0001_initial")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO users (id, name, created_at) VALUES (1, 'local', '2026-01-01')"
            )
            conn.exec_driver_sql(
                "INSERT INTO puzzles (id, user_id, created_at, seed, street, profile,"
                " profile_version, categories_version, config_version, format, data)"
                " VALUES (1, 1, '2026-01-01', 1, 'flop', 'tag', 1, 1, 1, 1, x'00')"
            )
            conn.exec_driver_sql(
                "INSERT INTO attempts (user_id, puzzle_id, attempt_no, is_first, created_at,"
                " action, equity_guess, verdict, action_kind, best_kind, ev_loss_chips,"
                " equity_error, equity_score, chosen, best_label, best_ev_chips,"
                " config_version) VALUES (1, 1, 1, 1, '2026-01-01', '{}', 0.5, 'best', 'bet',"
                " 'bet', 0, 0, 'great', '{\"label\": \"bet 33% \u2014 x\"}', 'bet', 0, 1)"
            )
    finally:
        engine.dispose()

    migrate(url)
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            label = conn.exec_driver_sql("SELECT chosen_label FROM attempts").scalar()
        assert label == "bet 33% \u2014 x"
        cols = {c["name"]: c for c in inspect(engine).get_columns("attempts")}
        assert cols["chosen_label"]["nullable"] is False
    finally:
        engine.dispose()
