"""approval list performance indexes

Revision ID: approval_list_perf_001
Revises: approval_productization_001
Create Date: 2026-06-21

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "approval_list_perf_001"
down_revision: str | Sequence[str] | None = "approval_productization_001"
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
    _create_index_if_missing(
        "ix_approval_requests_org_id_status_created_at",
        "approval_requests",
        ["org_id", "status", "created_at"],
    )
    _create_index_if_missing(
        "ix_approval_requests_org_id_category_created_at",
        "approval_requests",
        ["org_id", "category", "created_at"],
    )
    _create_index_if_missing(
        "ix_approval_requests_org_id_category_status_created_at",
        "approval_requests",
        ["org_id", "category", "status", "created_at"],
    )
    _create_index_if_missing(
        "ix_approval_workflows_org_id_approval_id",
        "approval_workflows",
        ["org_id", "approval_id"],
    )


def downgrade() -> None:
    _drop_index_if_exists(
        "ix_approval_workflows_org_id_approval_id",
        "approval_workflows",
    )
    _drop_index_if_exists(
        "ix_approval_requests_org_id_category_status_created_at",
        "approval_requests",
    )
    _drop_index_if_exists(
        "ix_approval_requests_org_id_category_created_at",
        "approval_requests",
    )
    _drop_index_if_exists(
        "ix_approval_requests_org_id_status_created_at",
        "approval_requests",
    )
