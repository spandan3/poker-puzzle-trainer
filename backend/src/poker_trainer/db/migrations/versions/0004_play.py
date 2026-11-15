"""Play vs Bots: ``play_sessions``, ``play_hands`` and ``play_decisions``.

A partial unique index on ``play_sessions.user_id`` (where ``ended_at IS NULL``) allows one open
session per user. A hand is unique per ``(session_id, hand_no)`` and a decision per
``(hand_id, n)``.

Revision ID: 0004_play
Revises: 0003_attempt_stats
Create Date: 2026-11-14 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_play"
down_revision: str | Sequence[str] | None = "0003_attempt_stats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "play_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile", sa.String(length=16), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("profile_data", sa.JSON(), nullable=False),
        sa.Column("hero_stack", sa.Integer(), nullable=False),
        sa.Column("bot_stack", sa.Integer(), nullable=False),
        sa.Column("hero_bought_chips", sa.Integer(), nullable=False),
        sa.Column("next_button", sa.Integer(), nullable=False),
        sa.Column("hands_played", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_play_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_play_sessions")),
    )
    with op.batch_alter_table("play_sessions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_play_sessions_user_id"), ["user_id"], unique=False)
        batch_op.create_index(
            "uq_play_sessions_open_user",
            ["user_id"],
            unique=True,
            sqlite_where=sa.text("ended_at IS NULL"),
            postgresql_where=sa.text("ended_at IS NULL"),
        )

    op.create_table(
        "play_hands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("hand_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("button", sa.Integer(), nullable=False),
        sa.Column("start_stacks", sa.JSON(), nullable=False),
        sa.Column("deck", sa.JSON(), nullable=False),
        sa.Column("bot_seed", sa.BigInteger(), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("action_count", sa.Integer(), nullable=False),
        sa.Column("abandoned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("ended_by", sa.String(length=12), nullable=True),
        sa.Column("winner", sa.String(length=8), nullable=True),
        sa.Column("hero_delta_chips", sa.Integer(), nullable=True),
        sa.Column("decision_count", sa.Integer(), nullable=False),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("categories_version", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("ev_loss_chips", sa.Double(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["play_sessions.id"],
            name=op.f("fk_play_hands_session_id_play_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_play_hands_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_play_hands")),
        sa.UniqueConstraint("session_id", "hand_no", name=op.f("uq_play_hands_session_id_hand_no")),
    )
    with op.batch_alter_table("play_hands", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_play_hands_session_id"), ["session_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_play_hands_user_id"), ["user_id"], unique=False)

    op.create_table(
        "play_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hand_id", sa.Integer(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("puzzle", sa.LargeBinary(), nullable=True),
        sa.Column("chosen", sa.JSON(), nullable=True),
        sa.Column("custom_to", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=8), nullable=True),
        sa.Column("ev_loss_chips", sa.Double(), nullable=True),
        sa.Column("best_label", sa.String(length=64), nullable=True),
        sa.Column("best_ev_chips", sa.Double(), nullable=True),
        sa.Column("intent_truth", sa.String(length=16), nullable=True),
        sa.Column("bluff_required", sa.Double(), nullable=True),
        sa.Column("bluff_actual", sa.Double(), nullable=True),
        sa.Column("strategy_version", sa.Integer(), nullable=False),
        sa.Column("categories_version", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["hand_id"], ["play_hands.id"], name=op.f("fk_play_decisions_hand_id_play_hands")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_play_decisions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_play_decisions")),
        sa.UniqueConstraint("hand_id", "n", name=op.f("uq_play_decisions_hand_id_n")),
    )
    with op.batch_alter_table("play_decisions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_play_decisions_hand_id"), ["hand_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_play_decisions_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("play_decisions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_play_decisions_user_id"))
        batch_op.drop_index(batch_op.f("ix_play_decisions_hand_id"))
    op.drop_table("play_decisions")
    with op.batch_alter_table("play_hands", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_play_hands_user_id"))
        batch_op.drop_index(batch_op.f("ix_play_hands_session_id"))
    op.drop_table("play_hands")
    with op.batch_alter_table("play_sessions", schema=None) as batch_op:
        batch_op.drop_index("uq_play_sessions_open_user")
        batch_op.drop_index(batch_op.f("ix_play_sessions_user_id"))
    op.drop_table("play_sessions")
