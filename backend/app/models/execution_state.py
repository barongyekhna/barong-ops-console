from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, json_type


class ExecutionCallbackRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "execution_callbacks"
    __table_args__ = (
        Index("ix_execution_callbacks_org_id_context_id", "org_id", "context_id"),
        Index("ix_execution_callbacks_org_id_workflow_id", "org_id", "workflow_id"),
        Index("ix_execution_callbacks_org_id_status", "org_id", "status"),
    )

    callback_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
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
