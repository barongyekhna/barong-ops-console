from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import CreatedAtMixin, OrgScopedMixin, PrimaryKeyMixin, json_type


class MemoryEvent(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_events"
    __table_args__ = (
        Index("ix_memory_events_org_id_created_at", "org_id", "created_at"),
    )

    memory_event_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    importance: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(128), nullable=False)


class MemorySummary(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_summaries"
    __table_args__ = (
        Index("ix_memory_summaries_org_id_created_at", "org_id", "created_at"),
    )

    memory_summary_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(String(8000), nullable=False)
    source_event_ids: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AgentMemoryAccessLog(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "agent_memory_access_logs"
    __table_args__ = (
        Index(
            "ix_agent_memory_access_logs_org_id_created_at",
            "org_id",
            "created_at",
        ),
    )

    access_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agent_registry.agent_id"),
        nullable=False,
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(1000), nullable=False)
    access_scope: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    denial_reason: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
