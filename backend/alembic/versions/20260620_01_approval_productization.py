"""approval productization fields

Revision ID: approval_productization_001
Revises: permission_ui_support_001
Create Date: 2026-06-20

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "approval_productization_001"
down_revision: str | Sequence[str] | None = "permission_ui_support_001"
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
    if not _table_exists("approval_requests"):
        return

    if not _column_exists("approval_requests", "category"):
        with op.batch_alter_table("approval_requests") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "category",
                    sa.String(length=50),
                    server_default="feature",
                    nullable=True,
                )
            )

        op.execute(
            sa.text(
                """
                UPDATE approval_requests
                SET category = CASE
                    WHEN lower(module_key) LIKE 'c%' THEN 'control_plane'
                    WHEN lower(module_key) LIKE 'admin.%' THEN 'control_plane'
                    WHEN lower(module_key) LIKE 'system.%' THEN 'control_plane'
                    WHEN lower(action_key) LIKE '%permission%' THEN 'control_plane'
                    WHEN lower(action_key) LIKE '%module%' THEN 'control_plane'
                    ELSE 'feature'
                END
                WHERE category IS NULL OR category = 'feature'
                """
            )
        )

        with op.batch_alter_table("approval_requests") as batch_op:
            batch_op.alter_column(
                "category",
                existing_type=sa.String(length=50),
                nullable=False,
                server_default="feature",
            )

    _create_index_if_missing(
        "ix_approval_requests_org_id_category_status",
        "approval_requests",
        ["org_id", "category", "status"],
    )


def downgrade() -> None:
    if not _table_exists("approval_requests"):
        return
    _drop_index_if_exists(
        "ix_approval_requests_org_id_category_status",
        "approval_requests",
    )
    if _column_exists("approval_requests", "category"):
        with op.batch_alter_table("approval_requests") as batch_op:
            batch_op.drop_column("category")
