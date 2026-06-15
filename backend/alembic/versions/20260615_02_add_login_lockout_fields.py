"""add login lockout fields

Revision ID: c16_fix4_login_lockout_001
Revises: c16_auth_sessions_001
Create Date: 2026-06-15

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c16_fix4_login_lockout_001"
down_revision: str | Sequence[str] | None = "c16_auth_sessions_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_users_locked_until"),
        "users",
        ["locked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_locked_until"), table_name="users")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "last_failed_login_at")
    op.drop_column("users", "failed_login_count")
