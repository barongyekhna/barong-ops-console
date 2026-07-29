"""B2B product-page widget dispatch queue.

把批发信息推到 Woo 产品页小窗的串行派单表。语义照抄 geo_backlink_jobs——
那套是生产事故换来的:同时最多一单在飞、发 webhook 前先 commit、15 分钟
没回报按失联、终态幂等。

Revision ID: 20260729_06_b2b_widget_jobs
Revises: 20260729_05_geo_monitor
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_06_b2b_widget_jobs"
down_revision: str | Sequence[str] | None = "20260729_05_geo_monitor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "b2b_widget_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
            server_default="woocommerce",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("token", sa.String(length=128), nullable=False),
        # 派单那一刻冻住的推送内容。包端点原样吐回,绝不重新推导。
        sa.Column("targets_json", sa.JSON(), nullable=True),
        sa.Column("updated_items_json", sa.JSON(), nullable=True),
        sa.Column(
            "requested_by_username", sa.String(length=128), nullable=True
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("job_id", name="uq_b2b_widget_jobs_job_id"),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name="ck_b2b_widget_jobs_status",
        ),
    )
    op.create_index("ix_b2b_widget_jobs_status", "b2b_widget_jobs", ["status"])
    op.create_index(
        "ix_b2b_widget_jobs_created", "b2b_widget_jobs", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_b2b_widget_jobs_created", table_name="b2b_widget_jobs")
    op.drop_index("ix_b2b_widget_jobs_status", table_name="b2b_widget_jobs")
    op.drop_table("b2b_widget_jobs")
