from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, json_type


class ExecutionCallbackRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_callbacks"
    __table_args__ = (
        Index("ix_execution_callbacks_org_id_context_id", "org_id", "context_id"),
        Index("ix_execution_callbacks_org_id_execution_id", "org_id", "execution_id"),
        Index("ix_execution_callbacks_org_id_workflow_id", "org_id", "workflow_id"),
        Index("ix_execution_callbacks_org_id_status", "org_id", "status"),
        Index("ix_execution_callbacks_org_id_created_at", "org_id", "created_at"),
        Index("ix_execution_callbacks_org_id_module_key", "org_id", "module_key"),
        Index("ix_execution_callbacks_idempotency_key", "idempotency_key"),
    )

    callback_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
    )
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    signature_status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    validation_result: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ExecutionResultRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_results"
    __table_args__ = (
        Index("ix_execution_results_org_id_context_id", "org_id", "context_id"),
        Index("ix_execution_results_org_id_workflow_id", "org_id", "workflow_id"),
        Index("ix_execution_results_org_id_status", "org_id", "status"),
    )

    result_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task: Mapped[str] = mapped_column(String(180), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    original_request: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    workflow_output: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    callbacks_received: Mapped[int] = mapped_column(nullable=False, default=0)
    signature_validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    payload_validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CallbackStateRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "callback_state"
    __table_args__ = (
        Index("ix_callback_state_org_id_context_id", "org_id", "context_id"),
        Index("ix_callback_state_org_id_execution_id", "org_id", "execution_id"),
        Index("ix_callback_state_org_id_workflow_id", "org_id", "workflow_id"),
        Index("ix_callback_state_org_id_status", "org_id", "status"),
        Index("ix_callback_state_org_id_created_at", "org_id", "created_at"),
        Index("ix_callback_state_org_id_module_key", "org_id", "module_key"),
        Index("ix_callback_state_org_id_trace_id", "org_id", "trace_id"),
        Index("ix_callback_state_org_id_job_id", "org_id", "job_id"),
        Index("ix_callback_state_org_id_actor_id", "org_id", "actor_id"),
    )

    result_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task: Mapped[str] = mapped_column(String(180), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    original_request: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    workflow_output: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    callbacks_received: Mapped[int] = mapped_column(nullable=False, default=0)
    signature_validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    payload_validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CallbackStateTransitionRecord(PrimaryKeyMixin, Base):
    __tablename__ = "callback_state_transitions"
    __table_args__ = (
        Index("ix_callback_state_transitions_execution_id", "execution_id"),
        Index("ix_callback_state_transitions_context_id", "context_id"),
        Index("ix_callback_state_transitions_to_status", "to_status"),
        Index("ix_callback_state_transitions_created_at", "created_at"),
        Index("ix_callback_state_transitions_idempotency_key", "idempotency_key"),
        Index(
            "uq_callback_state_transitions_terminal_execution_id",
            "execution_id",
            unique=True,
            sqlite_where=text("to_status IN ('success', 'failed')"),
            postgresql_where=text("to_status IN ('success', 'failed')"),
        ),
    )

    transition_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    payload_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ExecutionDLQRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_dlq"
    __table_args__ = (
        Index("ix_execution_dlq_org_id_context_id", "org_id", "context_id"),
        Index("ix_execution_dlq_org_id_status", "org_id", "status"),
        Index("ix_execution_dlq_org_id_retry_after", "org_id", "retry_after"),
    )

    dlq_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    context_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replayable: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DLQStateRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dlq_state"
    __table_args__ = (
        Index("ix_dlq_state_org_id_context_id", "org_id", "context_id"),
        Index("ix_dlq_state_org_id_execution_id", "org_id", "execution_id"),
        Index("ix_dlq_state_org_id_status", "org_id", "status"),
        Index("ix_dlq_state_org_id_retry_after", "org_id", "retry_after"),
        Index("ix_dlq_state_org_id_created_at", "org_id", "created_at"),
        Index("ix_dlq_state_org_id_module_key", "org_id", "module_key"),
        Index("ix_dlq_state_org_id_trace_id", "org_id", "trace_id"),
        Index("ix_dlq_state_org_id_job_id", "org_id", "job_id"),
        Index("ix_dlq_state_org_id_actor_id", "org_id", "actor_id"),
    )

    dlq_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    context_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    module_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    failure_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    failure_context: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
        default=dict,
    )
    retry_decision: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
        default=dict,
    )
    attempt: Mapped[int] = mapped_column(nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replay_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replayable: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
