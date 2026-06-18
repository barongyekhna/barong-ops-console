"""user module full upgrade and initial password policy

Revision ID: user_module_full_upgrade_001
Revises: fix_be_06_modules_me_perf_001
Create Date: 2026-06-18

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "user_module_full_upgrade_001"
down_revision: str | Sequence[str] | None = "fix_be_06_modules_me_perf_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {
        column["name"] for column in _inspector().get_columns(table_name)
    }


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in _inspector().get_indexes(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column(column_name)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


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
    if _column_exists("users", "must_change_password"):
        op.execute(sa.text("UPDATE users SET must_change_password = false"))
    _create_index_if_missing(
        "ix_users_organization_id",
        "users",
        ["organization_id"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_users_organization_id", "users")
    _drop_column_if_exists("users", "must_change_password")
    _drop_column_if_exists("users", "organization_id")
    _drop_column_if_exists("users", "job_title")
