from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, json_type


class OpsAlertRecord(OrgScopedMixin, PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ops_alerts"
    __table_args__ = (
        Index("ix_ops_alerts_org_id_status", "org_id", "status"),
        Index("ix_ops_alerts_org_id_severity", "org_id", "severity"),
        Index("ix_ops_alerts_org_id_rule_id", "org_id", "rule_id"),
        Index("ix_ops_alerts_org_id_module_id", "org_id", "module_id"),
        Index("ix_ops_alerts_org_id_created_at", "org_id", "created_at"),
        Index("ix_ops_alerts_dedupe_key", "dedupe_key", unique=True),
    )

    alert_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(120), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    module_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    context_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    threshold_value: Mapped[float | None] = mapped_column(nullable=True)
    observed_value: Mapped[float | None] = mapped_column(nullable=True)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class OpsAlertDeliveryRecord(OrgScopedMixin, PrimaryKeyMixin, Base):
    __tablename__ = "ops_alert_deliveries"
    __table_args__ = (
        Index("ix_ops_alert_deliveries_org_id_alert_id", "org_id", "alert_id"),
        Index("ix_ops_alert_deliveries_org_id_sink_type", "org_id", "sink_type"),
        Index("ix_ops_alert_deliveries_org_id_status", "org_id", "status"),
        Index("ix_ops_alert_deliveries_created_at", "created_at"),
    )

    delivery_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    alert_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("ops_alerts.alert_id"),
        nullable=False,
    )
    sink_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sink_target: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(json_type(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
