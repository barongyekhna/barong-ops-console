from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.execution_state import DLQStateRecord
from backend.app.models.ops import OpsAlertDeliveryRecord, OpsAlertRecord
from backend.app.schemas.alerting import AlertSinkConfig, AlertThresholds
from backend.app.schemas.storage_layer import StorageTimeRange
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.alerting import C17AlertEngine
from backend.app.services.storage_layer import DBStorageAdapter


BASE_TIME = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)


def _log_entry(
    *,
    event_id: str,
    context_id: str,
    module: str = "C17",
    action: str = "operation failed",
    event_type: str = "ops.failure",
    status: str = "failed",
    latency_ms: float = 25,
) -> LogEntry:
    module_tags = {
        "C16": "security",
        "C17": "observability",
    }
    return LogEntry(
        event_id=event_id,
        timestamp=BASE_TIME,
        context_id=context_id,
        module=module,  # type: ignore[arg-type]
        event_type=event_type,
        action=action,
        source="backend",
        entity=LogEntity(
            user_id="user-alert",
            product_key="product.ops",
            workflow_id="workflow.ops",
            request_id=context_id,
        ),
        status=status,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        request={"trace_id": f"trace-{context_id}", "path": "/api/app/operation-logs"},
        response={"ok": status == "success"},
        metadata=LogMetadata(retry_count=0),
        tags=(f"module:{module_tags[module]}",),
    )


def _insert_dlq_rows() -> None:
    with SessionLocal() as db:
        for index in range(2):
            db.add(
                DLQStateRecord(
                    org_id="platform",
                    dlq_id=f"dlq-alert-{index}",
                    context_id=f"ctx-dlq-{index}",
                    execution_id=f"exec-dlq-{index}",
                    trace_id=f"trace-dlq-{index}",
                    job_id=f"job-dlq-{index}",
                    actor_id="actor-alert",
                    module_key="C17",
                    workflow_id="workflow.ops",
                    failure_type="delivery_failure",
                    status="open",
                    reason="Simulated DLQ growth for alert test.",
                    payload={"index": index},
                    failure_context={"source": "test"},
                    retry_decision={"retryable": True},
                    attempt=1,
                    retry_count=0,
                    replay_count=0,
                    replayable=True,
                    created_at=BASE_TIME,
                    updated_at=BASE_TIME,
                )
            )
        db.commit()


def test_pre20_o_c17_alert_engine_triggers_all_sinks(
    clean_auth_tables: None,
) -> None:
    adapter = DBStorageAdapter(now=BASE_TIME, org_id="platform")
    for index in range(3):
        adapter.write_log(
            _log_entry(event_id=f"evt-error-{index}", context_id=f"ctx-error-{index}")
        )
    adapter.write_log(
        _log_entry(
            event_id="evt-latency-0",
            context_id="ctx-latency-0",
            status="success",
            latency_ms=2500,
        )
    )
    for index in range(2):
        adapter.write_log(
            _log_entry(
                event_id=f"evt-auth-{index}",
                context_id=f"ctx-auth-{index}",
                module="C16",
                action="login failed invalid token",
                event_type="auth.login.failed",
                status="failed",
            )
        )
    _insert_dlq_rows()

    webhook_calls: list[tuple[str, Mapping[str, Any], float]] = []

    def fake_webhook(
        url: str,
        payload: Mapping[str, Any],
        timeout: float,
    ) -> tuple[int, str | None]:
        webhook_calls.append((url, payload, timeout))
        return 202, None

    result = C17AlertEngine(
        org_id="platform",
        window_seconds=300,
        thresholds=AlertThresholds(
            error_spike_count=3,
            latency_spike_ms=1000,
            dlq_growth_count=2,
            auth_failure_count=2,
        ),
        sinks=AlertSinkConfig(webhook_url="https://alerts.example.test/hook"),
        webhook_client=fake_webhook,
    ).run_c17_pipeline(
        time_range=StorageTimeRange(
            start_at=BASE_TIME - timedelta(seconds=1),
            end_at=BASE_TIME + timedelta(seconds=1),
        ),
        org_id="platform",
    )

    rule_ids = {alert.rule_id for alert in result.alerts}
    assert {
        "ops.alert.error_spike",
        "ops.alert.latency_spike",
        "ops.alert.dlq_growth",
        "ops.alert.auth_failure_spike",
    }.issubset(rule_ids)
    assert result.pipeline == "event_streams -> anomaly_events -> alert_engine -> sink"
    assert result.analyzed_event_count == 6
    assert result.analyzed_anomaly_count >= 1
    assert webhook_calls

    delivery_sink_types = {delivery.sink_type for delivery in result.deliveries}
    assert {"webhook", "log", "ops_dashboard"}.issubset(delivery_sink_types)

    with SessionLocal() as db:
        alert_rows = tuple(
            db.execute(select(OpsAlertRecord.rule_id, OpsAlertRecord.payload))
        )
        delivery_rows = tuple(
            db.scalars(select(OpsAlertDeliveryRecord.sink_type))
        )

    assert {row.rule_id for row in alert_rows} == rule_ids
    assert set(delivery_rows).issuperset(
        {"webhook", "log", "ops_dashboard"}
    )
    assert any(row.payload["anomaly_count"] >= 1 for row in alert_rows)
