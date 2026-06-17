from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AlertRuleId = Literal[
    "ops.alert.error_spike",
    "ops.alert.latency_spike",
    "ops.alert.dlq_growth",
    "ops.alert.auth_failure_spike",
]
AlertType = Literal["availability", "performance", "recovery", "security"]
AlertSeverity = Literal["low", "medium", "high", "critical"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
AlertSinkType = Literal["webhook", "log", "ops_dashboard"]
AlertDeliveryStatus = Literal["delivered", "failed", "skipped"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class AlertThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_spike_count: int = Field(default=5, ge=1)
    latency_spike_ms: float = Field(default=1000, ge=1)
    dlq_growth_count: int = Field(default=3, ge=1)
    auth_failure_count: int = Field(default=5, ge=1)


class AlertSinkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enable_webhook: bool = True
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_timeout_seconds: float = Field(default=5, gt=0, le=30)
    enable_log: bool = True
    enable_ops_dashboard: bool = True

    @field_validator("webhook_url")
    @classmethod
    def normalize_webhook_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        return candidate or None


class AlertCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dedupe_key: str = Field(min_length=1, max_length=300)
    org_id: str = Field(min_length=1, max_length=40)
    rule_id: AlertRuleId
    alert_type: AlertType
    severity: AlertSeverity
    module_id: str | None = Field(default=None, max_length=180)
    context_id: str | None = Field(default=None, max_length=180)
    trace_id: str | None = Field(default=None, max_length=180)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=2000)
    threshold_value: float | None = None
    observed_value: float | None = None
    window_seconds: int = Field(ge=1)
    event_count: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)

    @field_validator("first_seen_at", "last_seen_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class OpsAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: str
    dedupe_key: str
    org_id: str
    source: Literal["c17_alert_engine"]
    rule_id: AlertRuleId
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    module_id: str | None = None
    context_id: str | None = None
    trace_id: str | None = None
    title: str
    description: str
    threshold_value: float | None = None
    observed_value: float | None = None
    window_seconds: int
    event_count: int
    payload: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class AlertDeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str
    alert_id: str
    org_id: str
    sink_type: AlertSinkType
    sink_target: str | None = None
    status: AlertDeliveryStatus
    response_code: int | None = None
    error: str | None = None


class AlertEngineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline: Literal["event_streams -> anomaly_events -> alert_engine -> sink"] = (
        "event_streams -> anomaly_events -> alert_engine -> sink"
    )
    analyzed_event_count: int = Field(default=0, ge=0)
    analyzed_anomaly_count: int = Field(default=0, ge=0)
    analyzed_dlq_count: int = Field(default=0, ge=0)
    alerts: tuple[OpsAlert, ...] = Field(default_factory=tuple)
    deliveries: tuple[AlertDeliveryResult, ...] = Field(default_factory=tuple)
