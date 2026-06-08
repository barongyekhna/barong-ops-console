"""create core foundation tables

Revision ID: f07_core_001
Revises:
Create Date: 2026-06-08

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f07_core_001"
down_revision: str | Sequence[str] | None = None
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


def registry_columns(stable_id: str) -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(stable_id, sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("responsibilities", json_type(), nullable=False),
        sa.Column("non_responsibilities", json_type(), nullable=False),
        sa.Column("input_schema", json_type(), nullable=False),
        sa.Column("output_schema", json_type(), nullable=False),
        sa.Column("permissions", json_type(), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("dependencies", json_type(), nullable=False),
        sa.Column("artifact_types", json_type(), nullable=False),
        sa.Column("review_types", json_type(), nullable=False),
        sa.Column("error_codes", json_type(), nullable=False),
        sa.Column("healthcheck_config", json_type(), nullable=False),
        sa.Column("rollback_policy", json_type(), nullable=False),
        created_at_column(),
        updated_at_column(),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )

    op.create_table(
        "module_registry",
        *registry_columns("module_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_registry")),
        sa.UniqueConstraint(
            "module_id",
            name=op.f("uq_module_registry_module_id"),
        ),
    )

    op.create_table(
        "agent_registry",
        *registry_columns("agent_id"),
        sa.Column("allowed_module_ids", json_type(), nullable=False),
        sa.Column("allowed_workflow_ids", json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_registry")),
        sa.UniqueConstraint(
            "agent_id",
            name=op.f("uq_agent_registry_agent_id"),
        ),
    )

    op.create_table(
        "workflow_registry",
        *registry_columns("workflow_id"),
        sa.Column("engine", sa.String(length=50), nullable=False),
        sa.Column("endpoint_ref", sa.String(length=255), nullable=False),
        sa.Column("callback_contract", json_type(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("retry_policy", json_type(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_registry")),
        sa.UniqueConstraint(
            "workflow_id",
            name=op.f("uq_workflow_registry_workflow_id"),
        ),
    )

    op.create_table(
        "automation_jobs",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("module_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_id", sa.String(length=128), nullable=True),
        sa.Column("parent_job_id", sa.String(length=128), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("input_payload", json_type(), nullable=False),
        sa.Column(
            "input_schema_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_registry.agent_id"],
            name=op.f("fk_automation_jobs_agent_id_agent_registry"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["module_registry.module_id"],
            name=op.f("fk_automation_jobs_module_id_module_registry"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_automation_jobs_parent_job_id_automation_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_automation_jobs_requested_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_registry.workflow_id"],
            name=op.f("fk_automation_jobs_workflow_id_workflow_registry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_jobs")),
        sa.UniqueConstraint(
            "job_id",
            name=op.f("uq_automation_jobs_job_id"),
        ),
    )

    op.create_table(
        "job_events",
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("from_status", sa.String(length=50), nullable=True),
        sa.Column("to_status", sa.String(length=50), nullable=True),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("details", json_type(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_job_events_job_id_automation_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
    )

    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=False),
        sa.Column("module_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("storage_provider", sa.String(length=100), nullable=False),
        sa.Column("storage_ref", sa.String(length=1024), nullable=False),
        sa.Column("content_hash", sa.String(length=255), nullable=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metadata", json_type(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_artifacts_job_id_automation_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["module_registry.module_id"],
            name=op.f("fk_artifacts_module_id_module_registry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        sa.UniqueConstraint(
            "artifact_id",
            name=op.f("uq_artifacts_artifact_id"),
        ),
    )

    op.create_table(
        "review_items",
        sa.Column("review_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("artifact_id", sa.String(length=128), nullable=True),
        sa.Column("review_type", sa.String(length=100), nullable=False),
        sa.Column("risk_level", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=False),
        sa.Column("assigned_to", sa.BigInteger(), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=True),
        sa.Column("comment", sa.String(length=4000), nullable=True),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.CheckConstraint(
            "job_id IS NOT NULL OR artifact_id IS NOT NULL",
            name=op.f("ck_review_items_has_review_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.artifact_id"],
            name=op.f("fk_review_items_artifact_id_artifacts"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_review_items_assigned_to_users"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_review_items_decided_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_review_items_job_id_automation_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_review_items_requested_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_items")),
        sa.UniqueConstraint(
            "review_id",
            name=op.f("uq_review_items_review_id"),
        ),
    )

    op.create_table(
        "system_errors",
        sa.Column("error_id", sa.String(length=128), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("details", json_type(), nullable=True),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("module_id", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acknowledged_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["acknowledged_by"],
            ["users.id"],
            name=op.f("fk_system_errors_acknowledged_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_registry.agent_id"],
            name=op.f("fk_system_errors_agent_id_agent_registry"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_system_errors_job_id_automation_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["module_registry.module_id"],
            name=op.f("fk_system_errors_module_id_module_registry"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflow_registry.workflow_id"],
            name=op.f("fk_system_errors_workflow_id_workflow_registry"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_errors")),
        sa.UniqueConstraint(
            "error_id",
            name=op.f("uq_system_errors_error_id"),
        ),
    )

    op.create_table(
        "memory_events",
        sa.Column("memory_event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("importance", sa.String(length=50), nullable=False),
        sa.Column("created_by_type", sa.String(length=50), nullable=False),
        sa.Column("created_by_id", sa.String(length=128), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_memory_events_job_id_automation_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_events")),
        sa.UniqueConstraint(
            "memory_event_id",
            name=op.f("uq_memory_events_memory_event_id"),
        ),
    )

    op.create_table(
        "operation_logs",
        sa.Column("operation_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=1000), nullable=True),
        sa.Column("details", json_type(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_operation_logs_job_id_automation_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_logs")),
        sa.UniqueConstraint(
            "operation_id",
            name=op.f("uq_operation_logs_operation_id"),
        ),
    )

    op.create_table(
        "context_packets",
        sa.Column(
            "context_packet_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("source_job_id", sa.String(length=128), nullable=False),
        sa.Column("source_module_id", sa.String(length=128), nullable=False),
        sa.Column("target_module_id", sa.String(length=128), nullable=True),
        sa.Column("target_agent_id", sa.String(length=128), nullable=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("artifact_refs", json_type(), nullable=False),
        sa.Column("access_scope", json_type(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.CheckConstraint(
            "target_module_id IS NOT NULL OR target_agent_id IS NOT NULL",
            name=op.f("ck_context_packets_has_context_target"),
        ),
        sa.ForeignKeyConstraint(
            ["source_job_id"],
            ["automation_jobs.job_id"],
            name=op.f("fk_context_packets_source_job_id_automation_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["source_module_id"],
            ["module_registry.module_id"],
            name=op.f(
                "fk_context_packets_source_module_id_module_registry"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_id"],
            ["agent_registry.agent_id"],
            name=op.f("fk_context_packets_target_agent_id_agent_registry"),
        ),
        sa.ForeignKeyConstraint(
            ["target_module_id"],
            ["module_registry.module_id"],
            name=op.f(
                "fk_context_packets_target_module_id_module_registry"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_packets")),
        sa.UniqueConstraint(
            "context_packet_id",
            name=op.f("uq_context_packets_context_packet_id"),
        ),
    )

    op.create_table(
        "memory_summaries",
        sa.Column(
            "memory_summary_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.String(length=8000), nullable=False),
        sa.Column("source_event_ids", json_type(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "valid_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_summaries")),
        sa.UniqueConstraint(
            "memory_summary_id",
            name=op.f("uq_memory_summaries_memory_summary_id"),
        ),
    )

    op.create_table(
        "agent_memory_access_logs",
        sa.Column("access_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=128), nullable=True),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=1000), nullable=False),
        sa.Column("access_scope", json_type(), nullable=False),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("denial_reason", sa.String(length=1000), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        created_at_column(),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_registry.agent_id"],
            name=op.f(
                "fk_agent_memory_access_logs_agent_id_agent_registry"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["automation_jobs.job_id"],
            name=op.f(
                "fk_agent_memory_access_logs_job_id_automation_jobs"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_agent_memory_access_logs"),
        ),
        sa.UniqueConstraint(
            "access_id",
            name=op.f("uq_agent_memory_access_logs_access_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_memory_access_logs")
    op.drop_table("memory_summaries")
    op.drop_table("context_packets")
    op.drop_table("operation_logs")
    op.drop_table("memory_events")
    op.drop_table("system_errors")
    op.drop_table("review_items")
    op.drop_table("artifacts")
    op.drop_table("job_events")
    op.drop_table("automation_jobs")
    op.drop_table("workflow_registry")
    op.drop_table("agent_registry")
    op.drop_table("module_registry")
    op.drop_table("users")
