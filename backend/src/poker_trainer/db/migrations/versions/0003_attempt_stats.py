"""Attempts: ``true_equity``, ``ahead_now`` and ``hero_category``, so stats never decode a blob.

Old rows are backfilled by decoding each attempt's puzzle once. A puzzle that can't be decoded
leaves its attempts' columns null (stats skip nulls). ``hero_category`` is only filled when the
puzzle was made with the live category thresholds (``stats.hero.hero_category``'s rule, and the
puzzle row's ``categories_version`` must agree with its blob): no approximate values are stored.
The backfill runs live app code (decoding, categories), so replaying it later may give other values.

Revision ID: 0003_attempt_stats
Revises: 0002_chosen_label
Create Date: 2026-11-12 10:00:00

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_attempt_stats"
down_revision: str | Sequence[str] | None = "0002_chosen_label"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH = 200

log = logging.getLogger(__name__)

_attempts = sa.table(
    "attempts",
    sa.column("id", sa.Integer()),
    sa.column("puzzle_id", sa.Integer()),
    sa.column("true_equity", sa.Double()),
    sa.column("ahead_now", sa.Double()),
    sa.column("hero_category", sa.String(16)),
)
_puzzles = sa.table(
    "puzzles",
    sa.column("id", sa.Integer()),
    sa.column("categories_version", sa.Integer()),
    sa.column("data", sa.LargeBinary()),
)

_Facts = tuple[float | None, float | None, str | None]
_NULLS: _Facts = (None, None, None)


def upgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("true_equity", sa.Double(), nullable=True))
        batch_op.add_column(sa.Column("ahead_now", sa.Double(), nullable=True))
        batch_op.add_column(sa.Column("hero_category", sa.String(length=16), nullable=True))

    # App code is imported here only, so loading the revision never needs it.
    from poker_trainer.db.blob import decode_puzzle
    from poker_trainer.stats.hero import hero_category

    conn = op.get_bind()
    facts: dict[int, _Facts] = {}

    def puzzle_facts(puzzle_id: int) -> _Facts:
        if puzzle_id in facts:
            return facts[puzzle_id]
        found = conn.execute(
            sa.select(_puzzles.c.categories_version, _puzzles.c.data).where(
                _puzzles.c.id == puzzle_id
            )
        ).first()
        out = _NULLS
        if found is not None:
            try:
                p = decode_puzzle(found.data)
                ahead = p.solution.ahead_now
                out = (
                    float(p.solution.equity),
                    None if ahead is None else float(ahead),
                    hero_category(p)
                    if found.categories_version == p.spot.categories_version
                    else None,
                )
            except Exception:  # noqa: BLE001 - one bad blob must not stop the upgrade
                log.warning(
                    "0003: puzzle %s can't be read; its attempts' stats stay null", puzzle_id
                )
                out = _NULLS
        facts[puzzle_id] = out
        return out

    last_id = 0
    while True:
        rows = conn.execute(
            sa.select(_attempts.c.id, _attempts.c.puzzle_id)
            .where(_attempts.c.id > last_id)
            .order_by(_attempts.c.id)
            .limit(BATCH)
        ).all()
        if not rows:
            break
        for row_id, puzzle_id in rows:
            values = puzzle_facts(puzzle_id)
            if values == _NULLS:
                continue  # nothing to write; the new columns are already null
            true_equity, ahead_now, category = values
            conn.execute(
                _attempts.update()
                .where(_attempts.c.id == row_id)
                .values(true_equity=true_equity, ahead_now=ahead_now, hero_category=category)
            )
        last_id = rows[-1][0]


def downgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("hero_category")
        batch_op.drop_column("ahead_now")
        batch_op.drop_column("true_equity")
