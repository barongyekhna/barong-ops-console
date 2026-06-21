"""force password reset owner-only bypass

Revision ID: force_pwd_owner_only_001
Revises: user_module_schema_repair_001
Create Date: 2026-06-19

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "force_pwd_owner_only_001"
down_revision: str | Sequence[str] | None = "user_module_schema_repair_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return False
    return column_name in {
        column["name"] for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    if not _column_exists("users", "must_change_password"):
        return
    op.execute(
        sa.text(
            """
            UPDATE users
            SET must_change_password = CASE
                WHEN lower(trim(role)) = 'owner' THEN false
                ELSE true
            END
            """
        )
    )


def downgrade() -> None:
    pass
