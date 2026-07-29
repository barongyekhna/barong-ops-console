"""Seed B2B wholesale permissions into the registry.

上一条迁移(20260727_01)只建了表,漏了权限落库——而权限注册表只在"整个
为空"时才从种子常量重新灌一次,所以往 BASE_PERMISSION_REGISTRY_SEED 里
加条目对已有数据库完全无效,模块会在侧边栏隐身。CS 系列的迁移是对的写法:
建表的迁移必须同时同步自己的权限。这里补上。

Revision ID: 20260727_02_b2b_permissions
Revises: 20260727_01_b2b_wholesale_items
Create Date: 2026-07-27
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260727_02_b2b_permissions"
down_revision: str | Sequence[str] | None = "20260727_01_b2b_wholesale_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

B2B_PERMISSIONS = (
    {
        "permission_key": "b2b.wholesale.read",
        "module_key": "b2b.wholesale",
        "category": "business",
        "action": "read",
        "label": "Read wholesale catalogue",
        "description": (
            "View wholesale items, pricing readiness, and line sheets."
        ),
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "b2b.wholesale.manage",
        "module_key": "b2b.wholesale",
        "category": "business",
        "action": "manage",
        "label": "Manage wholesale catalogue",
        "description": (
            "Set wholesale prices, MOQ, case pack, and lead times."
        ),
        "risk_level": "medium",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "b2b.wholesale.export",
        "module_key": "b2b.wholesale",
        "category": "business",
        "action": "export",
        "label": "Export wholesale line sheets",
        "description": (
            "Generate PDF or CSV line sheets for outbound buyers."
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


def _sync_b2b_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in B2B_PERMISSIONS:
        permission_key = permission["permission_key"]
        existing = connection.scalar(
            sa.select(table.c.permission_key).where(
                table.c.permission_key == permission_key
            )
        )
        values = {
            **permission,
            "is_system": True,
            "is_enabled": True,
        }
        if existing is None:
            connection.execute(table.insert().values(id=uuid4(), **values))
        else:
            connection.execute(
                table.update()
                .where(table.c.permission_key == permission_key)
                .values(**values)
            )


def upgrade() -> None:
    _sync_b2b_permissions()


def downgrade() -> None:
    permission_keys = tuple(
        permission["permission_key"] for permission in B2B_PERMISSIONS
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
