"""Create the standalone C19 record store schema.

Revision ID: c19_record_20260711_01
Revises:
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c19_record_20260711_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "record_conversation_sequences",
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name=op.f("ck_record_conversation_sequences_last_sequence_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id", name=op.f("pk_record_conversation_sequences")
        ),
    )
    op.create_table(
        "record_user_event_sequences",
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 0",
            name=op.f("ck_record_user_event_sequences_last_sequence_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", name=op.f("pk_record_user_event_sequences")
        ),
    )
    op.create_table(
        "chat_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.String(length=128), nullable=False),
        sa.Column("recipient_user_ids", sa.JSON(), nullable=False),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sender_org_id", sa.String(length=128), nullable=True),
        sa.Column("recipient_org_ids", sa.JSON(), nullable=False),
        sa.Column("record_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_type in ('text', 'emoji')",
            name=op.f("ck_chat_records_content_type_supported"),
        ),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_chat_records_sequence_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_records")),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_chat_records_conversation_sequence",
        ),
        sa.UniqueConstraint(
            "sender_user_id",
            "client_message_id",
            name="uq_chat_records_sender_client_message",
        ),
    )
    op.create_index(
        "ix_chat_records_conversation_created",
        "chat_records",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_records_created_at",
        "chat_records",
        ["created_at"],
        unique=False,
    )
    op.create_table(
        "record_idempotency_ledger",
        sa.Column("sender_user_id", sa.String(length=128), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=False),
        sa.Column("intent_sha256", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'active' and deleted_at is null and "
            "intent_sha256 is not null) or "
            "(status = 'deleted' and deleted_at is not null and "
            "record_id is null and intent_sha256 is null)",
            name=op.f(
                "ck_record_idempotency_ledger_deletion_state_consistent"
            ),
        ),
        sa.CheckConstraint(
            "sequence is null or sequence > 0",
            name=op.f("ck_record_idempotency_ledger_sequence_positive"),
        ),
        sa.CheckConstraint(
            "status in ('active', 'deleted')",
            name=op.f("ck_record_idempotency_ledger_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["chat_records.id"],
            name=op.f("fk_record_idempotency_ledger_record_id_chat_records"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "sender_user_id",
            "client_message_id",
            name=op.f("pk_record_idempotency_ledger"),
        ),
        sa.UniqueConstraint(
            "record_id", name="uq_record_idempotency_ledger_record_id"
        ),
    )
    op.create_index(
        "ix_record_idempotency_ledger_conversation_sequence",
        "record_idempotency_ledger",
        ["conversation_id", "sequence"],
        unique=False,
    )
    op.create_table(
        "chat_participant_positions",
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column(
            "delivered_through_sequence", sa.BigInteger(), nullable=False
        ),
        sa.Column("read_through_sequence", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivered_through_sequence >= 0",
            name=op.f(
                "ck_chat_participant_positions_delivered_sequence_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "read_through_sequence <= delivered_through_sequence",
            name=op.f("ck_chat_participant_positions_read_not_ahead_of_delivery"),
        ),
        sa.CheckConstraint(
            "read_through_sequence >= 0",
            name=op.f("ck_chat_participant_positions_read_sequence_nonnegative"),
        ),
        sa.PrimaryKeyConstraint(
            "conversation_id",
            "user_id",
            name=op.f("pk_chat_participant_positions"),
        ),
    )
    op.create_index(
        "ix_chat_participant_positions_user",
        "chat_participant_positions",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "chat_user_record_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("record_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["chat_records.id"],
            name=op.f("fk_chat_user_record_events_record_id_chat_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_user_record_events")),
        sa.UniqueConstraint(
            "user_id",
            "record_id",
            name="uq_chat_user_record_events_user_record",
        ),
        sa.UniqueConstraint(
            "user_id",
            "event_sequence",
            name="uq_chat_user_record_events_user_sequence",
        ),
    )
    op.create_index(
        "ix_chat_user_record_events_record_id",
        "chat_user_record_events",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_user_record_events_user_conversation_record",
        "chat_user_record_events",
        ["user_id", "conversation_id", "record_sequence"],
        unique=False,
    )
    op.create_table(
        "record_mutation_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=128), nullable=True),
        sa.Column("requested_by_user_id", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delete_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_record_ids", sa.JSON(), nullable=False),
        sa.Column("maximum_records", sa.Integer(), nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "affected_count >= 0",
            name=op.f("ck_record_mutation_audits_affected_count_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_mutation_audits")),
    )
    op.create_index(
        "ix_record_mutation_audits_completed_at",
        "record_mutation_audits",
        ["completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_record_mutation_audits_completed_at",
        table_name="record_mutation_audits",
    )
    op.drop_table("record_mutation_audits")
    op.drop_index(
        "ix_chat_user_record_events_user_conversation_record",
        table_name="chat_user_record_events",
    )
    op.drop_index(
        "ix_chat_user_record_events_record_id",
        table_name="chat_user_record_events",
    )
    op.drop_table("chat_user_record_events")
    op.drop_index(
        "ix_chat_participant_positions_user",
        table_name="chat_participant_positions",
    )
    op.drop_table("chat_participant_positions")
    op.drop_index("ix_chat_records_created_at", table_name="chat_records")
    op.drop_index(
        "ix_chat_records_conversation_created", table_name="chat_records"
    )
    op.drop_index(
        "ix_record_idempotency_ledger_conversation_sequence",
        table_name="record_idempotency_ledger",
    )
    op.drop_table("record_idempotency_ledger")
    op.drop_table("chat_records")
    op.drop_table("record_user_event_sequences")
    op.drop_table("record_conversation_sequences")
