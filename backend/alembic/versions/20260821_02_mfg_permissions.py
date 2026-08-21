"""Seed M-series (manufacturing inventory) permissions into the registry.

The permission registry only auto-seeds from BASE_PERMISSION_REGISTRY_SEED when
the table is entirely empty, so every table-creating migration must sync its own
permissions (the B2B/CS lesson). Note: for mfg.* the real gate is the role gate
in the router (owner + factory super_admin); these keys only satisfy the module
registry / sidebar contract.

Revision ID: 20260821_02_mfg_permissions
Revises: 20260821_01_mfg_inventory_tables
Create Date: 2026-08-21
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_02_mfg_permissions"
down_revision: str | Sequence[str] | None = "20260821_01_mfg_inventory_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MFG_PERMISSIONS = (
    {
        "permission_key": "mfg.inventory.read",
        "module_key": "mfg.inventory",
        "category": "business",
        "action": "read",
        "label": "Read manufacturing inventory",
        "description": (
            "View parts, finished goods, stock levels, BOMs and the "
            "movement ledger."
        ),
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "mfg.inventory.manage",
        "module_key": "mfg.inventory",
        "category": "business",
        "action": "manage",
        "label": "Manage manufacturing inventory",
        "description": (
            "Create items and BOMs; post receipts, production runs, "
            "shipments and stock adjustments."
        ),
        "risk_level": "medium",
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


def _sync_mfg_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in MFG_PERMISSIONS:
        permission_key = permission["permission_key"]
        existing = connection.scalar(
            sa.select(table.c.permission_key).where(
                table.c.permission_key == permission_key
            )
        )
        values = {**permission, "is_system": True, "is_enabled": True}
        if existing is None:
            connection.execute(table.insert().values(id=uuid4(), **values))
        else:
            connection.execute(
                table.update()
                .where(table.c.permission_key == permission_key)
                .values(**values)
            )


def upgrade() -> None:
    _sync_mfg_permissions()


def downgrade() -> None:
    permission_keys = tuple(
        permission["permission_key"] for permission in MFG_PERMISSIONS
    )
    for dependent_table in (
        "role_default_permissions",
        "user_permission_assignments",
    ):
        table = sa.table(
            dependent_table,
            sa.column("permission_key", sa.String()),
        )
        op.execute(
            table.delete().where(table.c.permission_key.in_(permission_keys))
        )
    permissions = _permission_registry_table()
    op.execute(
        permissions.delete().where(
            permissions.c.permission_key.in_(permission_keys)
        )
    )
