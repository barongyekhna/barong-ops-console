"""rw realtime engine tables

Revision ID: 20260702_04_rw_realtime_engine
Revises: 20260702_03_rw_keepa_concurrency_indexes
Create Date: 2026-07-02 12:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260702_04_rw_realtime_engine"
down_revision = "20260702_03_rw_keepa_concurrency_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE products_rw ADD COLUMN IF NOT EXISTS image_url TEXT")
    op.execute("ALTER TABLE enrich_queue ADD COLUMN IF NOT EXISTS category_id TEXT")
    op.execute("ALTER TABLE enrich_queue ADD COLUMN IF NOT EXISTS category_path TEXT")
    op.create_index(
        "idx_enrich_queue_category_pending",
        "enrich_queue",
        ["category_id", "picked", "enqueued_at"],
        if_not_exists=True,
    )
    op.create_table(
        "rw_pipeline_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asin", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score_action", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "rw_worker_status",
        sa.Column("worker_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("loop_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("deepseek_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_pending", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_categories", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("worker_name"),
        if_not_exists=True,
    )
    op.create_index(
        "idx_rw_pipeline_events_created",
        "rw_pipeline_events",
        ["created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_rw_pipeline_events_asin",
        "rw_pipeline_events",
        ["asin"],
        if_not_exists=True,
    )
    op.create_index(
        "idx_rw_worker_status_heartbeat",
        "rw_worker_status",
        ["last_heartbeat_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("idx_rw_worker_status_heartbeat", table_name="rw_worker_status", if_exists=True)
    op.drop_index("idx_rw_pipeline_events_asin", table_name="rw_pipeline_events", if_exists=True)
    op.drop_index("idx_rw_pipeline_events_created", table_name="rw_pipeline_events", if_exists=True)
    op.drop_table("rw_worker_status", if_exists=True)
    op.drop_table("rw_pipeline_events", if_exists=True)
    op.drop_index("idx_enrich_queue_category_pending", table_name="enrich_queue", if_exists=True)
    with op.batch_alter_table("enrich_queue") as batch_op:
        batch_op.drop_column("category_path")
        batch_op.drop_column("category_id")
    with op.batch_alter_table("products_rw") as batch_op:
        batch_op.drop_column("image_url")
