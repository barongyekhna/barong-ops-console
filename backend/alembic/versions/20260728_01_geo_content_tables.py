"""GEO content engine tables (clusters, items, generation jobs).

Milestone 1 of the GEO series: the content engine reads K product facts and
writes AI-citable guide content into these scope-partitioned tables for review.

Revision ID: 20260728_01_geo_content_tables
Revises: 20260727_04_b2b_prospect_signals
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_01_geo_content_tables"
down_revision: str | Sequence[str] | None = "20260727_04_b2b_prospect_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS_DEFAULT = "default_independent_store"
_BC_DEFAULT = "independent_store"
_SM_DEFAULT = "adapter_pending"


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "workspace_key",
            sa.String(length=128),
            nullable=False,
            server_default=_WS_DEFAULT,
        ),
        sa.Column(
            "business_context",
            sa.String(length=128),
            nullable=False,
            server_default=_BC_DEFAULT,
        ),
        sa.Column(
            "scope_mode",
            sa.String(length=64),
            nullable=False,
            server_default=_SM_DEFAULT,
        ),
    ]


def _timestamp_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "geo_content_clusters",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("google_category_id", sa.String(length=32), nullable=True),
        sa.Column("category_path", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(length=512), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="draft"
        ),
        sa.Column("seed_product_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('draft', 'generating', 'ready', 'needs_review', "
            "'approved', 'archived')",
            name="ck_geo_clusters_valid_status",
        ),
    )
    op.create_index(
        "ix_geo_clusters_scope_category",
        "geo_content_clusters",
        ["workspace_key", "business_context", "scope_mode", "google_category_id"],
    )
    op.create_index(
        "ix_geo_clusters_status", "geo_content_clusters", ["status"]
    )
    op.create_index(
        "ix_geo_clusters_created", "geo_content_clusters", ["created_at"]
    )

    op.create_table(
        "geo_content_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=True),
        sa.Column("seo_json", sa.JSON(), nullable=True),
        sa.Column("source_product_ids_json", sa.JSON(), nullable=True),
        sa.Column("schema_type", sa.String(length=20), nullable=True),
        sa.Column("brand_audit_json", sa.JSON(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "generation_status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("skill_version", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["geo_content_clusters.id"],
            name="fk_geo_items_cluster_id",
        ),
        sa.CheckConstraint(
            "item_type IN ('hub', 'how_it_works', 'comparison', 'scenario', 'qa')",
            name="ck_geo_items_valid_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_geo_items_valid_review",
        ),
        sa.CheckConstraint(
            "generation_status IN ('draft', 'generated', 'failed')",
            name="ck_geo_items_valid_generation",
        ),
    )
    op.create_index("ix_geo_items_cluster", "geo_content_items", ["cluster_id"])
    op.create_index(
        "ix_geo_items_cluster_type", "geo_content_items", ["cluster_id", "item_type"]
    )
    op.create_index(
        "ix_geo_items_review", "geo_content_items", ["review_status"]
    )

    op.create_table(
        "geo_generation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *_scope_columns(),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column(
            "job_type",
            sa.String(length=30),
            nullable=False,
            server_default="geo_content",
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_username", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["geo_content_clusters.id"],
            name="fk_geo_jobs_cluster_id",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_geo_jobs_valid_status",
        ),
    )
    op.create_index("ix_geo_jobs_status", "geo_generation_jobs", ["status"])
    op.create_index("ix_geo_jobs_cluster", "geo_generation_jobs", ["cluster_id"])
    op.create_index("ix_geo_jobs_batch", "geo_generation_jobs", ["batch_id"])
    op.create_index("ix_geo_jobs_created", "geo_generation_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_table("geo_generation_jobs")
    op.drop_table("geo_content_items")
    op.drop_table("geo_content_clusters")
