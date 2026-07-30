"""Seed SEO content permissions into the registry.

The permission registry only auto-seeds from BASE_PERMISSION_REGISTRY_SEED when
the table is entirely empty, so adding entries to that constant has no effect on
an existing DB — the module would be invisible/locked in the sidebar. Every
table-creating migration must sync its own permissions (the B2B/CS lesson).

Revision ID: 20260729_11_seo_permissions
Revises: 20260729_10_craft_facts
Create Date: 2026-07-29
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_11_seo_permissions"
down_revision: str | Sequence[str] | None = "20260729_10_craft_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEO_PERMISSIONS = (
    {
        "permission_key": "seo.content.read",
        "module_key": "seo.content",
        "category": "business",
        "action": "read",
        "label": "Read SEO content",
        "description": "View the craft-fact library and SEO content queue.",
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "seo.content.execute",
        "module_key": "seo.content",
        "category": "business",
        "action": "execute",
        "label": "Generate SEO content",
        "description": "Run the keyword radar and generate SEO articles.",
        "risk_level": "medium",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "seo.content.manage",
        "module_key": "seo.content",
        "category": "business",
        "action": "manage",
        "label": "Manage SEO content",
        "description": (
            "Record and approve craft facts; approve or reject SEO articles."
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


def _sync_seo_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in SEO_PERMISSIONS:
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
    _sync_seo_permissions()


def downgrade() -> None:
    permission_keys = tuple(
        permission["permission_key"] for permission in SEO_PERMISSIONS
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
