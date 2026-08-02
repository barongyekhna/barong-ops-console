"""Seed content-desk permissions into the registry.

The permission registry only auto-seeds from BASE_PERMISSION_REGISTRY_SEED when
the table is entirely empty, so adding entries to that constant has no effect on
an existing DB — the module would be invisible/locked in the sidebar. Every new
module must sync its own permissions (the B2B/CS/F/W lesson, four times over).

Revision ID: 20260802_01_content_desk_permissions
Revises: 20260731_01_content_link_settings
Create Date: 2026-08-02
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260802_01_content_desk_permissions"
down_revision: str | Sequence[str] | None = "20260731_01_content_link_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONTENT_DESK_PERMISSIONS = (
    {
        "permission_key": "content.desk.read",
        "module_key": "content.desk",
        "category": "business",
        "action": "read",
        "label": "Read content desk",
        "description": "View the unified review queue across GEO and SEO.",
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "content.desk.execute",
        "module_key": "content.desk",
        "category": "business",
        "action": "execute",
        "label": "Act in content desk",
        "description": (
            "Approve, reject, re-analyse and rewrite articles from the desk. "
            "Also requires the source engine's own permission."
        ),
        "risk_level": "medium",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "content.desk.manage",
        "module_key": "content.desk",
        "category": "business",
        "action": "manage",
        "label": "Manage content desk",
        "description": (
            "Override brand-audit findings and dispatch publishing. "
            "Also requires the source engine's own permission."
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


def _sync_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in CONTENT_DESK_PERMISSIONS:
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
        permission["permission_key"] for permission in CONTENT_DESK_PERMISSIONS
    )
    for dependent_table in (
        "role_default_permissions",
        "user_permission_assignments",
    ):
        table = sa.table(
            dependent_table,
            sa.column("permission_key", sa.String()),
        )
        op.execute(table.delete().where(table.c.permission_key.in_(permission_keys)))
    permissions = _permission_registry_table()
    op.execute(
        permissions.delete().where(
            permissions.c.permission_key.in_(permission_keys)
        )
    )
