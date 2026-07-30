"""SEO 内容引擎的表:选题 / 文章 / 生成队列 / 发布队列 / 雷达跑批 / 分类缓存。

外加给 geo_monitor_questions 添一列 kind——SEO 的关键词监测与 GEO 的买家问句
监测共用同一张表(见 seo_series/content/rank_monitor.py 里的理由)。

Revision ID: 20260729_12_seo_content_tables
Revises: 20260729_11_seo_permissions
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_12_seo_content_tables"
down_revision: str | Sequence[str] | None = "20260729_11_seo_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_columns() -> list[sa.Column]:
    return [
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
    ]


def _stamp_columns() -> list[sa.Column]:
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
        "seo_topics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("normalized_keyword", sa.String(255), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("destination", sa.String(16), nullable=False),
        sa.Column("google_category_id", sa.String(32), nullable=True),
        sa.Column("category_path", sa.Text(), nullable=True),
        sa.Column("store_type_key", sa.String(64), nullable=True),
        sa.Column("craft_topic", sa.String(64), nullable=True),
        sa.Column("avg_monthly_searches", sa.Integer(), nullable=True),
        sa.Column("competition_index", sa.Integer(), nullable=True),
        sa.Column("cpc_high_micros", sa.BigInteger(), nullable=True),
        sa.Column("attackability", sa.Integer(), nullable=True),
        sa.Column("terrain", sa.String(32), nullable=True),
        sa.Column(
            "geo_reachable", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("geo_reason", sa.Text(), nullable=True),
        sa.Column("fact_support_json", sa.JSON(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("picked_by_user_id", sa.BigInteger(), nullable=True),
        *_scope_columns(),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('candidate', 'picked', 'rejected', 'written')",
            name="ck_seo_topics_status",
        ),
        sa.CheckConstraint(
            "audience IN ('consumer', 'wholesale', 'brand')",
            name="ck_seo_topics_audience",
        ),
        sa.CheckConstraint(
            "destination IN ('factory', 'posts')", name="ck_seo_topics_destination"
        ),
    )
    op.create_index("ix_seo_topics_status", "seo_topics", ["status"])
    op.create_index("ix_seo_topics_audience", "seo_topics", ["audience"])
    op.create_index("ix_seo_topics_norm", "seo_topics", ["normalized_keyword"])

    op.create_table(
        "seo_content_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_id",
            sa.Uuid(),
            sa.ForeignKey("seo_topics.id", name="fk_seo_items_topic_id"),
            nullable=False,
        ),
        sa.Column("item_kind", sa.String(32), nullable=False),
        sa.Column("destination", sa.String(16), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=True),
        sa.Column("seo_json", sa.JSON(), nullable=True),
        sa.Column("links_json", sa.JSON(), nullable=True),
        sa.Column("brand_audit_json", sa.JSON(), nullable=True),
        sa.Column("analysis_json", sa.JSON(), nullable=True),
        sa.Column("revision_json", sa.JSON(), nullable=True),
        sa.Column(
            "review_status", sa.String(16), nullable=False, server_default="pending"
        ),
        sa.Column(
            "generation_status",
            sa.String(16),
            nullable=False,
            server_default="generated",
        ),
        sa.Column("skill_version", sa.String(32), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("wp_post_id", sa.Integer(), nullable=True),
        sa.Column("wp_status", sa.String(16), nullable=True),
        sa.Column("published_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_scope_columns(),
        *_stamp_columns(),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_seo_items_review_status",
        ),
        sa.CheckConstraint(
            "generation_status IN ('queued', 'running', 'generated', 'failed')",
            name="ck_seo_items_generation_status",
        ),
        sa.CheckConstraint(
            "item_kind IN ('craft_story', 'material_explainer', 'testing', "
            "'buying_guide', 'wholesale_guide', 'brand_story')",
            name="ck_seo_items_kind",
        ),
        sa.CheckConstraint(
            "destination IN ('factory', 'posts')", name="ck_seo_items_destination"
        ),
    )
    op.create_index("ix_seo_items_topic", "seo_content_items", ["topic_id"])
    op.create_index("ix_seo_items_review", "seo_content_items", ["review_status"])
    op.create_index("ix_seo_items_wp_post", "seo_content_items", ["wp_post_id"])

    op.create_table(
        "seo_generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "topic_id",
            sa.Uuid(),
            sa.ForeignKey("seo_topics.id", name="fk_seo_generation_jobs_topic_id"),
            nullable=False,
        ),
        sa.Column("job_kind", sa.String(32), nullable=False, server_default="generate"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by_username", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_scope_columns(),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed')",
            name="ck_seo_generation_jobs_status",
        ),
    )
    op.create_index(
        "ix_seo_generation_jobs_status", "seo_generation_jobs", ["status"]
    )

    op.create_table(
        "seo_publish_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.String(64), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False, server_default="wordpress"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("item_ids_json", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_username", sa.String(128), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_scope_columns(),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name="ck_seo_publish_jobs_status",
        ),
        sa.UniqueConstraint("job_id", name="uq_seo_publish_jobs_job_id"),
    )
    op.create_index("ix_seo_publish_jobs_status", "seo_publish_jobs", ["status"])

    op.create_table(
        "seo_radar_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("seed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planner_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "geo_blocked_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("notes_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_username", sa.String(128), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_scope_columns(),
        *_stamp_columns(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'failed')",
            name="ck_seo_radar_runs_status",
        ),
    )

    op.create_table(
        "seo_wp_category_map",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("destination", sa.String(16), nullable=False),
        sa.Column("wp_term_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_seo_wp_category_map_name"),
    )
    op.create_index(
        "ix_seo_wp_category_map_destination", "seo_wp_category_map", ["destination"]
    )

    # SEO 的关键词监测与 GEO 的买家问句监测共用一张表,加一列区分来源。
    op.add_column(
        "geo_monitor_questions",
        sa.Column(
            "kind", sa.String(32), nullable=False, server_default="geo_question"
        ),
    )


def downgrade() -> None:
    op.drop_column("geo_monitor_questions", "kind")
    op.drop_index("ix_seo_wp_category_map_destination", "seo_wp_category_map")
    op.drop_table("seo_wp_category_map")
    op.drop_table("seo_radar_runs")
    op.drop_index("ix_seo_publish_jobs_status", "seo_publish_jobs")
    op.drop_table("seo_publish_jobs")
    op.drop_index("ix_seo_generation_jobs_status", "seo_generation_jobs")
    op.drop_table("seo_generation_jobs")
    for name in ("ix_seo_items_wp_post", "ix_seo_items_review", "ix_seo_items_topic"):
        op.drop_index(name, "seo_content_items")
    op.drop_table("seo_content_items")
    for name in ("ix_seo_topics_norm", "ix_seo_topics_audience", "ix_seo_topics_status"):
        op.drop_index(name, "seo_topics")
    op.drop_table("seo_topics")
