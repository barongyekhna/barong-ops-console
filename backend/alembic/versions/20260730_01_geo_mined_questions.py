"""类目级深挖出来的买家问句。

原有候选(K 的 FAQ + F 的类目词)是实时读出来的、零成本;深挖是花钱换来的
(一发 Serper 一笔台账),所以必须落表——否则等于反复付钱买同一批问句。

Revision ID: 20260730_01_geo_mined_questions
Revises: 20260729_15_b2b_orders_and_credits
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_01_geo_mined_questions"
down_revision: str | Sequence[str] | None = "20260729_15_b2b_orders_and_credits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geo_mined_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "cluster_id",
            sa.Uuid(),
            sa.ForeignKey(
                "geo_content_clusters.id", name="fk_geo_mined_questions_cluster_id"
            ),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("seed_query", sa.String(255), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "workspace_key",
            sa.String(128),
            nullable=False,
            server_default="default_independent_store",
        ),
        sa.Column(
            "business_context",
            sa.String(64),
            nullable=False,
            server_default="independent_store",
        ),
        sa.Column(
            "scope_mode",
            sa.String(32),
            nullable=False,
            server_default="adapter_pending",
        ),
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
        sa.UniqueConstraint(
            "cluster_id",
            "normalized_question",
            name="uq_geo_mined_questions_cluster_norm",
        ),
    )
    op.create_index(
        "ix_geo_mined_questions_cluster", "geo_mined_questions", ["cluster_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_geo_mined_questions_cluster", "geo_mined_questions")
    op.drop_table("geo_mined_questions")
