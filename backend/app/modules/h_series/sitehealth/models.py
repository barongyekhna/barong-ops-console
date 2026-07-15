"""SQLAlchemy models for the H independent-site health control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    true,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type


class HUUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class HTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class HHealthRun(HUUIDPrimaryKeyMixin, HTimestampMixin, Base):
    """One scheduled or manually triggered site-health execution ledger row."""

    __tablename__ = "h_health_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('scheduled', 'manual')",
            name=conv("ck_h_health_runs_valid_trigger"),
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=conv("ck_h_health_runs_valid_status"),
        ),
    )

    trigger: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    urls_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    urls_ok: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    urls_broken: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    urls_slow: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    avg_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p95_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sitemap_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    homepage_ok: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    summary_json: Mapped[Any | None] = mapped_column(json_type(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class HHealthFinding(HUUIDPrimaryKeyMixin, HTimestampMixin, Base):
    """A health anomaly discovered by n8n and reviewed in the console."""

    __tablename__ = "h_health_findings"
    __table_args__ = (
        CheckConstraint(
            "finding_type IN ("
            "'broken_link', 'slow_page', 'sitemap_error', 'homepage_error'"
            ")",
            name=conv("ck_h_health_findings_valid_type"),
        ),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')",
            name=conv("ck_h_health_findings_valid_status"),
        ),
        Index("ix_h_health_findings_run_id", "run_id"),
        Index("ix_h_health_findings_type_status", "finding_type", "status"),
    )

    run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("h_health_runs.id", name="fk_h_health_findings_run_id_runs"),
        nullable=False,
    )
    finding_type: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="open",
    )
