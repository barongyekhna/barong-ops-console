"""FIX-BE-06 modules/me query indexes

Revision ID: fix_be_06_modules_me_perf_001
Revises: pre20_q_live_enable_gate_001
Create Date: 2026-06-18

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "fix_be_06_modules_me_perf_001"
down_revision: str | Sequence[str] | None = "pre20_q_live_enable_gate_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in _inspector().get_indexes(table_name)
    }


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _create_index(
        "ix_permission_registry_enabled_category",
        "permission_registry",
        ["is_enabled", "category"],
    )
    _create_index(
        "ix_user_permission_assignments_user_enabled_expires",
        "user_permission_assignments",
        ["user_id", "is_enabled", "expires_at"],
    )
    _create_index(
        "ix_user_permission_assignments_user_scope",
        "user_permission_assignments",
        ["user_id", "scope_type", "scope_key"],
    )


def downgrade() -> None:
    _drop_index(
        "ix_user_permission_assignments_user_scope",
        "user_permission_assignments",
    )
    _drop_index(
        "ix_user_permission_assignments_user_enabled_expires",
        "user_permission_assignments",
    )
    _drop_index(
        "ix_permission_registry_enabled_category",
        "permission_registry",
    )
