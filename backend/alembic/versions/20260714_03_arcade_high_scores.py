"""Add organization-scoped console arcade high scores.

Revision ID: 20260714_03_arcade_high_scores
Revises: 20260714_02_f_candidate_compare
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_03_arcade_high_scores"
down_revision: str | Sequence[str] | None = "20260714_02_f_candidate_compare"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "arcade_high_scores"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("game_id", sa.String(length=32), nullable=False),
        sa.Column("score", sa.BigInteger(), nullable=False),
        sa.Column("holder_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username_snapshot", sa.String(length=255), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "game_id IN ('shmup', 'snake', 'tetris', 'tank', 'asteroids', "
            "'breakout', '2048', 'runner', 'match3', 'mines', 'flappy', "
            "'pong')",
            name=op.f("ck_arcade_high_scores_game_id_allowed"),
        ),
        sa.CheckConstraint(
            "score >= 0",
            name=op.f("ck_arcade_high_scores_score_non_negative"),
        ),
        sa.CheckConstraint(
            "score <= 9007199254740991",
            name=op.f("ck_arcade_high_scores_score_safe_integer_max"),
        ),
        sa.ForeignKeyConstraint(
            ["holder_user_id"],
            ["users.id"],
            name=op.f("fk_arcade_high_scores_holder_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_arcade_high_scores")),
        sa.UniqueConstraint(
            "org_id",
            "game_id",
            name="uq_arcade_high_scores_org_id_game_id",
        ),
    )
    op.create_index(
        op.f("ix_arcade_high_scores_org_id"),
        TABLE,
        ["org_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_arcade_high_scores_org_id"), table_name=TABLE)
    op.drop_table(TABLE)
