import os
from dataclasses import replace
from importlib.resources import files

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from poker_trainer.db import (
    DEFAULT_USER_ID,
    Base,
    PuzzleRow,
    alembic_config,
    encode_puzzle,
    ensure_default_user,
    make_engine,
    make_sessionmaker,
    migrate,
)
from poker_trainer.puzzle.generate import generate_puzzle
from poker_trainer.settings import get_settings
from poker_trainer.stats.hero import hero_category
from poker_trainer.villain.features import load_thresholds

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
        assert head == "0003_attempt_stats"
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
down_revision = "0003_attempt_stats"
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


_STATS_COLS = ("true_equity", "ahead_now", "hero_category")


def _insert_at_0002(conn, puzzle_id: int, data: bytes, categories_version: int, attempts: int):
    """A puzzle row and ``attempts`` attempts on it, written with the 0002 schema."""
    conn.execute(
        text(
            "INSERT INTO puzzles (id, user_id, created_at, seed, street, profile,"
            " profile_version, categories_version, config_version, format, data)"
            " VALUES (:id, 1, '2026-01-01', 1, 'flop', 'tag', 1, :cv, 1, 1, :data)"
        ),
        {"id": puzzle_id, "cv": categories_version, "data": data},
    )
    for no in range(1, attempts + 1):
        conn.execute(
            text(
                "INSERT INTO attempts (user_id, puzzle_id, attempt_no, is_first, created_at,"
                " action, equity_guess, verdict, action_kind, best_kind, ev_loss_chips,"
                " equity_error, equity_score, chosen, chosen_label, best_label, best_ev_chips,"
                " config_version) VALUES (1, :pid, :no, :first, '2026-01-01', '{}', 0.5, 'best',"
                " 'bet', 'bet', 0, 0, 'great', '{}', 'bet', 'bet', 0, 1)"
            ),
            {"pid": puzzle_id, "no": no, "first": no == 1},
        )


def test_attempt_stats_backfilled(tmp_path, monkeypatch):
    """0003 adds ``true_equity``, ``ahead_now`` and ``hero_category`` and fills them from each
    attempt's puzzle, decoding each puzzle once; a corrupt blob keeps nulls, and a puzzle made
    with other category thresholds gets no ``hero_category``."""
    flop = generate_puzzle(1, street="flop")
    river = generate_puzzle(1, street="river")
    current = load_thresholds().version
    stale = replace(flop, spot=replace(flop.spot, categories_version=current + 1))
    url = _url(tmp_path / "a.db")
    command.upgrade(alembic_config(url), "0002_chosen_label")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO users (id, name, created_at) VALUES (1, 'local', '2026-01-01')"
            )
            _insert_at_0002(conn, 1, encode_puzzle(flop), current, attempts=3)
            _insert_at_0002(conn, 2, encode_puzzle(river), current, attempts=1)
            _insert_at_0002(conn, 3, b"not a puzzle", current, attempts=2)
            _insert_at_0002(conn, 4, encode_puzzle(flop), current + 1, attempts=1)
            _insert_at_0002(conn, 5, encode_puzzle(stale), current + 1, attempts=1)
    finally:
        engine.dispose()

    from poker_trainer.db import blob

    decoded = []
    real = blob.decode_puzzle
    monkeypatch.setattr(blob, "decode_puzzle", lambda b: decoded.append(b) or real(b))

    migrate(url)
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT puzzle_id, true_equity, ahead_now, hero_category FROM attempts"
                    " ORDER BY id"
                )
            ).all()
        cols = {c["name"]: c for c in inspect(engine).get_columns("attempts")}
    finally:
        engine.dispose()

    assert len(decoded) == 5  # once per puzzle, not once per attempt
    by_puzzle = {pid: tuple(r) for pid, *r in rows}
    assert len(rows) == 8
    assert all(tuple(r[1:]) == by_puzzle[r[0]] for r in rows)
    flop_vals = (flop.solution.equity, flop.solution.ahead_now, hero_category(flop))
    assert by_puzzle[1] == flop_vals
    assert flop_vals[1] is not None and flop_vals[2] is not None
    assert by_puzzle[2] == (river.solution.equity, None, hero_category(river))
    assert by_puzzle[3] == (None, None, None)
    assert by_puzzle[4] == (flop.solution.equity, flop.solution.ahead_now, None)
    assert by_puzzle[5] == (flop.solution.equity, flop.solution.ahead_now, None)
    assert all(cols[c]["nullable"] for c in _STATS_COLS)


def test_attempt_stats_backfill_batches(tmp_path):
    """More attempts than one backfill batch are all filled."""
    flop = generate_puzzle(1, street="flop")
    url = _url(tmp_path / "a.db")
    command.upgrade(alembic_config(url), "0002_chosen_label")
    engine = make_engine(url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO users (id, name, created_at) VALUES (1, 'local', '2026-01-01')"
            )
            _insert_at_0002(conn, 1, encode_puzzle(flop), load_thresholds().version, 450)
    finally:
        engine.dispose()

    migrate(url)
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            missing = conn.exec_driver_sql(
                "SELECT count(*) FROM attempts WHERE true_equity IS NULL"
            ).scalar()
    finally:
        engine.dispose()
    assert missing == 0


def test_attempt_stats_downgrade(tmp_path):
    url = _url(tmp_path / "a.db")
    migrate(url)
    command.downgrade(alembic_config(url), "0002_chosen_label")
    engine = make_engine(url)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("attempts")}
    finally:
        engine.dispose()
    assert not cols & set(_STATS_COLS)
    assert "chosen_label" in cols
