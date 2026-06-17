from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import CreatedAtMixin, OrgScopedMixin, PrimaryKeyMixin, json_type


class ContextPacket(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "context_packets"
    __table_args__ = (
        CheckConstraint(
            "target_module_id IS NOT NULL OR target_agent_id IS NOT NULL",
            name="has_context_target",
        ),
        Index("ix_context_packets_org_id_created_at", "org_id", "created_at"),
        Index("ix_context_packets_org_id_source_module_id", "org_id", "source_module_id"),
    )

    context_packet_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    source_job_id: Mapped[str] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=False,
    )
    source_module_id: Mapped[str] = mapped_column(
        ForeignKey("module_registry.module_id"),
        nullable=False,
    )
    target_module_id: Mapped[str | None] = mapped_column(
        ForeignKey("module_registry.module_id"),
        nullable=True,
    )
    target_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_registry.agent_id"),
        nullable=True,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    artifact_refs: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    access_scope: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
