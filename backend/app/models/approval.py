from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import (
    CreatedAtMixin,
    OrgScopedMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    json_type,
)


class ApprovalRequestRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_org_id_created_at", "org_id", "created_at"),
        Index("ix_approval_requests_org_id_status", "org_id", "status"),
        Index("ix_approval_requests_org_id_module_key", "org_id", "module_key"),
        Index(
            "ix_approval_requests_org_id_category_status",
            "org_id",
            "category",
            "status",
        ),
    )

    approval_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    module_key: Mapped[str] = mapped_column(String(128), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(180), nullable=False)
    action_key: Mapped[str] = mapped_column(String(180), nullable=False)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )
    request_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="feature",
        server_default="feature",
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    status_trace: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type(),
        nullable=False,
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )


class ApprovalWorkflowRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "approval_workflows"
    __table_args__ = (
        Index("ix_approval_workflows_org_id_created_at", "org_id", "created_at"),
        Index("ix_approval_workflows_org_id_state", "org_id", "state"),
    )

    workflow_id: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
        unique=True,
    )
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.approval_id"),
        nullable=False,
        unique=True,
    )
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    workflow_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    workflow_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    workflow_payload: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )


class ApprovalDecisionRecord(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (
        Index("ix_approval_decisions_org_id_created_at", "org_id", "created_at"),
        Index("ix_approval_decisions_org_id_status", "org_id", "status"),
    )

    decision_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.approval_id"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("approval_workflows.workflow_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decision_source: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    decision_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decision_payload: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
