"""Provider-neutral metadata schema; file bytes never enter these tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UTCDateTime


ASSET_STATES = (
    "pending_upload",
    "uploaded",
    "scanning",
    "active",
    "rejected",
    "quarantined",
    "delete_pending",
    "deleted",
    "expired",
)

ASSET_USAGES = ("chat_message", "moment_image")


class DatasetIdentity(Base):
    __tablename__ = "asset_dataset_identity"

    singleton_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    blob_format_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("singleton_key = 'primary'", name="singleton_key_primary"),
        CheckConstraint("blob_format_revision > 0", name="blob_revision_positive"),
    )


class Asset(Base):
    __tablename__ = "chat_assets"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_asset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    usage: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)

    # Cleared on the permanent body-free tombstone.
    intent_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    declared_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    declared_sha256_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)

    actual_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_sha256_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)
    incoming_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    active_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    quarantine_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    thumbnail_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    thumbnail_sha256_hex: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_media_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    binding_status: Mapped[str] = mapped_column(String(12), nullable=False)
    binding_client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bound_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    prepared_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    retention_operation_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    retention_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    retention_conversation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    retention_prepared_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "client_asset_id", name="uq_asset_owner_client_id"
        ),
        CheckConstraint(
            "usage in ('chat_message', 'moment_image')", name="usage_supported"
        ),
        CheckConstraint("length(scope_id) > 0", name="scope_id_not_blank"),
        CheckConstraint("kind in ('image', 'file')", name="kind_supported"),
        CheckConstraint(
            "usage <> 'moment_image' or kind = 'image'",
            name="moment_usage_requires_image",
        ),
        CheckConstraint(
            "status in ('pending_upload','uploaded','scanning','active','rejected',"
            "'quarantined','delete_pending','deleted','expired')",
            name="status_supported",
        ),
        CheckConstraint(
            "binding_status in ('unbound','prepared','committed')",
            name="binding_status_supported",
        ),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "declared_size_bytes is null or declared_size_bytes > 0",
            name="declared_size_positive",
        ),
        CheckConstraint(
            "actual_size_bytes is null or actual_size_bytes > 0",
            name="actual_size_positive",
        ),
        CheckConstraint(
            "(binding_status = 'unbound' and binding_client_id is null and bound_resource_id is null)"
            " or (binding_status = 'prepared' and binding_client_id is not null and bound_resource_id is null)"
            " or (binding_status = 'committed' and binding_client_id is not null and bound_resource_id is not null)",
            name="binding_consistent",
        ),
        CheckConstraint(
            "usage <> 'moment_image' or binding_status <> 'committed' "
            "or bound_resource_id = scope_id",
            name="moment_binding_matches_scope",
        ),
        CheckConstraint(
            "(status = 'deleted' and deleted_at is not null and intent_sha256 is null "
            "and filename is null and declared_sha256_hex is null and actual_sha256_hex is null "
            "and incoming_object_key is null and active_object_key is null "
            "and quarantine_object_key is null and thumbnail_object_key is null)"
            " or status <> 'deleted'",
            name="deleted_tombstone_body_free",
        ),
        CheckConstraint(
            "(retention_operation_id is null and retention_record_id is null "
            "and retention_conversation_id is null and retention_prepared_at is null) "
            "or (retention_operation_id is not null and retention_record_id is not null "
            "and retention_conversation_id is not null and retention_prepared_at is not null)",
            name="retention_preparation_consistent",
        ),
        UniqueConstraint(
            "retention_operation_id", name="uq_chat_assets_retention_operation_id"
        ),
        Index("ix_chat_assets_owner_status", "owner_user_id", "status"),
        Index("ix_chat_assets_worker_status_updated", "status", "updated_at"),
        Index(
            "ix_chat_assets_usage_scope_binding",
            "usage",
            "scope_id",
            "bound_resource_id",
        ),
        Index("ix_chat_assets_retention_prepared_at", "retention_prepared_at"),
    )

    # Read-only compatibility spellings for tests and operational diagnostics.
    # They are not persisted columns and are deliberately unavailable for
    # Moment assets, so new code cannot accidentally treat a Moment as chat.
    @property
    def conversation_id(self) -> str | None:
        return self.scope_id if self.usage == "chat_message" else None

    @property
    def client_message_id(self) -> str | None:
        return self.binding_client_id if self.usage == "chat_message" else None

    @property
    def record_id(self) -> str | None:
        return self.bound_resource_id if self.usage == "chat_message" else None


class TransferTicket(Base):
    __tablename__ = "asset_transfer_tickets"

    ticket_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reader_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    usage: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bound_resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(12), nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(12), nullable=True)
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        CheckConstraint("direction in ('upload','download')", name="direction_supported"),
        CheckConstraint(
            "usage in ('chat_message', 'moment_image')", name="usage_supported"
        ),
        CheckConstraint("length(scope_id) > 0", name="scope_id_not_blank"),
        CheckConstraint("max_uses > 0", name="max_uses_positive"),
        CheckConstraint("used_count >= 0", name="used_count_nonnegative"),
        CheckConstraint("used_count <= max_uses", name="uses_within_limit"),
        CheckConstraint("asset_version > 0", name="asset_version_positive"),
        CheckConstraint(
            "(direction = 'upload' and reader_user_id is null and bound_resource_id is null "
            "and variant is null and disposition is null) or "
            "(direction = 'download' and reader_user_id is not null and bound_resource_id is not null "
            "and variant in ('original','thumbnail') and disposition in ('attachment','inline'))",
            name="direction_fields_consistent",
        ),
        CheckConstraint(
            "usage <> 'moment_image' or direction <> 'download' "
            "or bound_resource_id = scope_id",
            name="moment_download_matches_scope",
        ),
        Index("ix_asset_transfer_tickets_asset_direction", "asset_id", "direction"),
        Index("ix_asset_transfer_tickets_expires_at", "expires_at"),
    )

    @property
    def conversation_id(self) -> str | None:
        return self.scope_id if self.usage == "chat_message" else None

    @property
    def record_id(self) -> str | None:
        return self.bound_resource_id if self.usage == "chat_message" else None


class AssetAuditEvent(Base):
    """Content-free lifecycle audit; never stores filenames, tokens, or object keys."""

    __tablename__ = "asset_audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_assets.asset_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "actor_type in ('barong','gateway','worker','system')",
            name="actor_type_supported",
        ),
        Index("ix_asset_audit_events_asset_occurred", "asset_id", "occurred_at"),
    )
