"""Owner-only hourly API key health monitoring.

Revision ID: 20260710_04_key_health
Revises: 20260710_03_k_image_render_jobs
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_04_key_health"
down_revision: str | Sequence[str] | None = "20260710_03_k_image_render_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "p_notifications",
        sa.Column("recipient_user_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_p_notifications_recipient_status_created",
        "p_notifications",
        ["recipient_user_id", "status", "created_at"],
    )

    op.create_table(
        "key_health_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("healthy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheduled_for", name="uq_key_health_runs_scheduled_for"),
    )
    op.create_index(
        "ix_key_health_runs_status_started",
        "key_health_runs",
        ["status", "started_at"],
    )

    op.create_table(
        "key_health_checks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("key_id", sa.String(length=40), nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("key_name", sa.String(length=120), nullable=False),
        sa.Column("key_hash_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_type", sa.String(length=48), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["key_health_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "key_id", name="uq_key_health_checks_run_key"),
    )
    op.create_index(
        "ix_key_health_checks_key_checked",
        "key_health_checks",
        ["key_id", "checked_at"],
    )
    op.create_index(
        "ix_key_health_checks_status_checked",
        "key_health_checks",
        ["status", "checked_at"],
    )
    op.create_index(
        "ix_key_health_checks_org_checked",
        "key_health_checks",
        ["org_id", "checked_at"],
    )

    op.create_table(
        "key_health_states",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key_id", sa.String(length=40), nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("key_name", sa.String(length=120), nullable=False),
        sa.Column("key_hash_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_type", sa.String(length=48), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("current_status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_id", name="uq_key_health_states_key_id"),
    )
    op.create_index(
        "ix_key_health_states_status_checked",
        "key_health_states",
        ["current_status", "last_checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_key_health_states_status_checked", table_name="key_health_states")
    op.drop_table("key_health_states")
    op.drop_index("ix_key_health_checks_org_checked", table_name="key_health_checks")
    op.drop_index("ix_key_health_checks_status_checked", table_name="key_health_checks")
    op.drop_index("ix_key_health_checks_key_checked", table_name="key_health_checks")
    op.drop_table("key_health_checks")
    op.drop_index("ix_key_health_runs_status_started", table_name="key_health_runs")
    op.drop_table("key_health_runs")
    op.drop_index(
        "ix_p_notifications_recipient_status_created",
        table_name="p_notifications",
    )
    op.drop_column("p_notifications", "recipient_user_id")
