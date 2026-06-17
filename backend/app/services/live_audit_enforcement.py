from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models.observability import AuditLogRecord, EventStreamRecord
from ..schemas.live_gate import LiveAuditEnforcementResult
from .event_collector import sanitize_event_payload


class LiveAuditEnforcer:
    """Synchronous C17 audit guard for live execution attempts."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def enforce(
        self,
        *,
        org_id: str,
        module_id: str,
        action: str,
        trace_id: str | None,
        execution_id: str | None,
        status: str,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LiveAuditEnforcementResult:
        if not trace_id or not execution_id:
            return LiveAuditEnforcementResult(
                enforced=False,
                trace_id=trace_id,
                execution_id=execution_id,
                event_stream_record_id=None,
                audit_id=None,
                status="failed",
                reason="Live audit enforcement requires trace_id and execution_id.",
            )
        if self.db is None:
            return LiveAuditEnforcementResult(
                enforced=False,
                trace_id=trace_id,
                execution_id=execution_id,
                event_stream_record_id=None,
                audit_id=None,
                status="failed",
                reason="Live audit enforcement requires a database session.",
            )

        now = datetime.now(UTC)
        event_id = f"live-gate-{uuid4()}"
        record_id = f"live-event-{event_id}"
        audit_id = f"audit-{uuid4()}"
        safe_payload = sanitize_event_payload(
            {
                "payload": dict(payload or {}),
                "metadata": {
                    **dict(metadata or {}),
                    "trace_id": trace_id,
                    "execution_id": execution_id,
                    "c17_live_audit_enforced": True,
                },
            }
        )
        row = EventStreamRecord(
            org_id=org_id,
            record_id=record_id,
            entity_type="LiveExecutionGate",
            event_id=event_id,
            context_id=execution_id,
            trace_id=trace_id,
            product_key=None,
            user_id=None,
            workflow_id=None,
            job_id=None,
            actor_id=None,
            module_id=module_id,
            event_type="live.execution.gate",
            action=action,
            source="backend",
            status="success" if status == "success" else "failed",
            latency_ms=0,
            timestamp=now,
            storage_tier="L1_hot",
            backend_targets=["postgresql"],
            payload=safe_payload,
            metadata_json={
                "trace_id": trace_id,
                "execution_id": execution_id,
                "c17_live_audit_enforced": True,
            },
            compressed=False,
            archive_object_key=None,
            processing_status="processed",
            processing_attempts=1,
            next_retry_at=None,
            processing_error=None,
            processed_at=now,
        )
        audit = AuditLogRecord(
            org_id=org_id,
            audit_id=audit_id,
            event_stream_record_id=record_id,
            event_id=event_id,
            context_id=execution_id,
            trace_id=trace_id,
            module_id=module_id,
            action=action,
            status=row.status,
            timestamp=now,
            payload=safe_payload,
            metadata_json={
                "trace_id": trace_id,
                "execution_id": execution_id,
                "event_stream_record_id": record_id,
                "c17_live_audit_enforced": True,
            },
        )
        self.db.add(row)
        self.db.add(audit)
        self.db.flush()
        return LiveAuditEnforcementResult(
            enforced=True,
            trace_id=trace_id,
            execution_id=execution_id,
            event_stream_record_id=record_id,
            audit_id=audit_id,
            status="emitted",
            reason="Live action emitted C17 event_streams and audit_logs.",
        )

    @staticmethod
    def skipped() -> LiveAuditEnforcementResult:
        return LiveAuditEnforcementResult(
            enforced=False,
            trace_id=None,
            execution_id=None,
            event_stream_record_id=None,
            audit_id=None,
            status="skipped",
            reason="Live audit enforcement is only required for live mode.",
        )
