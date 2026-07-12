"""Add the Stage 5 Moments content domain.

Revision ID: c19_record_20260712_03
Revises: c19_record_20260711_02
Create Date: 2026-07-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_record_20260712_03"
down_revision: str | None = "c19_record_20260711_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "moment_feed_sequence",
        sa.Column("singleton_key", sa.String(length=16), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "singleton_key = 'primary'",
            name=op.f("ck_moment_feed_sequence_singleton_key_primary"),
        ),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name=op.f("ck_moment_feed_sequence_last_sequence_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "singleton_key", name=op.f("pk_moment_feed_sequence")
        ),
    )
    op.create_table(
        "moments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_moment_id", sa.String(length=128), nullable=False),
        sa.Column("author_user_id", sa.String(length=128), nullable=False),
        sa.Column("author_org_id", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("audience_org_ids", sa.JSON(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("feed_sequence", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("last_like_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_comment_sequence", sa.BigInteger(), nullable=False),
        sa.Column("publish_intent_sha256", sa.String(length=64), nullable=True),
        sa.Column("publish_intent_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_pending_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state in ('draft','published','delete_pending','deleted')",
            name=op.f("ck_moments_state_supported"),
        ),
        sa.CheckConstraint(
            "visibility in ('public','org','friends','private')",
            name=op.f("ck_moments_visibility_supported"),
        ),
        sa.CheckConstraint(
            "like_count >= 0", name=op.f("ck_moments_like_count_nonnegative")
        ),
        sa.CheckConstraint(
            "comment_count >= 0",
            name=op.f("ck_moments_comment_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "last_like_sequence >= 0",
            name=op.f("ck_moments_last_like_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "last_comment_sequence >= 0",
            name=op.f("ck_moments_last_comment_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "publish_intent_version = 1",
            name=op.f("ck_moments_publish_intent_version_supported"),
        ),
        sa.CheckConstraint(
            "(state = 'draft' and visibility = 'private' and content is null "
            "and feed_sequence is null and publish_intent_sha256 is null "
            "and published_at is null and delete_pending_at is null and deleted_at is null) "
            "or (state = 'published' and content is not null and feed_sequence is not null "
            "and publish_intent_sha256 is not null and published_at is not null "
            "and delete_pending_at is null and deleted_at is null) "
            "or (state = 'delete_pending' and content is null "
            "and publish_intent_sha256 is null and delete_pending_at is not null "
            "and deleted_at is null) "
            "or (state = 'deleted' and content is null and publish_intent_sha256 is null "
            "and delete_pending_at is not null and deleted_at is not null)",
            name=op.f("ck_moments_lifecycle_consistent"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moments")),
        sa.UniqueConstraint(
            "author_user_id",
            "client_moment_id",
            name="uq_moments_author_client_moment",
        ),
        sa.UniqueConstraint("feed_sequence", name="uq_moments_feed_sequence"),
    )
    op.create_index(
        "ix_moments_state_feed_sequence",
        "moments",
        ["state", "feed_sequence"],
        unique=False,
    )
    op.create_index(
        "ix_moments_author_state",
        "moments",
        ["author_user_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_moments_published_at", "moments", ["published_at"], unique=False
    )
    op.create_table(
        "moment_audience_snapshots",
        sa.Column("moment_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_audience_snapshots_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "moment_id", "user_id", name=op.f("pk_moment_audience_snapshots")
        ),
    )
    op.create_index(
        "ix_moment_audience_snapshots_user_moment",
        "moment_audience_snapshots",
        ["user_id", "moment_id"],
        unique=False,
    )
    op.create_table(
        "moment_asset_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("moment_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("client_asset_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind = 'image'", name=op.f("ck_moment_asset_references_kind_image_only")
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name=op.f("ck_moment_asset_references_size_bytes_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_moment_asset_references_version_positive"),
        ),
        sa.CheckConstraint(
            "ordinal between 0 and 8",
            name=op.f("ck_moment_asset_references_ordinal_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_asset_references_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moment_asset_references")),
        sa.UniqueConstraint(
            "moment_id",
            "asset_id",
            name="uq_moment_asset_references_moment_asset",
        ),
        sa.UniqueConstraint(
            "moment_id",
            "ordinal",
            name="uq_moment_asset_references_moment_ordinal",
        ),
    )
    op.create_index(
        "ix_moment_asset_references_asset_id",
        "moment_asset_references",
        ["asset_id"],
        unique=False,
    )
    op.create_table(
        "moment_likes",
        sa.Column("moment_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('active','removed')",
            name=op.f("ck_moment_likes_status_supported"),
        ),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_moment_likes_sequence_positive")
        ),
        sa.CheckConstraint(
            "(status = 'active' and removed_at is null) or "
            "(status = 'removed' and removed_at is not null)",
            name=op.f("ck_moment_likes_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_likes_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "moment_id", "user_id", name=op.f("pk_moment_likes")
        ),
        sa.UniqueConstraint(
            "moment_id", "sequence", name="uq_moment_likes_moment_sequence"
        ),
    )
    op.create_index(
        "ix_moment_likes_user_status",
        "moment_likes",
        ["user_id", "status"],
        unique=False,
    )
    op.create_table(
        "moment_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_comment_id", sa.String(length=128), nullable=False),
        sa.Column("moment_id", sa.String(length=36), nullable=False),
        sa.Column("author_user_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("intent_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('active','deleted')",
            name=op.f("ck_moment_comments_status_supported"),
        ),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_moment_comments_sequence_positive")
        ),
        sa.CheckConstraint(
            "(status = 'active' and content is not null and intent_sha256 is not null "
            "and deleted_at is null) or "
            "(status = 'deleted' and content is null and intent_sha256 is null "
            "and deleted_at is not null)",
            name=op.f("ck_moment_comments_lifecycle_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_comments_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moment_comments")),
        sa.UniqueConstraint(
            "author_user_id",
            "client_comment_id",
            name="uq_moment_comments_author_client_comment",
        ),
        sa.UniqueConstraint(
            "moment_id", "sequence", name="uq_moment_comments_moment_sequence"
        ),
    )
    op.create_index(
        "ix_moment_comments_moment_status_sequence",
        "moment_comments",
        ["moment_id", "status", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_moment_comments_author_status",
        "moment_comments",
        ["author_user_id", "status"],
        unique=False,
    )
    op.create_table(
        "moment_user_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("moment_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=128), nullable=False),
        sa.Column("comment_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type in ('moment_published','moment_deleted','moment_liked',"
            "'moment_unliked','moment_commented','moment_comment_deleted')",
            name=op.f("ck_moment_user_events_event_type_supported"),
        ),
        sa.CheckConstraint(
            "(event_type in ('moment_commented','moment_comment_deleted') "
            "and comment_id is not null) or "
            "(event_type not in ('moment_commented','moment_comment_deleted') "
            "and comment_id is null)",
            name=op.f("ck_moment_user_events_comment_reference_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["moment_id"],
            ["moments.id"],
            name=op.f("fk_moment_user_events_moment_id_moments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moment_user_events")),
        sa.UniqueConstraint(
            "user_id",
            "event_sequence",
            name="uq_moment_user_events_user_sequence",
        ),
    )
    op.create_index(
        "ix_moment_user_events_user_sequence",
        "moment_user_events",
        ["user_id", "event_sequence"],
        unique=False,
    )
    op.create_index(
        "ix_moment_user_events_moment",
        "moment_user_events",
        ["moment_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    protected_tables = (
        "moments",
        "moment_audience_snapshots",
        "moment_asset_references",
        "moment_likes",
        "moment_comments",
        "moment_user_events",
        "moment_feed_sequence",
    )
    populated = [
        table_name
        for table_name in protected_tables
        if connection.execute(
            sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")
        ).first()
        is not None
    ]
    if populated:
        raise RuntimeError(
            "Refusing to downgrade C19 Record v3 while Moment data exists in: "
            + ", ".join(populated)
        )

    op.drop_index("ix_moment_user_events_moment", table_name="moment_user_events")
    op.drop_index(
        "ix_moment_user_events_user_sequence", table_name="moment_user_events"
    )
    op.drop_table("moment_user_events")
    op.drop_index(
        "ix_moment_comments_author_status", table_name="moment_comments"
    )
    op.drop_index(
        "ix_moment_comments_moment_status_sequence", table_name="moment_comments"
    )
    op.drop_table("moment_comments")
    op.drop_index("ix_moment_likes_user_status", table_name="moment_likes")
    op.drop_table("moment_likes")
    op.drop_index(
        "ix_moment_asset_references_asset_id",
        table_name="moment_asset_references",
    )
    op.drop_table("moment_asset_references")
    op.drop_index(
        "ix_moment_audience_snapshots_user_moment",
        table_name="moment_audience_snapshots",
    )
    op.drop_table("moment_audience_snapshots")
    op.drop_index("ix_moments_published_at", table_name="moments")
    op.drop_index("ix_moments_author_state", table_name="moments")
    op.drop_index("ix_moments_state_feed_sequence", table_name="moments")
    op.drop_table("moments")
    op.drop_table("moment_feed_sequence")
