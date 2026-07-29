"""GEO publishing: dispatch queue, WP category cache, site settings, item URLs.

Milestone 3 sends approved guide articles to WordPress through a dedicated n8n
workflow. Mirrors the P upload machinery: a serial job queue with one-time tokens,
plus a learned Google-taxonomy → WP-term cache so guide categories reproduce
exactly the tree K already defines (the same tree P mirrors into Woo).

Revision ID: 20260729_01_geo_publish
Revises: 20260728_07_geo_item_revision
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260729_01_geo_publish"
down_revision: str | Sequence[str] | None = "20260728_07_geo_item_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS_DEFAULT = "default_independent_store"
_BC_DEFAULT = "independent_store"
_SM_DEFAULT = "adapter_pending"


def upgrade() -> None:
    op.create_table(
        "geo_publish_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("cluster_id", sa.Uuid(), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=32),
            nullable=False,
            server_default="wordpress",
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="queued"
        ),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("published_items_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_username", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_geo_publish_jobs_job_id"),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["geo_content_clusters.id"],
            name="fk_geo_publish_jobs_cluster_id",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name="ck_geo_publish_jobs_valid_status",
        ),
    )
    op.create_index("ix_geo_publish_jobs_status", "geo_publish_jobs", ["status"])
    op.create_index("ix_geo_publish_jobs_cluster", "geo_publish_jobs", ["cluster_id"])
    op.create_index("ix_geo_publish_jobs_created", "geo_publish_jobs", ["created_at"])

    op.create_table(
        "geo_wp_category_map",
        sa.Column("google_id", sa.String(length=32), nullable=False),
        sa.Column("wp_term_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("google_id"),
        sa.CheckConstraint(
            "wp_term_id > 0", name="ck_geo_wp_category_map_term_positive"
        ),
    )
    op.create_index(
        "ix_geo_wp_category_map_term", "geo_wp_category_map", ["wp_term_id"]
    )

    op.create_table(
        "geo_site_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.add_column(
        "geo_content_items", sa.Column("wp_post_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "geo_content_items",
        sa.Column("published_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "geo_content_items",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_content_items", "published_at")
    op.drop_column("geo_content_items", "published_url")
    op.drop_column("geo_content_items", "wp_post_id")
    op.drop_table("geo_site_settings")
    op.drop_table("geo_wp_category_map")
    op.drop_table("geo_publish_jobs")
