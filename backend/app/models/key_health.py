"""Persistent, secret-free results for the API key health monitor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import CreatedAtMixin, PrimaryKeyMixin, TimestampMixin, json_type


class KeyHealthRun(PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "key_health_runs"
    __table_args__ = (
        UniqueConstraint("scheduled_for", name="uq_key_health_runs_scheduled_for"),
        Index("ix_key_health_runs_status_started", "status", "started_at"),
    )

    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    healthy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class KeyHealthCheck(PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "key_health_checks"
    __table_args__ = (
        UniqueConstraint("run_id", "key_id", name="uq_key_health_checks_run_key"),
        Index("ix_key_health_checks_key_checked", "key_id", "checked_at"),
        Index("ix_key_health_checks_status_checked", "status", "checked_at"),
        Index("ix_key_health_checks_org_checked", "org_id", "checked_at"),
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("key_health_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    key_name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_type: Mapped[str] = mapped_column(String(48), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(
        "details",
        json_type(),
        nullable=False,
        default=dict,
    )


class KeyHealthState(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "key_health_states"
    __table_args__ = (
        UniqueConstraint("key_id", name="uq_key_health_states_key_id"),
        Index("ix_key_health_states_status_checked", "current_status", "last_checked_at"),
    )

    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    org_id: Mapped[str] = mapped_column(String(40), nullable=False)
    key_name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_type: Mapped[str] = mapped_column(String(48), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    current_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(
        "details",
        json_type(),
        nullable=False,
        default=dict,
    )
