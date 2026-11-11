"""Attempts: a ``chosen_label`` column, so history never reads the ``chosen`` JSON.

Revision ID: 0002_chosen_label
Revises: 0001_initial
Create Date: 2026-11-11 15:00:00

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_chosen_label"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_attempts = sa.table(
    "attempts",
    sa.column("id", sa.Integer()),
    sa.column("chosen", sa.JSON()),
    sa.column("chosen_label", sa.String(64)),
)


def upgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("chosen_label", sa.String(length=64), nullable=True))

    conn = op.get_bind()
    for row_id, chosen in conn.execute(sa.select(_attempts.c.id, _attempts.c.chosen)).all():
        if isinstance(chosen, str | bytes):  # a driver that hands JSON back undecoded
            chosen = json.loads(chosen)
        conn.execute(
            _attempts.update()
            .where(_attempts.c.id == row_id)
            .values(chosen_label=str(chosen["label"]))
        )

    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.alter_column("chosen_label", existing_type=sa.String(length=64), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_column("chosen_label")
