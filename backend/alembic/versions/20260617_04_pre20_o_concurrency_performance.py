"""PRE20-O concurrency and performance stabilization

Revision ID: pre20_o_concurrency_perf_001
Revises: c17_durable_observability_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "pre20_o_concurrency_perf_001"
down_revision: str | Sequence[str] | None = "c17_durable_observability_001"
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


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _table_exists(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return constraint_name in {
        constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)
    }


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    **dialect_kwargs: object,
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=unique,
            **dialect_kwargs,
        )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(column)


def _create_unique_constraint_if_missing(
    table_name: str,
    constraint_name: str,
    columns: list[str],
) -> None:
    if _table_exists(table_name) and not _unique_constraint_exists(table_name, constraint_name):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_unique_constraint(constraint_name, columns)


def _upgrade_execution_callbacks() -> None:
    _add_column_if_missing(
        "execution_callbacks",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    _add_column_if_missing(
        "execution_callbacks",
        sa.Column("trace_id", sa.String(length=180), nullable=True),
    )
    _add_column_if_missing(
        "execution_callbacks",
        sa.Column("job_id", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "execution_callbacks",
        sa.Column("actor_id", sa.String(length=128), nullable=True),
    )
    _create_unique_constraint_if_missing(
        "execution_callbacks",
        "uq_execution_callbacks_idempotency_key",
        ["idempotency_key"],
    )
    for index_name, columns in (
        ("ix_execution_callbacks_org_id", ["org_id"]),
        ("ix_execution_callbacks_org_id_execution_id", ["org_id", "execution_id"]),
        ("ix_execution_callbacks_org_id_created_at", ["org_id", "created_at"]),
        ("ix_execution_callbacks_org_id_module_key", ["org_id", "module_key"]),
        ("ix_execution_callbacks_idempotency_key", ["idempotency_key"]),
    ):
        _create_index(index_name, "execution_callbacks", columns)


def _create_callback_state() -> None:
    if not _table_exists("callback_state"):
        op.create_table(
            "callback_state",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("result_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("execution_id", sa.String(length=128), nullable=False),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("job_id", sa.String(length=128), nullable=True),
            sa.Column("actor_id", sa.String(length=128), nullable=True),
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
            sa.PrimaryKeyConstraint("id", name=op.f("pk_callback_state")),
            sa.UniqueConstraint("result_id", name="uq_callback_state_result_id"),
            sa.UniqueConstraint("context_id", name="uq_callback_state_context_id"),
            sa.UniqueConstraint("execution_id", name="uq_callback_state_execution_id"),
        )
    for index_name, columns in (
        ("ix_callback_state_org_id", ["org_id"]),
        ("ix_callback_state_org_id_context_id", ["org_id", "context_id"]),
        ("ix_callback_state_org_id_execution_id", ["org_id", "execution_id"]),
        ("ix_callback_state_org_id_workflow_id", ["org_id", "workflow_id"]),
        ("ix_callback_state_org_id_status", ["org_id", "status"]),
        ("ix_callback_state_org_id_created_at", ["org_id", "created_at"]),
        ("ix_callback_state_org_id_module_key", ["org_id", "module_key"]),
        ("ix_callback_state_org_id_trace_id", ["org_id", "trace_id"]),
        ("ix_callback_state_org_id_job_id", ["org_id", "job_id"]),
        ("ix_callback_state_org_id_actor_id", ["org_id", "actor_id"]),
    ):
        _create_index(index_name, "callback_state", columns)


def _create_callback_transitions() -> None:
    if not _table_exists("callback_state_transitions"):
        op.create_table(
            "callback_state_transitions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("transition_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("execution_id", sa.String(length=128), nullable=False),
            sa.Column("from_status", sa.String(length=50), nullable=True),
            sa.Column("to_status", sa.String(length=50), nullable=False),
            sa.Column("idempotency_key", sa.String(length=255), nullable=False),
            sa.Column("payload_digest", sa.String(length=128), nullable=True),
            created_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_callback_state_transitions")),
            sa.UniqueConstraint(
                "transition_id",
                name="uq_callback_state_transitions_transition_id",
            ),
            sa.UniqueConstraint(
                "idempotency_key",
                name="uq_callback_state_transitions_idempotency_key",
            ),
        )
    for index_name, columns in (
        ("ix_callback_state_transitions_execution_id", ["execution_id"]),
        ("ix_callback_state_transitions_context_id", ["context_id"]),
        ("ix_callback_state_transitions_to_status", ["to_status"]),
        ("ix_callback_state_transitions_created_at", ["created_at"]),
        ("ix_callback_state_transitions_idempotency_key", ["idempotency_key"]),
    ):
        _create_index(index_name, "callback_state_transitions", columns)
    _create_index(
        "uq_callback_state_transitions_terminal_execution_id",
        "callback_state_transitions",
        ["execution_id"],
        unique=True,
        sqlite_where=sa.text("to_status IN ('success', 'failed')"),
        postgresql_where=sa.text("to_status IN ('success', 'failed')"),
    )


def _create_dlq_state() -> None:
    if not _table_exists("dlq_state"):
        op.create_table(
            "dlq_state",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("dlq_id", sa.String(length=128), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=True),
            sa.Column("execution_id", sa.String(length=128), nullable=True),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("job_id", sa.String(length=128), nullable=True),
            sa.Column("actor_id", sa.String(length=128), nullable=True),
            sa.Column("module_key", sa.String(length=128), nullable=True),
            sa.Column("workflow_id", sa.String(length=180), nullable=True),
            sa.Column("failure_type", sa.String(length=80), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("failure_context", json_type(), nullable=False),
            sa.Column("retry_decision", json_type(), nullable=False),
            sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
            sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replay_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replayable", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_dlq_state")),
            sa.UniqueConstraint("dlq_id", name="uq_dlq_state_dlq_id"),
        )
    for index_name, columns in (
        ("ix_dlq_state_org_id", ["org_id"]),
        ("ix_dlq_state_org_id_context_id", ["org_id", "context_id"]),
        ("ix_dlq_state_org_id_execution_id", ["org_id", "execution_id"]),
        ("ix_dlq_state_org_id_status", ["org_id", "status"]),
        ("ix_dlq_state_org_id_retry_after", ["org_id", "retry_after"]),
        ("ix_dlq_state_org_id_created_at", ["org_id", "created_at"]),
        ("ix_dlq_state_org_id_module_key", ["org_id", "module_key"]),
        ("ix_dlq_state_org_id_trace_id", ["org_id", "trace_id"]),
        ("ix_dlq_state_org_id_job_id", ["org_id", "job_id"]),
        ("ix_dlq_state_org_id_actor_id", ["org_id", "actor_id"]),
    ):
        _create_index(index_name, "dlq_state", columns)


def _upgrade_event_streams() -> None:
    _add_column_if_missing(
        "event_streams",
        sa.Column("job_id", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "event_streams",
        sa.Column("actor_id", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "event_streams",
        sa.Column("processing_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    _add_column_if_missing(
        "event_streams",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    for index_name, columns in (
        ("ix_event_streams_org_id_created_at", ["org_id", "created_at"]),
        ("ix_event_streams_org_id_workflow_id", ["org_id", "workflow_id"]),
        ("ix_event_streams_org_id_job_id", ["org_id", "job_id"]),
        ("ix_event_streams_org_id_actor_id", ["org_id", "actor_id"]),
        ("ix_event_streams_trace_id", ["trace_id"]),
        ("ix_event_streams_module_id", ["module_id"]),
        (
            "ix_event_streams_processing_status_next_retry_at",
            ["processing_status", "next_retry_at"],
        ),
    ):
        _create_index(index_name, "event_streams", columns)


def _upgrade_hot_indexes() -> None:
    for index_name, table_name, columns in (
        ("ix_module_bindings_module_id", "module_bindings", ["module_id"]),
        ("ix_module_bindings_status", "module_bindings", ["status"]),
        ("ix_module_bindings_created_at", "module_bindings", ["created_at"]),
        ("ix_shared_modules_status", "shared_modules", ["status"]),
        ("ix_shared_modules_created_at", "shared_modules", ["created_at"]),
        ("ix_operation_logs_org_id_result", "operation_logs", ["org_id", "result"]),
        ("ix_operation_logs_org_id_job_id", "operation_logs", ["org_id", "job_id"]),
        ("ix_operation_logs_org_id_actor_id", "operation_logs", ["org_id", "actor_id"]),
        ("ix_operation_logs_org_id_request_id", "operation_logs", ["org_id", "request_id"]),
        ("ix_automation_jobs_org_id_job_id", "automation_jobs", ["org_id", "job_id"]),
        (
            "ix_automation_jobs_org_id_requested_by_user_id",
            "automation_jobs",
            ["org_id", "requested_by_user_id"],
        ),
        (
            "ix_automation_jobs_org_id_correlation_id",
            "automation_jobs",
            ["org_id", "correlation_id"],
        ),
        (
            "ix_job_events_org_id_job_id_created_at",
            "job_events",
            ["org_id", "job_id", "created_at"],
        ),
        ("ix_job_events_org_id_actor_id", "job_events", ["org_id", "actor_id"]),
    ):
        _create_index(index_name, table_name, columns)


def upgrade() -> None:
    _upgrade_execution_callbacks()
    _create_callback_state()
    _create_callback_transitions()
    _create_dlq_state()
    _upgrade_event_streams()
    _upgrade_hot_indexes()


def downgrade() -> None:
    for table_name in (
        "dlq_state",
        "callback_state_transitions",
        "callback_state",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
