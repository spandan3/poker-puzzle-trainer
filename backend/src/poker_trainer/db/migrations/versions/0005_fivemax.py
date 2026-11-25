"""5-max play: table size, per-seat snapshots, pots and the show-range setting.

``play_sessions.table_size`` (2 or 5) and ``seats`` (5-max only: one dict per bot seat,
``{"seat", "name", "stack", "bot": SeatBot.to_dict()}``). In a 5-max session the legacy
``profile``, ``profile_version`` and ``profile_data`` hold Bot 1's snapshot and ``bot_stack`` is 0.
``play_hands.table_size``, ``pots`` and ``bot_versions``. ``user_settings.show_range``.
Existing heads-up rows get the defaults.

Revision ID: 0005_fivemax
Revises: 0004_play
Create Date: 2026-11-25 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_fivemax"
down_revision: str | Sequence[str] | None = "0004_play"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("play_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("table_size", sa.Integer(), nullable=False, server_default="2")
        )
        batch_op.add_column(sa.Column("seats", sa.JSON(), nullable=True))
    with op.batch_alter_table("play_hands", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("table_size", sa.Integer(), nullable=False, server_default="2")
        )
        batch_op.add_column(sa.Column("pots", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("bot_versions", sa.JSON(), nullable=True))
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("show_range", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("user_settings", schema=None) as batch_op:
        batch_op.drop_column("show_range")
    with op.batch_alter_table("play_hands", schema=None) as batch_op:
        batch_op.drop_column("bot_versions")
        batch_op.drop_column("pots")
        batch_op.drop_column("table_size")
    with op.batch_alter_table("play_sessions", schema=None) as batch_op:
        batch_op.drop_column("seats")
        batch_op.drop_column("table_size")
