"""r warehouse initial persistence schema

Revision ID: 20260702_00_rw_initial_schema
Revises: media_storage_perf_001
Create Date: 2026-07-02 03:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260702_00_rw_initial_schema"
down_revision = "media_storage_perf_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          CREATE TYPE rw_product_state AS ENUM (
            'discovered',
            'enriched',
            'rule_passed',
            'ai1_passed',
            'ai1_rejected',
            'rejected'
          );
        EXCEPTION
          WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.create_table(
        "products_rw",
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("marketplace", sa.Text(), nullable=False, server_default="US"),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("bsr", sa.Integer(), nullable=True),
        sa.Column("reviews", sa.Integer(), nullable=True),
        sa.Column("seller_count", sa.Integer(), nullable=True),
        sa.Column("landed_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("est_net_margin", sa.Numeric(8, 4), nullable=True),
        sa.Column("brand_share", sa.Numeric(8, 4), nullable=True),
        sa.Column("price_trend", sa.Text(), nullable=True),
        sa.Column("rating", sa.Numeric(3, 1), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(
                "discovered",
                "enriched",
                "rule_passed",
                "ai1_passed",
                "ai1_rejected",
                "rejected",
                name="rw_product_state",
                create_type=False,
            ),
            nullable=False,
            server_default="discovered",
        ),
        sa.Column("rule_reject_reason", sa.Text(), nullable=True),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_keepa_pull", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("asin"),
        if_not_exists=True,
    )
    op.create_table(
        "enrich_queue",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("marketplace", sa.Text(), nullable=False, server_default="US"),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column("picked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("picked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asin"),
        if_not_exists=True,
    )
    op.create_table(
        "rule_results",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checks", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "decision IN ('rule_passed', 'rule_rejected')",
            name=op.f("ck_rule_results_valid_decision"),
        ),
        sa.ForeignKeyConstraint(["asin"], ["products_rw.asin"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_table(
        "ai_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "layer IN ('deepseek')",
            name=op.f("ck_ai_evaluations_valid_layer"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name=op.f("ck_ai_evaluations_valid_score"),
        ),
        sa.CheckConstraint(
            "verdict IN ('keep', 'cut', 'hold')",
            name=op.f("ck_ai_evaluations_valid_verdict"),
        ),
        sa.ForeignKeyConstraint(["asin"], ["products_rw.asin"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("idx_products_rw_state", "products_rw", ["state"], if_not_exists=True)
    op.create_index("idx_products_rw_category", "products_rw", ["category"], if_not_exists=True)
    op.create_index("idx_enrich_queue_picked", "enrich_queue", ["picked", "enqueued_at"], if_not_exists=True)
    op.create_index("idx_rule_results_asin", "rule_results", ["asin"], if_not_exists=True)
    op.create_index("idx_ai_evaluations_asin", "ai_evaluations", ["asin"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_ai_evaluations_asin", table_name="ai_evaluations", if_exists=True)
    op.drop_index("idx_rule_results_asin", table_name="rule_results", if_exists=True)
    op.drop_index("idx_enrich_queue_picked", table_name="enrich_queue", if_exists=True)
    op.drop_index("idx_products_rw_category", table_name="products_rw", if_exists=True)
    op.drop_index("idx_products_rw_state", table_name="products_rw", if_exists=True)
    op.drop_table("ai_evaluations", if_exists=True)
    op.drop_table("rule_results", if_exists=True)
    op.drop_table("enrich_queue", if_exists=True)
    op.drop_table("products_rw", if_exists=True)
    op.execute("DROP TYPE IF EXISTS rw_product_state")
