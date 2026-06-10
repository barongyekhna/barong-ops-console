"""create permission tables

Revision ID: c05b_permissions_001
Revises: f07_core_001
Create Date: 2026-06-10

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c05b_permissions_001"
down_revision: str | Sequence[str] | None = "f07_core_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def uuid_pk_column() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "permission_registry",
        uuid_pk_column(),
        sa.Column("permission_key", sa.String(length=255), nullable=False),
        sa.Column("module_key", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "risk_level",
            sa.String(length=50),
            server_default="low",
            nullable=False,
        ),
        sa.Column(
            "menu_policy",
            sa.String(length=50),
            server_default="hide_when_denied",
            nullable=False,
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_permission_registry_valid_risk_level"),
        ),
        sa.CheckConstraint(
            "menu_policy IN ('show_locked', 'hide_when_denied')",
            name=op.f("ck_permission_registry_valid_menu_policy"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permission_registry")),
        sa.UniqueConstraint(
            "permission_key",
            name=op.f("uq_permission_registry_permission_key"),
        ),
    )

    op.create_table(
        "user_permission_assignments",
        uuid_pk_column(),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_key", sa.String(length=255), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=50),
            server_default="global",
            nullable=False,
        ),
        sa.Column(
            "scope_key",
            sa.String(length=255),
            server_default="*",
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "scope_type IN ("
            "'global', 'company', 'factory', 'department', "
            "'organization', 'module'"
            ")",
            name=op.f("ck_user_permission_assignments_valid_scope_type"),
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f(
                "fk_user_permission_assignments_granted_by_user_id_users"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["permission_key"],
            ["permission_registry.permission_key"],
            name=op.f(
                "fk_user_permission_assignments_permission_key_permission_registry"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_permission_assignments_user_id_users"),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_user_permission_assignments"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "permission_key",
            "scope_type",
            "scope_key",
            name=op.f(
                "uq_user_permission_assignments_user_permission_scope"
            ),
        ),
    )

    op.create_table(
        "role_default_permissions",
        uuid_pk_column(),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("permission_key", sa.String(length=255), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(length=50),
            server_default="global",
            nullable=False,
        ),
        sa.Column(
            "scope_key",
            sa.String(length=255),
            server_default="*",
            nullable=False,
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "scope_type IN ("
            "'global', 'company', 'factory', 'department', "
            "'organization', 'module'"
            ")",
            name=op.f("ck_role_default_permissions_valid_scope_type"),
        ),
        sa.ForeignKeyConstraint(
            ["permission_key"],
            ["permission_registry.permission_key"],
            name=op.f(
                "fk_role_default_permissions_permission_key_permission_registry"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_role_default_permissions"),
        ),
        sa.UniqueConstraint(
            "role",
            "permission_key",
            "scope_type",
            "scope_key",
            name=op.f("uq_role_default_permissions_role_permission_scope"),
        ),
    )


def downgrade() -> None:
    op.drop_table("role_default_permissions")
    op.drop_table("user_permission_assignments")
    op.drop_table("permission_registry")
