"""Seed the M-series cost-sheet permissions into the registry.

The permission registry only auto-seeds from BASE_PERMISSION_REGISTRY_SEED when
the table is entirely empty, so every table-creating migration must sync its own
permissions (the B2B/CS/F/W lesson).

These two keys are deliberately **not** the mfg.inventory ones.  Cost data is a
different class of secret from stock counts: it carries every supplier price and,
next to the factory price, the margin on every product.  Whoever can count boxes
in the warehouse should not automatically see what the company earns.

Revision ID: 20260911_02_mfg_cost_permissions
Revises: 20260911_01_mfg_cost_tables
Create Date: 2026-09-11
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_02_mfg_cost_permissions"
down_revision: str | Sequence[str] | None = "20260911_01_mfg_cost_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MFG_COST_PERMISSIONS = (
    {
        "permission_key": "mfg.cost.read",
        "module_key": "mfg.cost",
        "category": "business",
        "action": "read",
        "label": "查看出货成本明细",
        "description": (
            "View per-product cost sheets: material batch prices, inbound "
            "freight, labour, totals and margin. Separate from inventory "
            "access on purpose."
        ),
        "risk_level": "medium",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "mfg.cost.price",
        "module_key": "mfg.cost",
        "category": "business",
        "action": "manage",
        "label": "定出厂价与工价",
        "description": (
            "Set factory sale prices, labour rates and reference prices, and "
            "share cost sheets over C19. Implies mfg.cost.read."
        ),
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


def _sync_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in MFG_COST_PERMISSIONS:
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
    _sync_permissions()


def downgrade() -> None:
    permission_keys = tuple(
        permission["permission_key"] for permission in MFG_COST_PERMISSIONS
    )
    # 外键挡着,依赖表先清
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
