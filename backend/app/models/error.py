from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, json_type


class SystemError(PrimaryKeyMixin, Base):
    __tablename__ = "system_errors"

    error_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(),
        nullable=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    module_id: Mapped[str | None] = mapped_column(
        ForeignKey("module_registry.module_id"),
        nullable=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_registry.agent_id"),
        nullable=True,
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_registry.workflow_id"),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
