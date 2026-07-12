"""Private persistence schema for C19 records, receipts, and event cursors."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UTCDateTime


class ConversationSequence(Base):
    __tablename__ = "record_conversation_sequences"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),
    )


class UserEventSequence(Base):
    __tablename__ = "record_user_event_sequences"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),
    )


class ChatRecord(Base):
    __tablename__ = "chat_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sender_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_user_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sender_org_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recipient_org_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    record_metadata: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "sender_user_id",
            "client_message_id",
            name="uq_chat_records_sender_client_message",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_chat_records_conversation_sequence",
        ),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "content_type in ('text', 'emoji', 'image', 'file')",
            name="content_type_supported",
        ),
        Index(
            "ix_chat_records_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("ix_chat_records_created_at", "created_at"),
    )


class RecordAssetReference(Base):
    """Immutable asset metadata; file bytes and provider locators live elsewhere."""

    __tablename__ = "record_asset_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_asset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "record_id",
            "ordinal",
            name="uq_record_asset_references_record_ordinal",
        ),
        UniqueConstraint(
            "record_id",
            "asset_id",
            name="uq_record_asset_references_record_asset",
        ),
        CheckConstraint("kind in ('image', 'file')", name="kind_supported"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        Index("ix_record_asset_references_asset_id", "asset_id"),
    )


class RecordIdempotencyLedger(Base):
    """Permanent, body-free sender key ledger that survives record deletion."""

    __tablename__ = "record_idempotency_ledger"

    sender_user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "record_id", name="uq_record_idempotency_ledger_record_id"
        ),
        CheckConstraint(
            "status in ('active', 'deleted')", name="status_supported"
        ),
        CheckConstraint(
            "intent_version in (1, 2)", name="intent_version_supported"
        ),
        CheckConstraint(
            "sequence is null or sequence > 0", name="sequence_positive"
        ),
        CheckConstraint(
            "(status = 'active' and deleted_at is null and "
            "intent_sha256 is not null) or "
            "(status = 'deleted' and deleted_at is not null and "
            "record_id is null and intent_sha256 is null)",
            name="deletion_state_consistent",
        ),
        Index(
            "ix_record_idempotency_ledger_conversation_sequence",
            "conversation_id",
            "sequence",
        ),
    )


class ParticipantPosition(Base):
    __tablename__ = "chat_participant_positions"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    delivered_through_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    read_through_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "delivered_through_sequence >= 0",
            name="delivered_sequence_nonnegative",
        ),
        CheckConstraint(
            "read_through_sequence >= 0", name="read_sequence_nonnegative"
        ),
        CheckConstraint(
            "read_through_sequence <= delivered_through_sequence",
            name="read_not_ahead_of_delivery",
        ),
        Index("ix_chat_participant_positions_user", "user_id"),
    )


class UserRecordEvent(Base):
    __tablename__ = "chat_user_record_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_sequence",
            name="uq_chat_user_record_events_user_sequence",
        ),
        UniqueConstraint(
            "user_id", "record_id", name="uq_chat_user_record_events_user_record"
        ),
        Index(
            "ix_chat_user_record_events_user_conversation_record",
            "user_id",
            "conversation_id",
            "record_sequence",
        ),
        Index("ix_chat_user_record_events_record_id", "record_id"),
    )


class RecordMutationAudit(Base):
    __tablename__ = "record_mutation_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    delete_before: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    target_record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    maximum_records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("affected_count >= 0", name="affected_count_nonnegative"),
        Index("ix_record_mutation_audits_completed_at", "completed_at"),
    )


class RecordAssetCoordination(Base):
    """Permanent per-asset transaction fence shared by every reference writer."""

    __tablename__ = "record_asset_coordination"

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RecordAssetDeletionOutbox(Base):
    """Content-free, durable handoff from Record retention to Asset deletion.

    One row is retained for every removed record/asset reference.  Jobs are not
    eligible for delivery while the asset identifier is still referenced by a
    surviving chat record or Moment.  Keeping every historical binding makes a
    shared-reference anomaly recoverable: once the last live reference goes
    away, the Asset Service can accept the one job matching its authoritative
    committed binding and safely protect the others.
    """

    __tablename__ = "record_asset_deletion_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_operation_id: Mapped[str | None] = mapped_column(
        String(68),
        ForeignKey("record_retention_operations.operation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "record_id",
            "asset_id",
            name="uq_record_asset_deletion_outbox_record_asset",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "state in ('pending','authorized','completed','protected')",
            name="state_supported",
        ),
        CheckConstraint(
            "outcome is null or outcome in ('accepted','protected')",
            name="outcome_supported",
        ),
        CheckConstraint(
            "((lease_owner is null and lease_until is null) or "
            "(lease_owner is not null and lease_until is not null))",
            name="lease_pair_consistent",
        ),
        CheckConstraint(
            "(state in ('pending','authorized') and outcome is null and completed_at is null) or "
            "(state = 'completed' and outcome = 'accepted' and "
            "completed_at is not null and lease_owner is null and lease_until is null) or "
            "(state = 'protected' and outcome = 'protected' and "
            "completed_at is not null and lease_owner is null and lease_until is null)",
            name="completion_consistent",
        ),
        CheckConstraint(
            "(state = 'pending' and authorized_at is null) or "
            "(state in ('authorized','completed') and authorized_at is not null) or "
            "state = 'protected'",
            name="authorization_consistent",
        ),
        Index(
            "ix_record_asset_deletion_outbox_state_created",
            "state",
            "created_at",
        ),
        Index(
            "ix_record_asset_deletion_outbox_asset_state",
            "asset_id",
            "state",
        ),
        Index("ix_record_asset_deletion_outbox_lease_until", "lease_until"),
        Index("ix_record_asset_deletion_outbox_authorized_at", "authorized_at"),
        Index(
            "ix_record_asset_deletion_outbox_retention_operation",
            "retention_operation_id",
            "state",
        ),
    )


class RecordRetentionOperation(Base):
    """Stable policy ledger enforcing one hard cap across retries and batches."""

    __tablename__ = "record_retention_operations"

    operation_id: Mapped[str] = mapped_column(String(68), primary_key=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    delete_before: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_maximum_records: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_maximum_asset_jobs: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asset_jobs_enqueued_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    asset_jobs_completed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    next_batch_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "approved_maximum_records between 1 and 100000",
            name="approved_maximum_supported",
        ),
        CheckConstraint("affected_count >= 0", name="affected_count_nonnegative"),
        CheckConstraint(
            "approved_maximum_asset_jobs between 1 and 100000",
            name="approved_asset_maximum_supported",
        ),
        CheckConstraint(
            "asset_jobs_enqueued_count between 0 and approved_maximum_asset_jobs",
            name="asset_jobs_enqueued_within_maximum",
        ),
        CheckConstraint(
            "asset_jobs_completed_count between 0 and asset_jobs_enqueued_count",
            name="asset_jobs_completed_within_enqueued",
        ),
        CheckConstraint(
            "affected_count <= approved_maximum_records",
            name="affected_within_approved_maximum",
        ),
        CheckConstraint(
            "next_batch_ordinal >= 0", name="next_batch_ordinal_nonnegative"
        ),
        Index("ix_record_retention_operations_completed_at", "completed_at"),
    )


class RecordRetentionBatch(Base):
    """Exact replay result for one ordinal in a retention operation."""

    __tablename__ = "record_retention_batches"

    operation_id: Mapped[str] = mapped_column(
        String(68),
        ForeignKey("record_retention_operations.operation_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    batch_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    maximum_records: Mapped[int] = mapped_column(Integer, nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("batch_ordinal >= 0", name="batch_ordinal_nonnegative"),
        CheckConstraint(
            "maximum_records between 1 and 1000", name="maximum_records_supported"
        ),
        CheckConstraint(
            "affected_count between 0 and maximum_records",
            name="affected_within_batch_maximum",
        ),
        CheckConstraint(
            "cumulative_affected_count >= affected_count",
            name="cumulative_count_consistent",
        ),
    )


class MomentFeedSequence(Base):
    """Single monotonic sequence used for stable, integer feed cursors."""

    __tablename__ = "moment_feed_sequence"

    singleton_key: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint("singleton_key = 'primary'", name="singleton_key_primary"),
        CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),
    )


class Moment(Base):
    """Content-bearing Moment authority; Barong owns current social policy."""

    __tablename__ = "moments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_moment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    author_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    author_org_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    audience_org_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    feed_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_like_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    last_comment_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    publish_intent_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    publish_intent_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    delete_pending_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "author_user_id",
            "client_moment_id",
            name="uq_moments_author_client_moment",
        ),
        UniqueConstraint("feed_sequence", name="uq_moments_feed_sequence"),
        CheckConstraint(
            "state in ('draft','published','delete_pending','deleted')",
            name="state_supported",
        ),
        CheckConstraint(
            "visibility in ('public','org','friends','private')",
            name="visibility_supported",
        ),
        CheckConstraint("like_count >= 0", name="like_count_nonnegative"),
        CheckConstraint("comment_count >= 0", name="comment_count_nonnegative"),
        CheckConstraint(
            "last_like_sequence >= 0", name="last_like_sequence_nonnegative"
        ),
        CheckConstraint(
            "last_comment_sequence >= 0",
            name="last_comment_sequence_nonnegative",
        ),
        CheckConstraint(
            "publish_intent_version = 1", name="publish_intent_version_supported"
        ),
        CheckConstraint(
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
            name="lifecycle_consistent",
        ),
        Index("ix_moments_state_feed_sequence", "state", "feed_sequence"),
        Index("ix_moments_author_state", "author_user_id", "state"),
        Index("ix_moments_published_at", "published_at"),
    )


class MomentAudienceSnapshot(Base):
    """Immutable publish-time audience ceiling for one Moment."""

    __tablename__ = "moment_audience_snapshots"

    moment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        Index("ix_moment_audience_snapshots_user_moment", "user_id", "moment_id"),
    )


class MomentAssetReference(Base):
    """Immutable image snapshot; bytes and locators stay in the Asset Service."""

    __tablename__ = "moment_asset_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    moment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    client_asset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "moment_id", "asset_id", name="uq_moment_asset_references_moment_asset"
        ),
        UniqueConstraint(
            "moment_id", "ordinal", name="uq_moment_asset_references_moment_ordinal"
        ),
        CheckConstraint("kind = 'image'", name="kind_image_only"),
        CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("ordinal between 0 and 8", name="ordinal_supported"),
        Index("ix_moment_asset_references_asset_id", "asset_id"),
    )


class MomentLike(Base):
    __tablename__ = "moment_likes"

    moment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "moment_id", "sequence", name="uq_moment_likes_moment_sequence"
        ),
        CheckConstraint("status in ('active','removed')", name="status_supported"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "(status = 'active' and removed_at is null) or "
            "(status = 'removed' and removed_at is not null)",
            name="lifecycle_consistent",
        ),
        Index("ix_moment_likes_user_status", "user_id", "status"),
    )


class MomentComment(Base):
    __tablename__ = "moment_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_comment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    moment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "author_user_id",
            "client_comment_id",
            name="uq_moment_comments_author_client_comment",
        ),
        UniqueConstraint(
            "moment_id", "sequence", name="uq_moment_comments_moment_sequence"
        ),
        CheckConstraint("status in ('active','deleted')", name="status_supported"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "(status = 'active' and content is not null and intent_sha256 is not null "
            "and deleted_at is null) or "
            "(status = 'deleted' and content is null and intent_sha256 is null "
            "and deleted_at is not null)",
            name="lifecycle_consistent",
        ),
        Index("ix_moment_comments_moment_status_sequence", "moment_id", "status", "sequence"),
        Index("ix_moment_comments_author_status", "author_user_id", "status"),
    )


class MomentUserEvent(Base):
    """Content-free Moment notification/reconnect event."""

    __tablename__ = "moment_user_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    moment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    comment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_sequence",
            name="uq_moment_user_events_user_sequence",
        ),
        CheckConstraint(
            "event_type in ('moment_published','moment_deleted','moment_liked',"
            "'moment_unliked','moment_commented','moment_comment_deleted')",
            name="event_type_supported",
        ),
        CheckConstraint(
            "(event_type in ('moment_commented','moment_comment_deleted') "
            "and comment_id is not null) or "
            "(event_type not in ('moment_commented','moment_comment_deleted') "
            "and comment_id is null)",
            name="comment_reference_consistent",
        ),
        Index("ix_moment_user_events_user_sequence", "user_id", "event_sequence"),
        Index("ix_moment_user_events_moment", "moment_id"),
    )
