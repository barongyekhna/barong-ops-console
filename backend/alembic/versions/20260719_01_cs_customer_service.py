"""CS customer-service inbox.

Revision ID: 20260719_01_cs_customer_service
Revises: 20260718_01_k_category_spec_templates
Create Date: 2026-07-19
"""

from collections.abc import Sequence
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260719_01_cs_customer_service"
down_revision: str | Sequence[str] | None = (
    "20260718_01_k_category_spec_templates"
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "cs_messages"
TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
CS_PERMISSIONS = (
    {
        "permission_key": "cs.customer_service.read",
        "module_key": "cs.customer_service",
        "category": "business",
        "action": "read",
        "label": "Read customer-service messages",
        "description": "View retail contacts and wholesale inquiries.",
        "risk_level": "low",
        "menu_policy": "show_locked",
    },
    {
        "permission_key": "cs.customer_service.update",
        "module_key": "cs.customer_service",
        "category": "business",
        "action": "update",
        "label": "Update customer-service messages",
        "description": "Update message status and internal notes.",
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


def _sync_cs_permissions() -> None:
    table = _permission_registry_table()
    connection = op.get_bind()
    for permission in CS_PERMISSIONS:
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
            connection.execute(
                table.insert().values(id=uuid4(), **values)
            )
        else:
            connection.execute(
                table.update()
                .where(table.c.permission_key == permission_key)
                .values(**values)
            )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("workspace_key", sa.String(length=128), nullable=False),
        sa.Column(
            "business_context",
            sa.String(length=128),
            nullable=False,
            server_default="independent_store",
        ),
        sa.Column(
            "scope_mode",
            sa.String(length=64),
            nullable=False,
            server_default="production",
        ),
        sa.Column(
            "organization_name",
            sa.String(length=255),
            nullable=False,
            server_default=TARGET_ORGANIZATION_NAME,
        ),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="new",
        ),
        sa.Column("internal_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "channel IN ('retail', 'wholesale')",
            name="ck_cs_messages_valid_channel",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved', 'spam')",
            name="ck_cs_messages_valid_status",
        ),
        sa.CheckConstraint(
            "length(message) BETWEEN 1 AND 5000",
            name="ck_cs_messages_message_length",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cs_messages"),
    )
    op.create_index(
        "ix_cs_messages_channel_status_created",
        TABLE,
        ["channel", "status", "created_at"],
    )
    op.create_index(
        "ix_cs_messages_org_channel_created",
        TABLE,
        ["org_id", "channel", "created_at"],
    )
    _sync_cs_permissions()


def downgrade() -> None:
    permission_keys = tuple(
        permission["permission_key"] for permission in CS_PERMISSIONS
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
    op.drop_index("ix_cs_messages_org_channel_created", table_name=TABLE)
    op.drop_index("ix_cs_messages_channel_status_created", table_name=TABLE)
    op.drop_table(TABLE)
