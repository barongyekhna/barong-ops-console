from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, json_type


class EventStreamRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "event_streams"
    __table_args__ = (
        Index("ix_event_streams_org_id_timestamp", "org_id", "timestamp"),
        Index("ix_event_streams_org_id_context_id", "org_id", "context_id"),
        Index("ix_event_streams_org_id_trace_id", "org_id", "trace_id"),
        Index("ix_event_streams_org_id_module_id", "org_id", "module_id"),
        Index("ix_event_streams_org_id_status", "org_id", "status"),
        Index("ix_event_streams_org_id_event_type", "org_id", "event_type"),
        Index("ix_event_streams_processing_status", "processing_status"),
    )

    record_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(180), nullable=False)
    product_key: Mapped[str | None] = mapped_column(String(180), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    module_id: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(180), nullable=False)
    action: Mapped[str] = mapped_column(String(240), nullable=False)
    source: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    storage_tier: Mapped[str] = mapped_column(String(50), nullable=False)
    backend_targets: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
    )
    compressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archive_object_key: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    processing_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AuditLogRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_id_timestamp", "org_id", "timestamp"),
        Index("ix_audit_logs_org_id_context_id", "org_id", "context_id"),
        Index("ix_audit_logs_org_id_trace_id", "org_id", "trace_id"),
        Index("ix_audit_logs_org_id_module_id", "org_id", "module_id"),
    )

    audit_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    event_stream_record_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    event_id: Mapped[str] = mapped_column(String(180), nullable=False)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    module_id: Mapped[str] = mapped_column(String(180), nullable=False)
    action: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
    )


class ReplayJobRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "replay_jobs"
    __table_args__ = (
        Index("ix_replay_jobs_org_id_context_id", "org_id", "context_id"),
        Index("ix_replay_jobs_org_id_trace_id", "org_id", "trace_id"),
        Index("ix_replay_jobs_org_id_status", "org_id", "status"),
        Index("ix_replay_jobs_org_id_created_at", "org_id", "created_at"),
    )

    replay_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(180), nullable=False)
    context_id: Mapped[str] = mapped_column(String(180), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    deterministic_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    input_event_ids: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    replay_input: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    replay_output: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    replay_result: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AnomalyEventRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "anomaly_events"
    __table_args__ = (
        Index("ix_anomaly_events_org_id_timestamp", "org_id", "timestamp"),
        Index("ix_anomaly_events_org_id_context_id", "org_id", "context_id"),
        Index("ix_anomaly_events_org_id_module_id", "org_id", "module_id"),
        Index("ix_anomaly_events_org_id_type_severity", "org_id", "anomaly_type", "severity"),
    )

    anomaly_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    source_event_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    context_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    module_id: Mapped[str] = mapped_column(String(180), nullable=False)
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(180), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    threshold_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
