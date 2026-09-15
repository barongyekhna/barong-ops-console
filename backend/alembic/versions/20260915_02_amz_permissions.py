"""Seed A-series (Amazon operations, amz.ops) permissions into the registry.

The permission registry only auto-seeds from BASE_PERMISSION_REGISTRY_SEED when
the table is entirely empty, so every table-creating migration must sync its own
permissions (the B2B/CS lesson).

Revision ID: 20260915_02_amz_permissions
Revises: 20260915_01_amz_tables
Create Date: 2026-09-15
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_02_amz_permissions"
down_revision: str | Sequence[str] | None = "20260915_01_amz_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AMZ_PERMISSIONS = (
    {
        "permission_key": "amz.ops.read",
        "module_key": "amz.ops",
        "category": "business",
        "action": "read",
        "label": "Read Amazon operations",
        "description": "View stores, employees, suggestions and imported reports.",
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "amz.ops.execute",
        "module_key": "amz.ops",
        "category": "business",
        "action": "execute",
        "label": "Run Amazon operations",
        "description": "Approve or reject suggestions, run imports, operate a store.",
        "risk_level": "medium",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "amz.ops.manage",
        "module_key": "amz.ops",
        "category": "business",
        "action": "manage",
        "label": "Manage Amazon operations",
        "description": "Grant store access, edit guardrails and ladder levels.",
        "risk_level": "high",
        "menu_policy": "show_locked",
    },
)


def _permission_registry_table() -> sa.TableClause:
    return sa.table(
        "permission_registry",
        sa.column("id", sa.Uuid()),
        sa.column("permission_key", sa.String()),
        sa.column("module_key", sa.String()),
        sa.column("category", sa.String()),
        sa.column("action", sa.String()),
        sa.column("label", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("risk_level", sa.String()),
        sa.column("menu_policy", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_enabled", sa.Boolean()),
    )


def _sync_amz_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in AMZ_PERMISSIONS:
        permission_key = permission["permission_key"]
        existing = connection.scalar(
            sa.select(table.c.permission_key).where(table.c.permission_key == permission_key)
        )
        values = {**permission, "is_system": True, "is_enabled": True}
        if existing is None:
            connection.execute(table.insert().values(id=uuid4(), **values))
        else:
            connection.execute(
                table.update().where(table.c.permission_key == permission_key).values(**values)
            )


def upgrade() -> None:
    _sync_amz_permissions()


def downgrade() -> None:
    permission_keys = tuple(permission["permission_key"] for permission in AMZ_PERMISSIONS)
    for dependent_table in ("role_default_permissions", "user_permission_assignments"):
        table = sa.table(dependent_table, sa.column("permission_key", sa.String()))
        op.execute(table.delete().where(table.c.permission_key.in_(permission_keys)))
    permissions = _permission_registry_table()
    op.execute(permissions.delete().where(permissions.c.permission_key.in_(permission_keys)))
