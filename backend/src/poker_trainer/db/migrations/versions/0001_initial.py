"""Initial schema: users, user_settings, puzzles, attempts.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-11 11:40:26.582233

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("name", name=op.f("uq_users_name")),
    )
    op.create_table(
        "puzzles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("street", sa.String(length=8), nullable=False),
        sa.Column("profile", sa.String(length=16), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("categories_version", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("format", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_puzzles_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_puzzles")),
    )
    with op.batch_alter_table("puzzles", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_puzzles_user_id"), ["user_id"], unique=False)

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("show_pot_odds", sa.Boolean(), nullable=False),
        sa.Column("show_profile", sa.Boolean(), nullable=False),
        sa.Column("profile", sa.String(length=16), nullable=True),
        sa.Column("daily_goal", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_settings_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_settings")),
    )
    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("puzzle_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("is_first", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=True),
        sa.Column("custom_to", sa.Integer(), nullable=True),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("equity_guess", sa.Double(), nullable=False),
        sa.Column("range_read_guess", sa.Double(), nullable=True),
        sa.Column("intent", sa.String(length=16), nullable=True),
        sa.Column("verdict", sa.String(length=8), nullable=False),
        sa.Column("action_kind", sa.String(length=8), nullable=False),
        sa.Column("best_kind", sa.String(length=8), nullable=False),
        sa.Column("ev_loss_chips", sa.Double(), nullable=False),
        sa.Column("equity_error", sa.Double(), nullable=False),
        sa.Column("equity_score", sa.String(length=8), nullable=False),
        sa.Column("range_read_error", sa.Double(), nullable=True),
        sa.Column("range_read_score", sa.String(length=8), nullable=True),
        sa.Column("intent_truth", sa.String(length=16), nullable=True),
        sa.Column("intent_flag", sa.Text(), nullable=True),
        sa.Column("bluff_required", sa.Double(), nullable=True),
        sa.Column("bluff_actual", sa.Double(), nullable=True),
        sa.Column("chosen", sa.JSON(), nullable=False),
        sa.Column("best_label", sa.String(length=64), nullable=False),
        sa.Column("best_ev_chips", sa.Double(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["puzzle_id"], ["puzzles.id"], name=op.f("fk_attempts_puzzle_id_puzzles")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_attempts_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
        sa.UniqueConstraint(
            "puzzle_id", "attempt_no", name=op.f("uq_attempts_puzzle_id_attempt_no")
        ),
    )
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_attempts_action_kind"), ["action_kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_attempts_puzzle_id"), ["puzzle_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_attempts_user_id"), ["user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_attempts_verdict"), ["verdict"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attempts_verdict"))
        batch_op.drop_index(batch_op.f("ix_attempts_user_id"))
        batch_op.drop_index(batch_op.f("ix_attempts_puzzle_id"))
        batch_op.drop_index(batch_op.f("ix_attempts_action_kind"))

    op.drop_table("attempts")
    op.drop_table("user_settings")
    with op.batch_alter_table("puzzles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_puzzles_user_id"))

    op.drop_table("puzzles")
    op.drop_table("users")
