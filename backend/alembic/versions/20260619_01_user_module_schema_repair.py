"""safe user module schema repair

Revision ID: user_module_schema_repair_001
Revises: user_module_full_upgrade_001
Create Date: 2026-06-19

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "user_module_schema_repair_001"
down_revision: str | Sequence[str] | None = "user_module_full_upgrade_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing(
        "users",
        sa.Column("job_title", sa.String(length=255), nullable=True),
    )
    _add_column_if_missing(
        "users",
        sa.Column("organization_id", sa.String(length=40), nullable=True),
    )
    _add_column_if_missing(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    _add_column_if_missing(
        "users",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    _add_column_if_missing(
        "users",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    pass
