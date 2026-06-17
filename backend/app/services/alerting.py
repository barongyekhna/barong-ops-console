from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.base import Base
from ..models.execution_state import DLQStateRecord
from ..models.observability import AnomalyEventRecord, EventStreamRecord
from ..models.ops import OpsAlertDeliveryRecord, OpsAlertRecord
from ..schemas.alerting import (
    AlertCandidate,
    AlertDeliveryResult,
    AlertEngineResult,
    AlertRuleId,
    AlertSeverity,
    AlertSinkConfig,
    AlertThresholds,
    OpsAlert,
)
from ..schemas.storage_layer import StorageTimeRange
from .anomaly_detection import StreamAnomalyEngine


logger = logging.getLogger("barong.ops.alerting")

WebhookClient = Callable[[str, Mapping[str, Any], float], tuple[int | None, str | None]]


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_ops_alert_tables() -> None:
    from ..db.session import engine

    Base.metadata.create_all(
        bind=engine,
        tables=[
            OpsAlertRecord.__table__,
            OpsAlertDeliveryRecord.__table__,
        ],
        checkfirst=True,
    )


def _timestamp_value(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _window_or_latest(time_range: StorageTimeRange | None, window: timedelta) -> StorageTimeRange:
    if time_range is not None:
        return time_range
    end_at = utc_now()
    return StorageTimeRange(start_at=end_at - window, end_at=end_at)


def _severity_for_observed(observed: float, threshold: float) -> AlertSeverity:
    if observed >= threshold * 3:
        return "critical"
    if observed >= threshold * 2:
        return "critical"
    return "high"


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return str(value)


def _row_text(row: EventStreamRecord) -> str:
    return " ".join(
        (
            row.event_type,
            row.action,
            row.source,
            row.status,
            _json_text(row.payload),
            _json_text(row.metadata_json),
        )
    ).lower()


def _is_failed(row: EventStreamRecord) -> bool:
    return row.status.lower() in {"failed", "error", "errored", "denied", "rejected"}


def _is_auth_failure(row: EventStreamRecord) -> bool:
    if not _is_failed(row):
        return False
    text = _row_text(row)
    auth_markers = (
        "auth",
        "login",
        "session",
        "token",
        "credential",
        "password",
    )
    return any(marker in text for marker in auth_markers)


def _ids(rows: Sequence[EventStreamRecord], field: str) -> tuple[str, ...]:
    values: list[str] = []
    for row in rows:
        value = getattr(row, field)
        if value is not None and value not in values:
            values.append(value)
    return tuple(values)


class C17AlertEngine:
    """C17 alert engine: event_streams -> anomaly_events -> alert_engine -> sink."""

    def __init__(
        self,
        *,
        db: Session | None = None,
        org_id: str | None = None,
        window_seconds: int = 300,
        thresholds: AlertThresholds | None = None,
        sinks: AlertSinkConfig | None = None,
        webhook_client: WebhookClient | None = None,
    ) -> None:
        ensure_ops_alert_tables()
        self._db = db
        self._org_id = org_id
        self.window = timedelta(seconds=max(window_seconds, 1))
        self.thresholds = thresholds or AlertThresholds()
        settings = get_settings()
        self.sinks = sinks or AlertSinkConfig(
            webhook_url=getattr(settings, "ops_alert_webhook_url", None),
            webhook_timeout_seconds=getattr(
                settings,
                "ops_alert_webhook_timeout_seconds",
                5,
            ),
        )
        self.webhook_client = webhook_client

    def run_c17_pipeline(
        self,
        *,
        time_range: StorageTimeRange | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        limit: int | None = None,
        refresh_anomalies: bool = True,
    ) -> AlertEngineResult:
        effective_range = _window_or_latest(time_range, self.window)
        effective_org_id = org_id or self._org_id
        if refresh_anomalies:
            StreamAnomalyEngine(
                db=self._db,
                org_id=effective_org_id,
                window_seconds=int(self.window.total_seconds()),
                threshold_event_count=self.thresholds.error_spike_count,
            ).analyze_stream(
                time_range=effective_range,
                org_id=effective_org_id,
                module_id=module_id,
                limit=limit,
            )
        return self.evaluate_window(
            time_range=effective_range,
            org_id=effective_org_id,
            module_id=module_id,
            limit=limit,
        )

    def evaluate_window(
        self,
        *,
        time_range: StorageTimeRange | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        limit: int | None = None,
    ) -> AlertEngineResult:
        effective_range = _window_or_latest(time_range, self.window)
        effective_org_id = org_id or self._org_id
        rows = self._load_event_rows(
            time_range=effective_range,
            org_id=effective_org_id,
            module_id=module_id,
            limit=limit,
        )
        anomalies = self._load_anomaly_rows(
            time_range=effective_range,
            org_id=effective_org_id,
            module_id=module_id,
        )
        dlq_rows = self._load_dlq_rows(
            time_range=effective_range,
            org_id=effective_org_id,
        )
        candidates = (
            *self._error_spike_alerts(rows, anomalies, effective_range),
            *self._latency_spike_alerts(rows, anomalies, effective_range),
            *self._dlq_growth_alerts(dlq_rows, anomalies, effective_range),
            *self._auth_failure_alerts(rows, anomalies, effective_range),
        )

        alerts: list[OpsAlert] = []
        deliveries: list[AlertDeliveryResult] = []
        with self._session() as db:
            for candidate in candidates:
                row = self._persist_alert(db, candidate)
                alert = self._alert_from_row(row)
                alerts.append(alert)
                deliveries.extend(self._deliver_alert(db, alert))
            self._commit(db)

        return AlertEngineResult(
            analyzed_event_count=len(rows),
            analyzed_anomaly_count=len(anomalies),
            analyzed_dlq_count=len(dlq_rows),
            alerts=tuple(alerts),
            deliveries=tuple(deliveries),
        )

    def _load_event_rows(
        self,
        *,
        time_range: StorageTimeRange,
        org_id: str | None,
        module_id: str | None,
        limit: int | None,
    ) -> tuple[EventStreamRecord, ...]:
        with self._session() as db:
            statement = select(EventStreamRecord)
            if org_id is not None:
                statement = statement.where(EventStreamRecord.org_id == org_id)
            if module_id is not None:
                statement = statement.where(EventStreamRecord.module_id == module_id)
            if time_range.start_at is not None:
                statement = statement.where(EventStreamRecord.timestamp >= time_range.start_at)
            if time_range.end_at is not None:
                statement = statement.where(EventStreamRecord.timestamp <= time_range.end_at)
            statement = statement.order_by(
                EventStreamRecord.timestamp.desc(),
                EventStreamRecord.id.desc(),
            )
            if limit is not None:
                statement = statement.limit(max(limit, 0))
            return tuple(db.scalars(statement))

    def _load_anomaly_rows(
        self,
        *,
        time_range: StorageTimeRange,
        org_id: str | None,
        module_id: str | None,
    ) -> tuple[AnomalyEventRecord, ...]:
        with self._session() as db:
            statement = select(AnomalyEventRecord)
            if org_id is not None:
                statement = statement.where(AnomalyEventRecord.org_id == org_id)
            if module_id is not None:
                statement = statement.where(AnomalyEventRecord.module_id == module_id)
            if time_range.start_at is not None:
                statement = statement.where(AnomalyEventRecord.timestamp >= time_range.start_at)
            if time_range.end_at is not None:
                statement = statement.where(AnomalyEventRecord.timestamp <= time_range.end_at)
            return tuple(db.scalars(statement.order_by(AnomalyEventRecord.timestamp.desc())))

    def _load_dlq_rows(
        self,
        *,
        time_range: StorageTimeRange,
        org_id: str | None,
    ) -> tuple[DLQStateRecord, ...]:
        with self._session() as db:
            statement = select(DLQStateRecord)
            if org_id is not None:
                statement = statement.where(DLQStateRecord.org_id == org_id)
            if time_range.start_at is not None:
                statement = statement.where(DLQStateRecord.created_at >= time_range.start_at)
            if time_range.end_at is not None:
                statement = statement.where(DLQStateRecord.created_at <= time_range.end_at)
            return tuple(db.scalars(statement.order_by(DLQStateRecord.created_at.desc())))

    def _error_spike_alerts(
        self,
        rows: Sequence[EventStreamRecord],
        anomalies: Sequence[AnomalyEventRecord],
        time_range: StorageTimeRange,
    ) -> tuple[AlertCandidate, ...]:
        failed_by_module: dict[tuple[str, str], list[EventStreamRecord]] = defaultdict(list)
        for row in rows:
            if _is_failed(row):
                failed_by_module[(row.org_id, row.module_id)].append(row)
        candidates: list[AlertCandidate] = []
        threshold = self.thresholds.error_spike_count
        for (org_id, module_id), grouped in failed_by_module.items():
            if len(grouped) < threshold:
                continue
            candidates.append(
                self._candidate(
                    org_id=org_id,
                    module_id=module_id,
                    rule_id="ops.alert.error_spike",
                    alert_type="availability",
                    severity=_severity_for_observed(len(grouped), threshold),
                    title=f"Error spike in {module_id}",
                    description=(
                        f"{len(grouped)} failed events observed in module {module_id} "
                        f"within {self._window_seconds(time_range)} seconds."
                    ),
                    threshold_value=float(threshold),
                    observed_value=float(len(grouped)),
                    event_count=len(grouped),
                    related_rows=grouped,
                    anomalies=anomalies,
                    time_range=time_range,
                )
            )
        return tuple(candidates)

    def _latency_spike_alerts(
        self,
        rows: Sequence[EventStreamRecord],
        anomalies: Sequence[AnomalyEventRecord],
        time_range: StorageTimeRange,
    ) -> tuple[AlertCandidate, ...]:
        rows_by_module: dict[tuple[str, str], list[EventStreamRecord]] = defaultdict(list)
        for row in rows:
            rows_by_module[(row.org_id, row.module_id)].append(row)
        threshold = self.thresholds.latency_spike_ms
        candidates: list[AlertCandidate] = []
        for (org_id, module_id), grouped in rows_by_module.items():
            peak_latency = max((row.latency_ms for row in grouped), default=0)
            if peak_latency < threshold:
                continue
            candidates.append(
                self._candidate(
                    org_id=org_id,
                    module_id=module_id,
                    rule_id="ops.alert.latency_spike",
                    alert_type="performance",
                    severity=_severity_for_observed(peak_latency, threshold),
                    title=f"Latency spike in {module_id}",
                    description=(
                        f"Peak latency reached {peak_latency:.2f} ms in module "
                        f"{module_id}; threshold is {threshold:.2f} ms."
                    ),
                    threshold_value=float(threshold),
                    observed_value=float(peak_latency),
                    event_count=len(grouped),
                    related_rows=grouped,
                    anomalies=anomalies,
                    time_range=time_range,
                )
            )
        return tuple(candidates)

    def _dlq_growth_alerts(
        self,
        rows: Sequence[DLQStateRecord],
        anomalies: Sequence[AnomalyEventRecord],
        time_range: StorageTimeRange,
    ) -> tuple[AlertCandidate, ...]:
        rows_by_module: dict[tuple[str, str], list[DLQStateRecord]] = defaultdict(list)
        for row in rows:
            rows_by_module[(row.org_id, row.module_key or "system")].append(row)
        threshold = self.thresholds.dlq_growth_count
        candidates: list[AlertCandidate] = []
        for (org_id, module_id), grouped in rows_by_module.items():
            if len(grouped) < threshold:
                continue
            candidates.append(
                self._candidate(
                    org_id=org_id,
                    module_id=module_id,
                    rule_id="ops.alert.dlq_growth",
                    alert_type="recovery",
                    severity=_severity_for_observed(len(grouped), threshold),
                    title=f"DLQ growth in {module_id}",
                    description=(
                        f"{len(grouped)} DLQ records observed for {module_id} "
                        f"within {self._window_seconds(time_range)} seconds."
                    ),
                    threshold_value=float(threshold),
                    observed_value=float(len(grouped)),
                    event_count=len(grouped),
                    related_rows=(),
                    dlq_rows=grouped,
                    anomalies=anomalies,
                    time_range=time_range,
                )
            )
        return tuple(candidates)

    def _auth_failure_alerts(
        self,
        rows: Sequence[EventStreamRecord],
        anomalies: Sequence[AnomalyEventRecord],
        time_range: StorageTimeRange,
    ) -> tuple[AlertCandidate, ...]:
        rows_by_org: dict[str, list[EventStreamRecord]] = defaultdict(list)
        for row in rows:
            if _is_auth_failure(row):
                rows_by_org[row.org_id].append(row)
        threshold = self.thresholds.auth_failure_count
        candidates: list[AlertCandidate] = []
        for org_id, grouped in rows_by_org.items():
            if len(grouped) < threshold:
                continue
            candidates.append(
                self._candidate(
                    org_id=org_id,
                    module_id="auth",
                    rule_id="ops.alert.auth_failure_spike",
                    alert_type="security",
                    severity=_severity_for_observed(len(grouped), threshold),
                    title="Authentication failure spike",
                    description=(
                        f"{len(grouped)} failed authentication/session events "
                        f"observed within {self._window_seconds(time_range)} seconds."
                    ),
                    threshold_value=float(threshold),
                    observed_value=float(len(grouped)),
                    event_count=len(grouped),
                    related_rows=grouped,
                    anomalies=anomalies,
                    time_range=time_range,
                )
            )
        return tuple(candidates)

    def _candidate(
        self,
        *,
        org_id: str,
        module_id: str,
        rule_id: AlertRuleId,
        alert_type: str,
        severity: AlertSeverity,
        title: str,
        description: str,
        threshold_value: float,
        observed_value: float,
        event_count: int,
        related_rows: Sequence[EventStreamRecord],
        anomalies: Sequence[AnomalyEventRecord],
        time_range: StorageTimeRange,
        dlq_rows: Sequence[DLQStateRecord] = (),
    ) -> AlertCandidate:
        window_seconds = self._window_seconds(time_range)
        anomaly_refs = self._related_anomalies(
            anomalies,
            org_id=org_id,
            module_id=module_id,
            context_ids=_ids(related_rows, "context_id"),
        )
        first_seen_at = min(
            [
                *(row.timestamp for row in related_rows),
                *(row.created_at for row in dlq_rows),
            ],
            default=time_range.start_at or utc_now(),
        )
        last_seen_at = max(
            [
                *(row.timestamp for row in related_rows),
                *(row.created_at for row in dlq_rows),
            ],
            default=time_range.end_at or utc_now(),
        )
        dedupe_window = (
            _timestamp_value(time_range.start_at) or first_seen_at,
            _timestamp_value(time_range.end_at) or last_seen_at,
        )
        dedupe_key = (
            f"{rule_id}:{org_id}:{module_id}:"
            f"{dedupe_window[0].isoformat()}:{dedupe_window[1].isoformat()}"
        )
        return AlertCandidate(
            dedupe_key=dedupe_key[:300],
            org_id=org_id,
            rule_id=rule_id,
            alert_type=alert_type,  # type: ignore[arg-type]
            severity=severity,
            module_id=module_id,
            context_id=related_rows[0].context_id if related_rows else None,
            trace_id=related_rows[0].trace_id if related_rows else None,
            title=title,
            description=description,
            threshold_value=threshold_value,
            observed_value=observed_value,
            window_seconds=window_seconds,
            event_count=event_count,
            payload={
                "event_ids": _ids(related_rows, "event_id"),
                "trace_ids": _ids(related_rows, "trace_id"),
                "dlq_ids": _ids(dlq_rows, "dlq_id"),
                "anomaly_ids": tuple(row.anomaly_id for row in anomaly_refs),
                "anomaly_count": len(anomaly_refs),
                "pipeline": "event_streams -> anomaly_events -> alert_engine -> sink",
            },
            first_seen_at=first_seen_at,
            last_seen_at=last_seen_at,
        )

    def _related_anomalies(
        self,
        anomalies: Sequence[AnomalyEventRecord],
        *,
        org_id: str,
        module_id: str,
        context_ids: Sequence[str],
    ) -> tuple[AnomalyEventRecord, ...]:
        context_set = set(context_ids)
        related: list[AnomalyEventRecord] = []
        for row in anomalies:
            if row.org_id != org_id:
                continue
            if row.module_id not in {module_id, "system"} and row.context_id not in context_set:
                continue
            if row not in related:
                related.append(row)
        return tuple(related)

    def _window_seconds(self, time_range: StorageTimeRange) -> int:
        if time_range.start_at is not None and time_range.end_at is not None:
            return max(int((time_range.end_at - time_range.start_at).total_seconds()), 1)
        return max(int(self.window.total_seconds()), 1)

    def _persist_alert(self, db: Session, candidate: AlertCandidate) -> OpsAlertRecord:
        row = db.scalar(
            select(OpsAlertRecord).where(
                OpsAlertRecord.dedupe_key == candidate.dedupe_key
            )
        )
        now = utc_now()
        if row is None:
            row = OpsAlertRecord(
                org_id=candidate.org_id,
                alert_id=f"ops-alert-{uuid4()}",
                dedupe_key=candidate.dedupe_key,
                source="c17_alert_engine",
                rule_id=candidate.rule_id,
                alert_type=candidate.alert_type,
                severity=candidate.severity,
                status="open",
                module_id=candidate.module_id,
                context_id=candidate.context_id,
                trace_id=candidate.trace_id,
                title=candidate.title,
                description=candidate.description,
                threshold_value=candidate.threshold_value,
                observed_value=candidate.observed_value,
                window_seconds=candidate.window_seconds,
                event_count=candidate.event_count,
                payload=candidate.payload,
                first_seen_at=candidate.first_seen_at,
                last_seen_at=candidate.last_seen_at,
            )
            db.add(row)
        else:
            row.severity = candidate.severity
            row.module_id = candidate.module_id
            row.context_id = candidate.context_id
            row.trace_id = candidate.trace_id
            row.title = candidate.title
            row.description = candidate.description
            row.threshold_value = candidate.threshold_value
            row.observed_value = candidate.observed_value
            row.window_seconds = candidate.window_seconds
            row.event_count = candidate.event_count
            row.payload = candidate.payload
            row.last_seen_at = candidate.last_seen_at
            row.updated_at = now
        db.flush()
        return row

    def _deliver_alert(
        self,
        db: Session,
        alert: OpsAlert,
    ) -> tuple[AlertDeliveryResult, ...]:
        deliveries: list[AlertDeliveryResult] = []
        if self.sinks.enable_ops_dashboard:
            deliveries.append(
                self._record_delivery(
                    db,
                    alert,
                    sink_type="ops_dashboard",
                    sink_target="ops_alerts",
                    status="delivered",
                    payload={"alert_id": alert.alert_id},
                )
            )
        if self.sinks.enable_log:
            logger.warning(
                "ops_alert rule=%s severity=%s org_id=%s module_id=%s alert_id=%s",
                alert.rule_id,
                alert.severity,
                alert.org_id,
                alert.module_id,
                alert.alert_id,
            )
            deliveries.append(
                self._record_delivery(
                    db,
                    alert,
                    sink_type="log",
                    sink_target="barong.ops.alerting",
                    status="delivered",
                    payload={"alert_id": alert.alert_id},
                )
            )
        if self.sinks.enable_webhook:
            deliveries.append(self._deliver_webhook(db, alert))
        return tuple(deliveries)

    def _deliver_webhook(self, db: Session, alert: OpsAlert) -> AlertDeliveryResult:
        if self.sinks.webhook_url is None:
            return self._record_delivery(
                db,
                alert,
                sink_type="webhook",
                sink_target=None,
                status="skipped",
                payload={"alert_id": alert.alert_id},
                error="webhook_url_not_configured",
            )
        payload = alert.model_dump(mode="json")
        try:
            if self.webhook_client is not None:
                response_code, error = self.webhook_client(
                    self.sinks.webhook_url,
                    payload,
                    self.sinks.webhook_timeout_seconds,
                )
            else:
                import httpx

                response = httpx.post(
                    self.sinks.webhook_url,
                    json=payload,
                    timeout=self.sinks.webhook_timeout_seconds,
                )
                response_code = response.status_code
                error = None if response.status_code < 400 else response.text[:500]
            status = "delivered" if response_code is not None and response_code < 400 else "failed"
            return self._record_delivery(
                db,
                alert,
                sink_type="webhook",
                sink_target=self.sinks.webhook_url,
                status=status,
                payload=payload,
                response_code=response_code,
                error=error,
            )
        except Exception as exc:
            return self._record_delivery(
                db,
                alert,
                sink_type="webhook",
                sink_target=self.sinks.webhook_url,
                status="failed",
                payload=payload,
                error=str(exc)[:500],
            )

    def _record_delivery(
        self,
        db: Session,
        alert: OpsAlert,
        *,
        sink_type: str,
        sink_target: str | None,
        status: str,
        payload: Mapping[str, Any],
        response_code: int | None = None,
        error: str | None = None,
    ) -> AlertDeliveryResult:
        now = utc_now()
        row = OpsAlertDeliveryRecord(
            org_id=alert.org_id,
            delivery_id=f"ops-alert-delivery-{uuid4()}",
            alert_id=alert.alert_id,
            sink_type=sink_type,
            sink_target=sink_target,
            status=status,
            attempt=1,
            response_code=response_code,
            error=error,
            payload=dict(payload),
            delivered_at=now if status == "delivered" else None,
            created_at=now,
        )
        db.add(row)
        db.flush()
        return AlertDeliveryResult(
            delivery_id=row.delivery_id,
            alert_id=row.alert_id,
            org_id=row.org_id,
            sink_type=row.sink_type,  # type: ignore[arg-type]
            sink_target=row.sink_target,
            status=row.status,  # type: ignore[arg-type]
            response_code=row.response_code,
            error=row.error,
        )

    def _alert_from_row(self, row: OpsAlertRecord) -> OpsAlert:
        created_at = _timestamp_value(row.created_at) or utc_now()
        updated_at = _timestamp_value(row.updated_at) or created_at
        return OpsAlert(
            alert_id=row.alert_id,
            dedupe_key=row.dedupe_key,
            org_id=row.org_id,
            source=row.source,  # type: ignore[arg-type]
            rule_id=row.rule_id,  # type: ignore[arg-type]
            alert_type=row.alert_type,  # type: ignore[arg-type]
            severity=row.severity,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            module_id=row.module_id,
            context_id=row.context_id,
            trace_id=row.trace_id,
            title=row.title,
            description=row.description,
            threshold_value=row.threshold_value,
            observed_value=row.observed_value,
            window_seconds=row.window_seconds,
            event_count=row.event_count,
            payload=dict(row.payload),
            first_seen_at=_timestamp_value(row.first_seen_at) or created_at,
            last_seen_at=_timestamp_value(row.last_seen_at) or updated_at,
            created_at=created_at,
            updated_at=updated_at,
        )

    @contextmanager
    def _session(self) -> Iterator[Session]:
        if self._db is not None:
            yield self._db
            return
        from ..db.session import SessionLocal

        with SessionLocal() as db:
            yield db

    def _commit(self, db: Session) -> None:
        if self._db is None:
            db.commit()
        else:
            db.flush()
