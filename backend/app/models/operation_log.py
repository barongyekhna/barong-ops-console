from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import CreatedAtMixin, OrgScopedMixin, PrimaryKeyMixin, json_type


class OperationLog(OrgScopedMixin, PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "operation_logs"
    __table_args__ = (
        Index("ix_operation_logs_org_id_created_at", "org_id", "created_at"),
    )

    operation_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_jobs.job_id"),
        nullable=True,
    )
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        json_type(),
        nullable=True,
    )
