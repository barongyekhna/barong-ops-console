"""Create the standalone C19 asset metadata schema.

Revision ID: c19_asset_20260711_01
Revises:
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_asset_20260711_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_dataset_identity",
        sa.Column("singleton_key", sa.String(length=16), nullable=False),
        sa.Column("dataset_id", sa.String(length=128), nullable=False),
        sa.Column("blob_format_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "blob_format_revision > 0",
            name=op.f("ck_asset_dataset_identity_blob_revision_positive"),
        ),
        sa.CheckConstraint(
            "singleton_key = 'primary'",
            name=op.f("ck_asset_dataset_identity_singleton_key_primary"),
        ),
        sa.PrimaryKeyConstraint(
            "singleton_key", name=op.f("pk_asset_dataset_identity")
        ),
        sa.UniqueConstraint(
            "dataset_id", name=op.f("uq_asset_dataset_identity_dataset_id")
        ),
    )
    op.create_table(
        "chat_assets",
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("client_asset_id", sa.String(length=128), nullable=False),
        sa.Column("owner_user_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("intent_sha256", sa.String(length=64), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=128), nullable=True),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("declared_sha256_hex", sa.String(length=64), nullable=True),
        sa.Column("actual_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("actual_sha256_hex", sa.String(length=64), nullable=True),
        sa.Column("incoming_object_key", sa.String(length=256), nullable=True),
        sa.Column("active_object_key", sa.String(length=256), nullable=True),
        sa.Column("quarantine_object_key", sa.String(length=256), nullable=True),
        sa.Column("thumbnail_object_key", sa.String(length=256), nullable=True),
        sa.Column("thumbnail_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("thumbnail_sha256_hex", sa.String(length=64), nullable=True),
        sa.Column("thumbnail_media_type", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("binding_status", sa.String(length=12), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=True),
        sa.Column("record_id", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=48), nullable=True),
        sa.CheckConstraint(
            "actual_size_bytes is null or actual_size_bytes > 0",
            name=op.f("ck_chat_assets_actual_size_positive"),
        ),
        sa.CheckConstraint(
            "(binding_status = 'unbound' and client_message_id is null and record_id is null)"
            " or (binding_status = 'prepared' and client_message_id is not null and record_id is null)"
            " or (binding_status = 'committed' and client_message_id is not null and record_id is not null)",
            name=op.f("ck_chat_assets_binding_consistent"),
        ),
        sa.CheckConstraint(
            "binding_status in ('unbound','prepared','committed')",
            name=op.f("ck_chat_assets_binding_status_supported"),
        ),
        sa.CheckConstraint(
            "declared_size_bytes is null or declared_size_bytes > 0",
            name=op.f("ck_chat_assets_declared_size_positive"),
        ),
        sa.CheckConstraint(
            "(status = 'deleted' and deleted_at is not null and intent_sha256 is null "
            "and filename is null and declared_sha256_hex is null and actual_sha256_hex is null "
            "and incoming_object_key is null and active_object_key is null "
            "and quarantine_object_key is null and thumbnail_object_key is null)"
            " or status <> 'deleted'",
            name=op.f("ck_chat_assets_deleted_tombstone_body_free"),
        ),
        sa.CheckConstraint(
            "kind in ('image', 'file')",
            name=op.f("ck_chat_assets_kind_supported"),
        ),
        sa.CheckConstraint(
            "status in ('pending_upload','uploaded','scanning','active','rejected',"
            "'quarantined','delete_pending','deleted','expired')",
            name=op.f("ck_chat_assets_status_supported"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_chat_assets_version_positive")
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_chat_assets")),
        sa.UniqueConstraint(
            "owner_user_id", "client_asset_id", name="uq_asset_owner_client_id"
        ),
    )
    op.create_index(
        "ix_chat_assets_owner_status",
        "chat_assets",
        ["owner_user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_chat_assets_record_id", "chat_assets", ["record_id"], unique=False
    )
    op.create_index(
        "ix_chat_assets_worker_status_updated",
        "chat_assets",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_table(
        "asset_audit_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type in ('barong','gateway','worker','system')",
            name=op.f("ck_asset_audit_events_actor_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["chat_assets.asset_id"],
            name=op.f("fk_asset_audit_events_asset_id_chat_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_asset_audit_events")),
    )
    op.create_index(
        "ix_asset_audit_events_asset_occurred",
        "asset_audit_events",
        ["asset_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "asset_transfer_tickets",
        sa.Column("ticket_id", sa.String(length=36), nullable=False),
        sa.Column("ticket_sha256", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("owner_user_id", sa.String(length=128), nullable=False),
        sa.Column("reader_user_id", sa.String(length=128), nullable=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("record_id", sa.String(length=64), nullable=True),
        sa.Column("variant", sa.String(length=12), nullable=True),
        sa.Column("disposition", sa.String(length=12), nullable=True),
        sa.Column("asset_version", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "asset_version > 0",
            name=op.f("ck_asset_transfer_tickets_asset_version_positive"),
        ),
        sa.CheckConstraint(
            "direction in ('upload','download')",
            name=op.f("ck_asset_transfer_tickets_direction_supported"),
        ),
        sa.CheckConstraint(
            "(direction = 'upload' and reader_user_id is null and record_id is null "
            "and variant is null and disposition is null) or "
            "(direction = 'download' and reader_user_id is not null and record_id is not null "
            "and variant in ('original','thumbnail') and disposition in ('attachment','inline'))",
            name=op.f("ck_asset_transfer_tickets_direction_fields_consistent"),
        ),
        sa.CheckConstraint(
            "max_uses > 0",
            name=op.f("ck_asset_transfer_tickets_max_uses_positive"),
        ),
        sa.CheckConstraint(
            "used_count >= 0",
            name=op.f("ck_asset_transfer_tickets_used_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "used_count <= max_uses",
            name=op.f("ck_asset_transfer_tickets_uses_within_limit"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["chat_assets.asset_id"],
            name=op.f("fk_asset_transfer_tickets_asset_id_chat_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "ticket_id", name=op.f("pk_asset_transfer_tickets")
        ),
        sa.UniqueConstraint(
            "ticket_sha256",
            name=op.f("uq_asset_transfer_tickets_ticket_sha256"),
        ),
    )
    op.create_index(
        "ix_asset_transfer_tickets_asset_direction",
        "asset_transfer_tickets",
        ["asset_id", "direction"],
        unique=False,
    )
    op.create_index(
        "ix_asset_transfer_tickets_expires_at",
        "asset_transfer_tickets",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_asset_transfer_tickets_expires_at",
        table_name="asset_transfer_tickets",
    )
    op.drop_index(
        "ix_asset_transfer_tickets_asset_direction",
        table_name="asset_transfer_tickets",
    )
    op.drop_table("asset_transfer_tickets")
    op.drop_index(
        "ix_asset_audit_events_asset_occurred", table_name="asset_audit_events"
    )
    op.drop_table("asset_audit_events")
    op.drop_index("ix_chat_assets_worker_status_updated", table_name="chat_assets")
    op.drop_index("ix_chat_assets_record_id", table_name="chat_assets")
    op.drop_index("ix_chat_assets_owner_status", table_name="chat_assets")
    op.drop_table("chat_assets")
    op.drop_table("asset_dataset_identity")
