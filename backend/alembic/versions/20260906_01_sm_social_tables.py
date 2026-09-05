"""SM 系列社媒运营表（sm.social）。

七张表，全部按 workspace_key / business_context / scope_mode 分区（与 K/GEO 同一套
apply_scope_filters）。sm_posts 多带 wp_post_id / wp_status / published_url /
published_at 四列恒空：内容台 to_article 通读这些属性，第三源头「加一行」才成立。

纯增量：只建新表，不动现有表。

Revision ID: 20260906_01_sm_social_tables
Revises: 20260905_01_w_traffic
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260906_01_sm_social_tables"
down_revision = "20260905_01_w_traffic"
branch_labels = None
depends_on = None

TABLES = (
    "sm_generation_jobs",
    "sm_rejections",
    "sm_image_requests",
    "sm_media_usage",
    "sm_posts",
    "sm_calendar_slots",
    "sm_channels",
)


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT to_regclass(%(n)s) IS NOT NULL", {"n": f"public.{name}"}
        ).scalar()
    )


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("workspace_key", sa.String(length=128), nullable=False, server_default="default_independent_store"),
        sa.Column("business_context", sa.String(length=128), nullable=False, server_default="independent_store"),
        sa.Column("scope_mode", sa.String(length=64), nullable=False, server_default="adapter_pending"),
    ]


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "sm_channels"):
        op.create_table(
            "sm_channels",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("handle", sa.String(length=255), nullable=True),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("key_alias", sa.String(length=128), nullable=True),
            sa.Column("profile_version", sa.String(length=64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            *_stamps(),
            sa.UniqueConstraint("workspace_key", "platform", name="uq_sm_channels_ws_platform"),
        )

    if not _table_exists(conn, "sm_calendar_slots"):
        op.create_table(
            "sm_calendar_slots",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("slot_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("window_pt", sa.String(length=16), nullable=True),
            sa.Column("pillar", sa.String(length=4), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_type", sa.String(length=32), nullable=False, server_default="none"),
            sa.Column("source_id", sa.Uuid(), nullable=True),
            sa.Column("seed_product_id", sa.Uuid(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="planned"),
            sa.Column("swap_reason", sa.Text(), nullable=True),
            sa.Column("post_id", sa.Uuid(), nullable=True),
            sa.Column("media_plan_json", _json(), nullable=True),
            sa.Column("planner_version", sa.String(length=64), nullable=False),
            sa.Column("plan_run_id", sa.Uuid(), nullable=True),
            *_stamps(),
            sa.UniqueConstraint(
                "workspace_key", "day", "platform", "slot_index", name="uq_sm_slots_ws_day_platform_idx"
            ),
        )
        op.create_index("ix_sm_slots_ws_day", "sm_calendar_slots", ["workspace_key", "day"])
        op.create_index("ix_sm_slots_status", "sm_calendar_slots", ["status"])

    if not _table_exists(conn, "sm_posts"):
        op.create_table(
            "sm_posts",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column(
                "slot_id",
                sa.Uuid(),
                sa.ForeignKey("sm_calendar_slots.id", name="fk_sm_posts_slot_id_slots", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("post_kind", sa.String(length=32), nullable=False),
            sa.Column("pillar", sa.String(length=4), nullable=False),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=True),
            sa.Column("seed_product_id", sa.Uuid(), nullable=True),
            sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("first_line", sa.String(length=512), nullable=True),
            sa.Column("caption", sa.Text(), nullable=True),
            sa.Column("alt_text", sa.String(length=255), nullable=True),
            sa.Column("hashtags_json", _json(), nullable=True),
            sa.Column("board", sa.String(length=255), nullable=True),
            sa.Column("link_url", sa.String(length=2048), nullable=True),
            sa.Column("media_refs_json", _json(), nullable=True),
            sa.Column("keyword_primary", sa.String(length=255), nullable=True),
            sa.Column("keywords_secondary_json", _json(), nullable=True),
            sa.Column("cta", sa.String(length=255), nullable=True),
            sa.Column("facts_used_json", _json(), nullable=True),
            sa.Column("body_json", _json(), nullable=True),
            sa.Column("seo_json", _json(), nullable=True),
            sa.Column("brand_audit_json", _json(), nullable=True),
            sa.Column("analysis_json", _json(), nullable=True),
            sa.Column("revision_json", _json(), nullable=True),
            sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("generation_status", sa.String(length=20), nullable=False, server_default="draft"),
            sa.Column("publish_status", sa.String(length=20), nullable=False, server_default="manual"),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("permalink", sa.String(length=2048), nullable=True),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("wp_post_id", sa.Integer(), nullable=True),
            sa.Column("wp_status", sa.String(length=20), nullable=True),
            sa.Column("published_url", sa.String(length=2048), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("skill_version", sa.String(length=64), nullable=True),
            sa.Column("provider", sa.String(length=50), nullable=True),
            sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_sm_posts_ws_review", "sm_posts", ["workspace_key", "review_status"])
        op.create_index("ix_sm_posts_slot", "sm_posts", ["slot_id"])
        op.create_index("ix_sm_posts_platform", "sm_posts", ["platform"])

    if not _table_exists(conn, "sm_media_usage"):
        op.create_table(
            "sm_media_usage",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("asset_id", sa.Uuid(), nullable=False),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("post_id", sa.Uuid(), nullable=True),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("workspace_key", "asset_id", "platform", name="uq_sm_media_usage_ws_asset_platform"),
        )

    if not _table_exists(conn, "sm_image_requests"):
        op.create_table(
            "sm_image_requests",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("slot_id", sa.Uuid(), nullable=True),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=True),
            sa.Column("seed_product_id", sa.Uuid(), nullable=True),
            sa.Column("pillar", sa.String(length=4), nullable=False),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("ratio", sa.String(length=8), nullable=False, server_default="2:3"),
            sa.Column("lane", sa.String(length=16), nullable=False),
            sa.Column("k_position", sa.Integer(), nullable=True),
            sa.Column("due_day", sa.Date(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("filled_asset_id", sa.Uuid(), nullable=True),
            sa.Column("brief_text", sa.Text(), nullable=True),
            sa.Column("prompt_text", sa.Text(), nullable=True),
            sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_sm_image_requests_ws_status", "sm_image_requests", ["workspace_key", "status"])
        op.create_index("ix_sm_image_requests_product", "sm_image_requests", ["seed_product_id"])

    if not _table_exists(conn, "sm_rejections"):
        op.create_table(
            "sm_rejections",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("post_id", sa.Uuid(), nullable=True),
            sa.Column("object", sa.String(length=16), nullable=False),
            sa.Column("asset_id", sa.Uuid(), nullable=True),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("pillar", sa.String(length=4), nullable=False),
            sa.Column("reason_code", sa.String(length=32), nullable=False),
            sa.Column("replacement_asset_id", sa.Uuid(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index(
            "ix_sm_rejections_ws_platform_pillar", "sm_rejections", ["workspace_key", "platform", "pillar"]
        )

    if not _table_exists(conn, "sm_generation_jobs"):
        op.create_table(
            "sm_generation_jobs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            *_scope_columns(),
            sa.Column("slot_id", sa.Uuid(), nullable=True),
            sa.Column("post_id", sa.Uuid(), nullable=True),
            sa.Column("job_type", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("requested_by_username", sa.String(length=150), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_sm_jobs_status_created", "sm_generation_jobs", ["status", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    for name in TABLES:
        if _table_exists(conn, name):
            op.drop_table(name)
