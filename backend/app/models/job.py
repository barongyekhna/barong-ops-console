from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import (
    CreatedAtMixin,
    OrgScopedMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    json_type,
)


class AutomationJob(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "automation_jobs"
    __table_args__ = (
        Index("ix_automation_jobs_org_id_created_at", "org_id", "created_at"),
        Index("ix_automation_jobs_org_id_status", "org_id", "status"),
        Index("ix_automation_jobs_org_id_module_id", "org_id", "module_id"),
    )

    job_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    module_id: Mapped[str] = mapped_column(
        ForeignKey("module_registry.module_id"),
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_registry.agent_id"),
        nullable=True,
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_registry.workflow_id"),
        nullable=True,
    )
    parent_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    input_schema_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class JobEvent(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_org_id_created_at", "org_id", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(),
        nullable=True,
    )
