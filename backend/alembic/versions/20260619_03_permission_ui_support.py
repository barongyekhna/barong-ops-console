"""permission ui support fields

Revision ID: permission_ui_support_001
Revises: force_pwd_owner_only_001
Create Date: 2026-06-19

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "permission_ui_support_001"
down_revision: str | Sequence[str] | None = "force_pwd_owner_only_001"
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


def upgrade() -> None:
    if not _column_exists("module_registry", "organization_id"):
        with op.batch_alter_table("module_registry") as batch_op:
            batch_op.add_column(
                sa.Column("organization_id", sa.String(length=40), nullable=True)
            )
    if not _index_exists("module_registry", "ix_module_registry_organization_id"):
        op.create_index(
            "ix_module_registry_organization_id",
            "module_registry",
            ["organization_id"],
        )


def downgrade() -> None:
    if _index_exists("module_registry", "ix_module_registry_organization_id"):
        op.drop_index(
            "ix_module_registry_organization_id",
            table_name="module_registry",
        )
    if _column_exists("module_registry", "organization_id"):
        with op.batch_alter_table("module_registry") as batch_op:
            batch_op.drop_column("organization_id")
