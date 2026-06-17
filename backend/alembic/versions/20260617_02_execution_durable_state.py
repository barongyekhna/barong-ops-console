"""Execution durable state tables

Revision ID: execution_durable_state_001
Revises: c18_tenant_consistency_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "execution_durable_state_001"
down_revision: str | Sequence[str] | None = "c18_tenant_consistency_001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _table_exists(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    if table_name in inspect(op.get_bind()).get_table_names():
        existing = {
            index["name"]
            for index in inspect(op.get_bind()).get_indexes(table_name)
        }
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("execution_callbacks"):
        op.create_table(
            "execution_callbacks",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("callback_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("execution_id", sa.String(length=128), nullable=True),
            sa.Column("module_key", sa.String(length=128), nullable=False),
            sa.Column("workflow_id", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("signature_status", sa.String(length=50), nullable=False),
            sa.Column("payload_digest", sa.String(length=128), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("validation_result", json_type(), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_callbacks")),
            sa.UniqueConstraint("callback_id", name="uq_execution_callbacks_callback_id"),
        )
    _create_index(
        "ix_execution_callbacks_org_id_context_id",
        "execution_callbacks",
        ["org_id", "context_id"],
    )
    _create_index(
        "ix_execution_callbacks_org_id_workflow_id",
        "execution_callbacks",
        ["org_id", "workflow_id"],
    )
    _create_index(
        "ix_execution_callbacks_org_id_status",
        "execution_callbacks",
        ["org_id", "status"],
    )

    if not _table_exists("execution_results"):
        op.create_table(
            "execution_results",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("result_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("execution_id", sa.String(length=128), nullable=True),
            sa.Column("module_key", sa.String(length=128), nullable=False),
            sa.Column("task", sa.String(length=180), nullable=False),
            sa.Column("workflow_id", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("original_request", json_type(), nullable=False),
            sa.Column("workflow_output", json_type(), nullable=False),
            sa.Column("execution_metadata", json_type(), nullable=False),
            sa.Column("callbacks_received", sa.Integer(), server_default="0", nullable=False),
            sa.Column("signature_validated", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("payload_validated", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_results")),
            sa.UniqueConstraint("result_id", name="uq_execution_results_result_id"),
            sa.UniqueConstraint("context_id", name="uq_execution_results_context_id"),
        )
    _create_index(
        "ix_execution_results_org_id_context_id",
        "execution_results",
        ["org_id", "context_id"],
    )
    _create_index(
        "ix_execution_results_org_id_workflow_id",
        "execution_results",
        ["org_id", "workflow_id"],
    )
    _create_index(
        "ix_execution_results_org_id_status",
        "execution_results",
        ["org_id", "status"],
    )

    if not _table_exists("execution_dlq"):
        op.create_table(
            "execution_dlq",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("dlq_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=True),
            sa.Column("execution_id", sa.String(length=128), nullable=True),
            sa.Column("module_key", sa.String(length=128), nullable=True),
            sa.Column("workflow_id", sa.String(length=180), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replayable", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_dlq")),
            sa.UniqueConstraint("dlq_id", name="uq_execution_dlq_dlq_id"),
        )
    _create_index(
        "ix_execution_dlq_org_id_context_id",
        "execution_dlq",
        ["org_id", "context_id"],
    )
    _create_index("ix_execution_dlq_org_id_status", "execution_dlq", ["org_id", "status"])
    _create_index(
        "ix_execution_dlq_org_id_retry_after",
        "execution_dlq",
        ["org_id", "retry_after"],
    )


def downgrade() -> None:
    for table_name in ("execution_dlq", "execution_results", "execution_callbacks"):
        if _table_exists(table_name):
            op.drop_table(table_name)
