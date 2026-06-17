"""C17 durable observability tables

Revision ID: c17_durable_observability_001
Revises: execution_durable_state_001
Create Date: 2026-06-17

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "c17_durable_observability_001"
down_revision: str | Sequence[str] | None = "execution_durable_state_001"
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


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
    }


def _create_index(
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _table_exists("event_streams"):
        op.create_table(
            "event_streams",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("record_id", sa.String(length=128), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("event_id", sa.String(length=180), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("trace_id", sa.String(length=180), nullable=False),
            sa.Column("product_key", sa.String(length=180), nullable=True),
            sa.Column("user_id", sa.String(length=180), nullable=True),
            sa.Column("workflow_id", sa.String(length=180), nullable=True),
            sa.Column("module_id", sa.String(length=180), nullable=False),
            sa.Column("event_type", sa.String(length=180), nullable=False),
            sa.Column("action", sa.String(length=240), nullable=False),
            sa.Column("source", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("storage_tier", sa.String(length=50), nullable=False),
            sa.Column("backend_targets", json_type(), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("metadata", json_type(), nullable=False),
            sa.Column("compressed", sa.Boolean(), nullable=False),
            sa.Column("archive_object_key", sa.String(length=500), nullable=True),
            sa.Column("processing_status", sa.String(length=50), nullable=False),
            sa.Column("processing_error", sa.Text(), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_event_streams")),
            sa.UniqueConstraint("record_id", name="uq_event_streams_record_id"),
        )
    _create_index("ix_event_streams_org_id_timestamp", "event_streams", ["org_id", "timestamp"])
    _create_index("ix_event_streams_org_id_context_id", "event_streams", ["org_id", "context_id"])
    _create_index("ix_event_streams_org_id_trace_id", "event_streams", ["org_id", "trace_id"])
    _create_index("ix_event_streams_org_id_module_id", "event_streams", ["org_id", "module_id"])
    _create_index("ix_event_streams_org_id_status", "event_streams", ["org_id", "status"])
    _create_index("ix_event_streams_org_id_event_type", "event_streams", ["org_id", "event_type"])
    _create_index("ix_event_streams_processing_status", "event_streams", ["processing_status"])

    if not _table_exists("audit_logs"):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("audit_id", sa.String(length=128), nullable=False),
            sa.Column("event_stream_record_id", sa.String(length=128), nullable=True),
            sa.Column("event_id", sa.String(length=180), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("module_id", sa.String(length=180), nullable=False),
            sa.Column("action", sa.String(length=240), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", json_type(), nullable=False),
            sa.Column("metadata", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
            sa.UniqueConstraint("audit_id", name="uq_audit_logs_audit_id"),
        )
    _create_index("ix_audit_logs_org_id_timestamp", "audit_logs", ["org_id", "timestamp"])
    _create_index("ix_audit_logs_org_id_context_id", "audit_logs", ["org_id", "context_id"])
    _create_index("ix_audit_logs_org_id_trace_id", "audit_logs", ["org_id", "trace_id"])
    _create_index("ix_audit_logs_org_id_module_id", "audit_logs", ["org_id", "module_id"])

    if not _table_exists("replay_jobs"):
        op.create_table(
            "replay_jobs",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("replay_id", sa.String(length=128), nullable=False),
            sa.Column("source_type", sa.String(length=80), nullable=False),
            sa.Column("source_id", sa.String(length=180), nullable=False),
            sa.Column("context_id", sa.String(length=180), nullable=False),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("mode", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("deterministic_hash", sa.String(length=128), nullable=False),
            sa.Column("input_event_ids", json_type(), nullable=False),
            sa.Column("replay_input", json_type(), nullable=False),
            sa.Column("replay_output", json_type(), nullable=False),
            sa.Column("replay_result", json_type(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_replay_jobs")),
            sa.UniqueConstraint("replay_id", name="uq_replay_jobs_replay_id"),
        )
    _create_index("ix_replay_jobs_org_id_context_id", "replay_jobs", ["org_id", "context_id"])
    _create_index("ix_replay_jobs_org_id_trace_id", "replay_jobs", ["org_id", "trace_id"])
    _create_index("ix_replay_jobs_org_id_status", "replay_jobs", ["org_id", "status"])
    _create_index("ix_replay_jobs_org_id_created_at", "replay_jobs", ["org_id", "created_at"])

    if not _table_exists("anomaly_events"):
        op.create_table(
            "anomaly_events",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("org_id", sa.String(length=40), nullable=False),
            sa.Column("anomaly_id", sa.String(length=128), nullable=False),
            sa.Column("source_event_id", sa.String(length=180), nullable=True),
            sa.Column("context_id", sa.String(length=180), nullable=True),
            sa.Column("trace_id", sa.String(length=180), nullable=True),
            sa.Column("module_id", sa.String(length=180), nullable=False),
            sa.Column("anomaly_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=50), nullable=False),
            sa.Column("rule_id", sa.String(length=180), nullable=False),
            sa.Column("entity_type", sa.String(length=80), nullable=False),
            sa.Column("entity_id", sa.String(length=180), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("threshold_value", sa.Float(), nullable=True),
            sa.Column("observed_value", sa.Float(), nullable=True),
            sa.Column("window_seconds", sa.Integer(), nullable=False),
            sa.Column("event_count", sa.Integer(), nullable=False),
            sa.Column("score", json_type(), nullable=False),
            sa.Column("evidence", json_type(), nullable=False),
            created_at_column(),
            updated_at_column(),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_anomaly_events")),
            sa.UniqueConstraint("anomaly_id", name="uq_anomaly_events_anomaly_id"),
        )
    _create_index("ix_anomaly_events_org_id_timestamp", "anomaly_events", ["org_id", "timestamp"])
    _create_index("ix_anomaly_events_org_id_context_id", "anomaly_events", ["org_id", "context_id"])
    _create_index("ix_anomaly_events_org_id_module_id", "anomaly_events", ["org_id", "module_id"])
    _create_index(
        "ix_anomaly_events_org_id_type_severity",
        "anomaly_events",
        ["org_id", "anomaly_type", "severity"],
    )


def downgrade() -> None:
    for table_name in (
        "anomaly_events",
        "replay_jobs",
        "audit_logs",
        "event_streams",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)
