from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.observability import (
    AnomalyEventRecord,
    AuditLogRecord,
    EventStreamRecord,
    ReplayJobRecord,
)
from backend.app.models.organization import OrganizationRecord
from backend.app.schemas.execution_trace import ExecutionTrace, ExecutionTraceStep
from backend.app.schemas.organization import generate_org_id
from backend.app.schemas.storage_layer import EventRaw, StorageTimeRange
from backend.app.schemas.structured_logs import LogEntity, LogEntry, LogMetadata
from backend.app.services.audit_query_engine import AuditLogWriter, AuditQueryEngine
from backend.app.services.data_isolation import (
    OrgDataIsolationUserContext,
    org_data_isolation_context,
)
from backend.app.services.event_collector import clear_event_buffer, emit_event
from backend.app.services.storage_layer import DBStorageAdapter


BASE_TIME = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


def _log_entry(
    *,
    event_id: str = "evt-durable-log",
    context_id: str = "ctx-durable-001",
    trace_id: str = "trace-durable-001",
    timestamp: datetime = BASE_TIME,
) -> LogEntry:
    return LogEntry(
        event_id=event_id,
        timestamp=timestamp,
        context_id=context_id,
        module="C15",
        event_type="workflow.execution.end",
        action="workflow execution end",
        source="n8n",
        entity=LogEntity(
            user_id="user-42",
            product_key="product.demo",
            workflow_id="workflow.demo",
            request_id=context_id,
        ),
        status="success",
        latency_ms=15,
        request={"trace_id": trace_id, "workflow_id": "workflow.demo"},
        response={"ok": True},
        metadata=LogMetadata(retry_count=1),
        tags=("c17b", "module:execution"),
    )


def _trace(
    *,
    context_id: str = "ctx-durable-001",
    trace_id: str = "trace-durable-001",
) -> ExecutionTrace:
    return ExecutionTrace(
        trace_id=trace_id,
        context_id=context_id,
        root_event_id="evt-durable-root",
        chain=(
            ExecutionTraceStep(
                step_id="step.0",
                step_index=0,
                module="C15",
                action="workflow_trigger",
                input={"workflow_id": "workflow.demo"},
                output={"accepted": True},
                status="success",
                latency_ms=10,
                timestamp=BASE_TIME,
            ),
            ExecutionTraceStep(
                step_id="step.1",
                step_index=1,
                module="DB",
                action="write_success_failure",
                input={"table": "event_streams"},
                output={"stored": True},
                status="success",
                latency_ms=12,
                timestamp=BASE_TIME + timedelta(milliseconds=10),
                dependency_step_id="step.0",
            ),
        ),
        final_status="success",
        total_latency_ms=22,
    )


def _org_record(org_id: str) -> OrganizationRecord:
    return OrganizationRecord(
        org_id=org_id,
        org_name=f"Org {org_id[-6:]}",
        org_type="store",
        owner_user_id=f"owner-{org_id[-6:]}",
        status="active",
        metadata_json={},
    )


def _context(org_id: str) -> OrgDataIsolationUserContext:
    return OrgDataIsolationUserContext(
        org_id=org_id,
        user_id=f"user-{org_id[-6:]}",
        role="member",
        source="c17_durable_test",
        strict=True,
    )


def test_c17_event_write_is_db_first_and_reports_queue_status(
    clean_auth_tables: None,
) -> None:
    clear_event_buffer()

    event = emit_event(
        event_type="unit.durable",
        module="system",
        action="unit.durable",
        source="backend",
        status="success",
        context_id="ctx-durable-event",
        payload={"safe": "value", "api_key": "unsafe"},
        org_id="platform",
    )

    assert event.persisted is True
    assert event.queued is True
    assert event.success is True
    assert event.error is None

    with SessionLocal() as db:
        row = db.scalar(
            select(EventStreamRecord).where(
                EventStreamRecord.event_id == event.event_id
            )
        )

    assert row is not None
    assert row.org_id == "platform"
    assert row.context_id == "ctx-durable-event"
    assert row.payload["payload"]["api_key"] == "[redacted]"


def test_c17_db_storage_and_audit_query_are_persistent(
    clean_auth_tables: None,
) -> None:
    adapter = DBStorageAdapter(now=BASE_TIME, org_id="platform")
    adapter.write_log(_log_entry())
    adapter.append_event(
        EventRaw(
            event_id="evt-durable-raw",
            timestamp=BASE_TIME,
            context_id="ctx-durable-raw",
            trace_id="trace-durable-raw",
            module="C15",
            event_type="callback.received",
            action="callback received",
            source="webhook",
            status="success",
        )
    )

    queried_event = adapter.query_event(org_id="platform", module_id="C15")
    audit_result = AuditQueryEngine(adapter).search_logs(
        context_id="ctx-durable-001",
        module="C15",
    )
    audit_row = AuditLogWriter(org_id="platform").write_storage_record(
        adapter.records[0],
    )

    assert queried_event.total_count == 2
    assert audit_result.result_count == 1
    assert audit_result.data[0].event_id == "evt-durable-log"
    assert audit_row.org_id == "platform"

    with SessionLocal() as db:
        audit_count = len(tuple(db.scalars(select(AuditLogRecord))))
    assert audit_count == 1


def test_c17_event_stream_respects_c18_org_isolation(
    clean_auth_tables: None,
) -> None:
    org_a = generate_org_id()
    org_b = generate_org_id()
    with SessionLocal() as db:
        db.add_all([_org_record(org_a), _org_record(org_b)])
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_a)):
        DBStorageAdapter(db, now=BASE_TIME).append_event(
            EventRaw(
                event_id="evt-org-a",
                timestamp=BASE_TIME,
                context_id="ctx-org-a",
                trace_id="trace-org-a",
                module="C15",
                event_type="workflow.org_a",
                action="org a",
                source="backend",
                status="success",
            )
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_b)):
        DBStorageAdapter(db, now=BASE_TIME).append_event(
            EventRaw(
                event_id="evt-org-b",
                timestamp=BASE_TIME,
                context_id="ctx-org-b",
                trace_id="trace-org-b",
                module="C15",
                event_type="workflow.org_b",
                action="org b",
                source="backend",
                status="success",
            )
        )
        db.commit()

    with SessionLocal() as db, org_data_isolation_context(_context(org_a)):
        result = DBStorageAdapter(db).query_event(limit=10)

    assert [record.event_id for record in result.records] == ["evt-org-a"]
