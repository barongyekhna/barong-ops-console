"""Backfill org_id columns on OrgScoped tables that C18 add-column step missed

The c18_tenant_consistency_001 revision was supposed to add `org_id` (and the
tenant composite indexes) to every table in TENANT_TABLES via
`_add_tenant_columns_and_indexes`. In production only its CREATE TABLE half took
effect; the ALTER/add-column half never landed (an older build of the c18 file,
without the add-column logic, was the one actually executed — and since the
revision is already recorded as applied, alembic will never re-run it).

Result: models declaring `OrgScopedMixin` (SystemError, MemoryEvent,
MemorySummary, AgentMemoryAccessLog, OperationLog, AutomationJob, …) select an
`org_id` column that does not exist in prod, so any strict-isolation query
against them raises UndefinedColumn → the /errors and /memory-events pages 500.

This is a forward, idempotent repair migration. It does NOT touch the old c18
revision (touching an already-applied migration is what triggers the migration
safety-gate crash-loop). It simply (re)applies the c18 add-column + index logic,
guarded by `_column_exists`, so tables that already have `org_id` (e.g. the
approval_* tables) are skipped and only the missing ones are fixed.

Revision ID: 20260822_01_backfill_orgscoped_org_id
Revises: 20260821_03_factory_org_type
Create Date: 2026-08-22
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260822_01_backfill_orgscoped_org_id"
down_revision: str | Sequence[str] | None = "20260821_03_factory_org_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same fallback org that c18 used, so re-running is consistent with prior intent.
ROLLOUT_BACKFILL_ORG_ID = "org_00000000000000000000000000000000"

# Mirror of c18 TENANT_TABLES: {table: {status_col, module_col}} for index shape.
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
    return index_name in {
        index["name"] for index in _inspector().get_indexes(table_name)
    }


def _create_index_if_missing(
    index_name: str, table_name: str, columns: list[str]
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _add_created_at_if_missing(table_name: str) -> None:
    if _column_exists(table_name, "created_at"):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )


def _add_org_id_column(table_name: str) -> None:
    """Add org_id nullable, backfill to fallback org, then set NOT NULL.

    Identical shape to c18 `_add_org_id_column`, guarded by `_column_exists` so
    tables that already have the column are left untouched.
    """
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
                org_id, name, org_name, org_type, owner_user_id,
                status, metadata, created_at, updated_at
            )
            SELECT
                :org_id, 'C18 Rollout Backfill Org', 'C18 Rollout Backfill Org',
                'store', 'system', 'active', '{}',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            WHERE NOT EXISTS (
                SELECT 1 FROM organizations WHERE org_id = :org_id
            )
            """
        ).bindparams(org_id=ROLLOUT_BACKFILL_ORG_ID)
    )


def upgrade() -> None:
    # Fallback org must exist before any row is backfilled to it.
    _ensure_fallback_org()

    for table_name, index_spec in TENANT_TABLES.items():
        if not _table_exists(table_name):
            continue

        # c18 special-cased system_errors: it needs created_at before the
        # (org_id, created_at) index can be built.
        if table_name == "system_errors":
            _add_created_at_if_missing(table_name)

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


def downgrade() -> None:
    # No-op on purpose. These org_id columns are semantically owned by the c18
    # tenant-consistency migration (this revision only repairs c18's missed
    # add-column step). Dropping them here would remove columns other applied
    # migrations and the ORM depend on, so downgrade intentionally does nothing.
    pass
