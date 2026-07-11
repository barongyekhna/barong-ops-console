"""Private persistence schema for C19 records, receipts, and event cursors."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
            "content_type in ('text', 'emoji')", name="content_type_supported"
        ),
        Index(
            "ix_chat_records_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("ix_chat_records_created_at", "created_at"),
    )


class RecordIdempotencyLedger(Base):
    """Permanent, body-free sender key ledger that survives record deletion."""

    __tablename__ = "record_idempotency_ledger"

    sender_user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
