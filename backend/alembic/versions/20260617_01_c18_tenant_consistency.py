"""C18 tenant consistency and DB-backed module bindings

Revision ID: c18_tenant_consistency_001
Revises: c16_adv_security_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "c18_tenant_consistency_001"
down_revision: str | Sequence[str] | None = "c16_adv_security_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLLOUT_BACKFILL_ORG_ID = "org_00000000000000000000000000000000"


def json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


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


def _inspector():
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
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)


def _add_required_text_column_from_source(
    table_name: str,
    column_name: str,
    source_column_name: str,
    *,
    length: int,
) -> None:
    if _column_exists(table_name, column_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(sa.Column(column_name, sa.String(length=length), nullable=True))
    op.execute(
        sa.text(
            f"UPDATE {table_name} "
            f"SET {column_name} = {source_column_name} "
            f"WHERE {column_name} IS NULL"
        )
    )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=sa.String(length=length),
            nullable=False,
        )


def _add_required_datetime_column_from_source(
    table_name: str,
    column_name: str,
    source_column_name: str,
) -> None:
    if _column_exists(table_name, column_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(
            sa.Column(
                column_name,
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            )
        )
    op.execute(
        sa.text(
            f"UPDATE {table_name} "
            f"SET {column_name} = {source_column_name} "
            f"WHERE {column_name} IS NULL"
        )
    )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            column_name,
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column(column_name)


def _add_org_id_column(table_name: str) -> None:
    if not _table_exists(table_name) or _column_exists(table_name, "org_id"):
        return

    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(
            sa.Column(
                "org_id",
                sa.String(length=40),
                server_default=ROLLOUT_BACKFILL_ORG_ID,
                nullable=True,
            )
        )
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET org_id = :org_id WHERE org_id IS NULL"
        ).bindparams(org_id=ROLLOUT_BACKFILL_ORG_ID)
    )
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column(
            "org_id",
            existing_type=sa.String(length=40),
            nullable=False,
            server_default=None,
        )


def _ensure_fallback_org() -> None:
    if not _table_exists("organizations"):
        return
    op.execute(
        sa.text(
            """
            INSERT INTO organizations (
                org_id,
                name,
                org_name,
                org_type,
                owner_user_id,
                status,
                metadata,
                created_at,
                updated_at
            )
            SELECT
                :org_id,
                'C18 Rollout Backfill Org',
                'C18 Rollout Backfill Org',
                'store',
                'system',
                'active',
                '{}',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM organizations WHERE org_id = :org_id
            )
            """
        ).bindparams(org_id=ROLLOUT_BACKFILL_ORG_ID)
    )


def _create_c18_tables() -> None:
    if not _table_exists("organizations"):
        op.create_table(
            "organizations",
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("org_name", sa.String(length=255), nullable=False),
            sa.Column("org_type", sa.String(length=50), nullable=False),
            sa.Column("owner_user_id", sa.String(length=255), nullable=False),
            sa.Column(
                "status",
                sa.String(length=50),
                server_default="active",
                nullable=False,
            ),
            sa.Column("metadata", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.CheckConstraint(
                "length(org_id) = 36 AND org_id LIKE 'org_%'",
                name=op.f("ck_organizations_organizations_org_id_format_valid"),
            ),
            sa.PrimaryKeyConstraint("org_id", name=op.f("pk_organizations")),
        )
    else:
        _add_required_text_column_from_source(
            "organizations",
            "name",
            "org_name",
            length=255,
        )
    _create_index_if_missing(
        "ix_organizations_org_id",
        "organizations",
        ["org_id"],
    )
    _create_index_if_missing(
        op.f("ix_organizations_owner_user_id"),
        "organizations",
        ["owner_user_id"],
    )
    _create_index_if_missing(
        op.f("ix_organizations_status"),
        "organizations",
        ["status"],
    )

    if not _table_exists("org_memberships"):
        op.create_table(
            "org_memberships",
            sa.Column("membership_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=255), nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default="active",
                nullable=False,
            ),
            sa.Column(
                "joined_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            created_at_column(),
            sa.CheckConstraint(
                "role IN ('owner', 'admin', 'member')",
                name=op.f("ck_org_memberships_org_memberships_role_valid"),
            ),
            sa.CheckConstraint(
                "status IN ('active', 'suspended')",
                name=op.f("ck_org_memberships_org_memberships_status_valid"),
            ),
            sa.CheckConstraint(
                "length(org_id) = 36 AND org_id LIKE 'org_%'",
                name=op.f("ck_org_memberships_org_memberships_org_id_format_valid"),
            ),
            sa.ForeignKeyConstraint(
                ["org_id"],
                ["organizations.org_id"],
                name=op.f("fk_org_memberships_org_id_organizations"),
            ),
            sa.PrimaryKeyConstraint(
                "membership_id",
                name=op.f("pk_org_memberships"),
            ),
            sa.UniqueConstraint(
                "user_id",
                "org_id",
                name="uq_org_memberships_user_id_org_id",
            ),
        )
    else:
        _add_required_datetime_column_from_source(
            "org_memberships",
            "created_at",
            "joined_at",
        )
    _create_index_if_missing(
        "ix_org_memberships_user_id_org_id",
        "org_memberships",
        ["user_id", "org_id"],
    )
    _create_index_if_missing(
        "ix_org_memberships_org_id",
        "org_memberships",
        ["org_id"],
    )
    _create_index_if_missing(
        "ix_org_memberships_org_id_status",
        "org_memberships",
        ["org_id", "status"],
    )

    if not _table_exists("module_bindings"):
        op.create_table(
            "module_bindings",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=68), nullable=False),
            sa.Column("module_id", sa.String(length=128), nullable=False),
            sa.Column(
                "status",
                sa.String(length=50),
                server_default="enabled",
                nullable=False,
            ),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_module_bindings")),
            sa.UniqueConstraint(
                "org_id",
                "module_id",
                name="uq_module_bindings_org_id_module_id",
            ),
        )
    _create_index_if_missing("ix_module_bindings_org_id", "module_bindings", ["org_id"])
    _create_index_if_missing(
        "ix_module_bindings_org_id_status",
        "module_bindings",
        ["org_id", "status"],
    )
    _create_index_if_missing(
        "ix_module_bindings_org_id_module_id",
        "module_bindings",
        ["org_id", "module_id"],
    )

    if not _table_exists("shared_modules"):
        op.create_table(
            "shared_modules",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("source_org_id", sa.String(length=68), nullable=False),
            sa.Column("target_org_id", sa.String(length=68), nullable=False),
            sa.Column("module_id", sa.String(length=128), nullable=False),
            sa.Column("mode", sa.String(length=50), nullable=False),
            sa.Column(
                "status",
                sa.String(length=50),
                server_default="enabled",
                nullable=False,
            ),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_shared_modules")),
            sa.UniqueConstraint(
                "source_org_id",
                "target_org_id",
                "module_id",
                name="uq_shared_modules_source_target_module",
            ),
        )
    _create_index_if_missing(
        "ix_shared_modules_source_org_id",
        "shared_modules",
        ["source_org_id"],
    )
    _create_index_if_missing(
        "ix_shared_modules_target_org_id",
        "shared_modules",
        ["target_org_id"],
    )
    _create_index_if_missing(
        "ix_shared_modules_target_org_id_module_id",
        "shared_modules",
        ["target_org_id", "module_id"],
    )
    _create_index_if_missing(
        "ix_shared_modules_module_id",
        "shared_modules",
        ["module_id"],
    )


TENANT_TABLES: dict[str, dict[str, str | None]] = {
    "automation_jobs": {"status": "status", "module": "module_id"},
    "job_events": {"status": None, "module": None},
    "artifacts": {"status": "status", "module": "module_id"},
    "review_items": {"status": "status", "module": None},
    "approval_requests": {"status": "status", "module": "module_key"},
    "approval_workflows": {"status": "state", "module": None},
    "approval_decisions": {"status": "status", "module": None},
    "operation_logs": {"status": None, "module": None},
    "memory_events": {"status": None, "module": None},
    "memory_summaries": {"status": None, "module": None},
    "agent_memory_access_logs": {"status": "result", "module": None},
    "system_errors": {"status": "status", "module": "module_id"},
    "context_packets": {"status": None, "module": "source_module_id"},
}


def _add_tenant_columns_and_indexes() -> None:
    for table_name, index_spec in TENANT_TABLES.items():
        if not _table_exists(table_name):
            continue
        if table_name == "system_errors":
            _add_column_if_missing(table_name, created_at_column())

        _add_org_id_column(table_name)
        _create_index_if_missing(f"ix_{table_name}_org_id", table_name, ["org_id"])

        if _column_exists(table_name, "created_at"):
            _create_index_if_missing(
                f"ix_{table_name}_org_id_created_at",
                table_name,
                ["org_id", "created_at"],
            )

        status_column = index_spec["status"]
        if status_column is not None and _column_exists(table_name, status_column):
            _create_index_if_missing(
                f"ix_{table_name}_org_id_{status_column}",
                table_name,
                ["org_id", status_column],
            )

        module_column = index_spec["module"]
        if module_column is not None and _column_exists(table_name, module_column):
            _create_index_if_missing(
                f"ix_{table_name}_org_id_{module_column}",
                table_name,
                ["org_id", module_column],
            )


def upgrade() -> None:
    _create_c18_tables()
    _ensure_fallback_org()
    _add_tenant_columns_and_indexes()


def downgrade() -> None:
    for table_name, index_spec in reversed(TENANT_TABLES.items()):
        if not _table_exists(table_name):
            continue
        module_column = index_spec["module"]
        if module_column is not None:
            _drop_index_if_exists(
                f"ix_{table_name}_org_id_{module_column}",
                table_name,
            )
        status_column = index_spec["status"]
        if status_column is not None:
            _drop_index_if_exists(
                f"ix_{table_name}_org_id_{status_column}",
                table_name,
            )
        _drop_index_if_exists(f"ix_{table_name}_org_id_created_at", table_name)
        _drop_index_if_exists(f"ix_{table_name}_org_id", table_name)
        _drop_column_if_exists(table_name, "org_id")
        if table_name == "system_errors":
            _drop_column_if_exists(table_name, "created_at")

    if _table_exists("shared_modules"):
        _drop_index_if_exists("ix_shared_modules_module_id", "shared_modules")
        _drop_index_if_exists(
            "ix_shared_modules_target_org_id_module_id",
            "shared_modules",
        )
        _drop_index_if_exists("ix_shared_modules_target_org_id", "shared_modules")
        _drop_index_if_exists("ix_shared_modules_source_org_id", "shared_modules")
        op.drop_table("shared_modules")

    if _table_exists("module_bindings"):
        _drop_index_if_exists(
            "ix_module_bindings_org_id_module_id",
            "module_bindings",
        )
        _drop_index_if_exists("ix_module_bindings_org_id_status", "module_bindings")
        _drop_index_if_exists("ix_module_bindings_org_id", "module_bindings")
        op.drop_table("module_bindings")

    if _table_exists("org_memberships"):
        _drop_index_if_exists("ix_org_memberships_org_id_status", "org_memberships")
        _drop_index_if_exists("ix_org_memberships_org_id", "org_memberships")
        _drop_index_if_exists(
            "ix_org_memberships_user_id_org_id",
            "org_memberships",
        )
        op.drop_table("org_memberships")

    if _table_exists("organizations"):
        _drop_index_if_exists("ix_organizations_org_id", "organizations")
        _drop_index_if_exists("ix_organizations_status", "organizations")
        _drop_index_if_exists("ix_organizations_owner_user_id", "organizations")
        op.drop_table("organizations")
