from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Mapping
from contextvars import Token, ContextVar
from dataclasses import dataclass
from typing import Any, get_args
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from ..schemas.event_collector import (
    AuditEvent,
    EmittedAuditEvent,
    EventModule,
    EventSource,
    EventStatus,
)

EVENT_LOGGER_NAME = "barong.audit_events"
DEFAULT_EVENT_BUFFER_SIZE = 5000
DEFAULT_EVENT_QUEUE_SIZE = 10000
COLLECTOR_RECORD_PREFIX = "event-"
PLATFORM_ORG_ID = "platform"
VALID_EVENT_MODULES = frozenset(get_args(EventModule))
VALID_EVENT_SOURCES = frozenset(get_args(EventSource))
VALID_EVENT_STATUSES = frozenset(get_args(EventStatus))
MAX_STRING_LENGTH = 2000
SENSITIVE_KEY_MARKERS = (
    "password",
    "passwd",
    "password_hash",
    "token",
    "secret",
    "session_id",
    "cookie",
    "set-cookie",
    "signature",
    "nonce",
    "idempotency",
    "authorization",
    "api_key",
    "private_key",
    "credential",
    "webhook_url",
    "provider_url",
    "endpoint",
)

_context_id: ContextVar[str | None] = ContextVar(
    "event_context_id",
    default=None,
)
_user_id: ContextVar[str | None] = ContextVar("event_user_id", default=None)
_product_key: ContextVar[str | None] = ContextVar(
    "event_product_key",
    default=None,
)
_workflow_id: ContextVar[str | None] = ContextVar(
    "event_workflow_id",
    default=None,
)
_org_id: ContextVar[str | None] = ContextVar("event_org_id", default=None)


@dataclass(frozen=True)
class EventQueueWriteResult:
    persisted: bool
    queued: bool
    record_id: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.persisted and self.queued and self.error is None


class EventQueueBackend:
    def __init__(
        self,
        *,
        queue_size: int = DEFAULT_EVENT_QUEUE_SIZE,
        snapshot_limit: int = DEFAULT_EVENT_BUFFER_SIZE,
    ) -> None:
        self._queue: queue.Queue[str] = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._snapshot_limit = snapshot_limit
        self._failed = 0
        self._emitted = 0
        self._started = False
        self._worker: threading.Thread | None = None
        self._logger = logging.getLogger(EVENT_LOGGER_NAME)
        self._tables_ready = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._worker = threading.Thread(
                target=self._drain,
                name="barong-audit-event-queue",
                daemon=True,
            )
            self._worker.start()
            self._started = True

    def emit(
        self,
        event: AuditEvent,
        *,
        org_id: str | None = None,
    ) -> EventQueueWriteResult:
        write = self._write_event(event, org_id=org_id)
        if not write.persisted or write.record_id is None:
            with self._lock:
                self._failed += 1
            return write

        try:
            self._queue.put_nowait(write.record_id)
        except queue.Full:
            self._mark_processing_status(
                write.record_id,
                status="queue_full",
                error="event processing queue is full",
            )
            with self._lock:
                self._failed += 1
            return EventQueueWriteResult(
                persisted=True,
                queued=False,
                record_id=write.record_id,
                error="event processing queue is full",
            )

        self.start()
        with self._lock:
            self._emitted += 1
        return EventQueueWriteResult(
            persisted=True,
            queued=True,
            record_id=write.record_id,
        )

    def snapshot(self) -> list[AuditEvent]:
        self._ensure_tables()
        from sqlalchemy import select

        from ..db.session import SessionLocal
        from ..models.observability import EventStreamRecord

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(EventStreamRecord)
                    .where(EventStreamRecord.record_id.like(f"{COLLECTOR_RECORD_PREFIX}%"))
                    .order_by(
                        EventStreamRecord.timestamp.desc(),
                        EventStreamRecord.id.desc(),
                    )
                    .limit(self._snapshot_limit)
                )
            )
        rows.reverse()
        return [self._audit_event_from_record(row) for row in rows]

    def clear(self) -> None:
        self._ensure_tables()
        from sqlalchemy import delete

        from ..db.session import SessionLocal
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with SessionLocal() as db:
                db.execute(
                    delete(EventStreamRecord).where(
                        EventStreamRecord.record_id.like(
                            f"{COLLECTOR_RECORD_PREFIX}%"
                        )
                    )
                )
                db.commit()
        with self._lock:
            self._failed = 0
            self._emitted = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            self._queue.task_done()

    def stats(self) -> dict[str, int]:
        self._ensure_tables()
        from sqlalchemy import func, select

        from ..db.session import SessionLocal
        from ..models.observability import EventStreamRecord

        with SessionLocal() as db:
            stored = db.scalar(
                select(func.count())
                .select_from(EventStreamRecord)
                .where(EventStreamRecord.record_id.like(f"{COLLECTOR_RECORD_PREFIX}%"))
            )
        with self._lock:
            return {
                "buffered": int(stored or 0),
                "queued": self._queue.qsize(),
                "emitted": self._emitted,
                "dropped": 0,
                "failed": self._failed,
            }

    def _drain(self) -> None:
        while True:
            record_id = self._queue.get()
            try:
                try:
                    self._process_record(record_id)
                except Exception as exc:
                    self._logger.exception(
                        "C17 event queue processing failed for %s",
                        record_id,
                    )
                    try:
                        self._mark_processing_status(
                            record_id,
                            status="processing_failed",
                            error=str(exc),
                        )
                    except Exception:
                        self._logger.exception(
                            "C17 event queue failed to mark processing failure for %s",
                            record_id,
                        )
            finally:
                self._queue.task_done()

    def _write_event(
        self,
        event: AuditEvent,
        *,
        org_id: str | None,
    ) -> EventQueueWriteResult:
        try:
            self._ensure_tables()
            from ..db.session import SessionLocal
            from ..models.observability import EventStreamRecord
            from .data_isolation import without_org_data_isolation
            from .storage_layer import storage_record_from_event_raw

            record = storage_record_from_event_raw(event)
            record.record_id = f"{COLLECTOR_RECORD_PREFIX}{event.event_id}"
            metadata = {
                **dict(event.metadata),
                "c17_collector": "EventQueueBackend",
            }
            resolved_org_id = self._resolve_org_id(
                event,
                explicit_org_id=org_id,
            )
            row = EventStreamRecord(
                org_id=resolved_org_id,
                record_id=record.record_id,
                entity_type=record.entity_type,
                event_id=record.event_id,
                context_id=record.context_id,
                trace_id=record.trace_id,
                product_key=record.product_key,
                user_id=record.user_id,
                workflow_id=event.workflow_id,
                module_id=record.module,
                event_type=record.event_type,
                action=event.action,
                source=event.source,
                status=record.status,
                latency_ms=event.latency_ms,
                timestamp=record.timestamp,
                storage_tier=record.tier,
                backend_targets=list(record.backend_targets),
                payload=record.payload,
                metadata_json=metadata,
                compressed=record.compressed,
                archive_object_key=record.archive_object_key,
                processing_status="queued",
            )
            with without_org_data_isolation():
                with SessionLocal() as db:
                    db.add(row)
                    db.commit()
            return EventQueueWriteResult(
                persisted=True,
                queued=False,
                record_id=record.record_id,
            )
        except SQLAlchemyError as exc:
            return EventQueueWriteResult(
                persisted=False,
                queued=False,
                error=str(exc),
            )
        except Exception as exc:
            return EventQueueWriteResult(
                persisted=False,
                queued=False,
                error=str(exc),
            )

    def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        with self._lock:
            if self._tables_ready:
                return
            from ..db.base import Base
            from ..db.session import engine
            from ..models.observability import (
                AnomalyEventRecord,
                AuditLogRecord,
                EventStreamRecord,
                ReplayJobRecord,
            )

            Base.metadata.create_all(
                bind=engine,
                tables=[
                    EventStreamRecord.__table__,
                    AuditLogRecord.__table__,
                    ReplayJobRecord.__table__,
                    AnomalyEventRecord.__table__,
                ],
                checkfirst=True,
            )
            self._tables_ready = True

    def _resolve_org_id(
        self,
        event: AuditEvent,
        *,
        explicit_org_id: str | None,
    ) -> str:
        for value in (explicit_org_id, _org_id.get()):
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]

        try:
            from .data_isolation import current_org_data_isolation_context

            context = current_org_data_isolation_context()
        except Exception:
            context = None
        if context is not None and context.org_id:
            return context.org_id[:40]

        for source in (event.metadata, event.payload):
            for key in ("org_id", "active_org_id", "tenant_org_id"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:40]
        return PLATFORM_ORG_ID

    def _mark_processing_status(
        self,
        record_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        self._ensure_tables()
        from datetime import UTC, datetime

        from sqlalchemy import update

        from ..db.session import SessionLocal
        from ..models.observability import EventStreamRecord
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with SessionLocal() as db:
                db.execute(
                    update(EventStreamRecord)
                    .where(EventStreamRecord.record_id == record_id)
                    .values(
                        processing_status=status,
                        processing_error=error,
                        processed_at=datetime.now(UTC),
                    )
                )
                db.commit()

    def _process_record(self, record_id: str) -> None:
        self._ensure_tables()
        from datetime import UTC, datetime

        from sqlalchemy import select

        from ..db.session import SessionLocal
        from ..models.observability import EventStreamRecord
        from .audit_query_engine import AuditLogWriter
        from .data_isolation import without_org_data_isolation

        with without_org_data_isolation():
            with SessionLocal() as db:
                row = db.scalar(
                    select(EventStreamRecord).where(
                        EventStreamRecord.record_id == record_id
                    )
                )
                if row is None:
                    return
                event = self._audit_event_from_record(row)
                self._logger.info(
                    json.dumps(event.model_dump(mode="json"), sort_keys=True)
                )
                AuditLogWriter(db, org_id=row.org_id).write_event_stream(row)
                row.processing_status = "processed"
                row.processing_error = None
                row.processed_at = datetime.now(UTC)
                db.commit()

    def _audit_event_from_record(self, row: Any) -> AuditEvent:
        payload = row.payload if isinstance(row.payload, Mapping) else {}
        raw_payload = payload.get("payload") if isinstance(payload, Mapping) else {}
        raw_metadata = payload.get("metadata") if isinstance(payload, Mapping) else {}
        module = row.module_id if row.module_id in VALID_EVENT_MODULES else "system"
        source = row.source if row.source in VALID_EVENT_SOURCES else "system"
        status = row.status if row.status in VALID_EVENT_STATUSES else "pending"
        return AuditEvent(
            event_id=row.event_id,
            timestamp=row.timestamp,
            event_type=row.event_type,
            module=module,
            action=row.action,
            context_id=row.context_id,
            user_id=row.user_id,
            product_key=row.product_key,
            workflow_id=row.workflow_id,
            source=source,
            status=status,
            latency_ms=max(float(row.latency_ms or 0), 0),
            payload=dict(raw_payload or {}),
            metadata=dict(raw_metadata or {}),
        )


EventEmitter = EventQueueBackend
DEFAULT_EVENT_EMITTER = EventQueueBackend()


def _truncate(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return f"{value[:MAX_STRING_LENGTH]}...[truncated]"


def sanitize_event_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if any(marker in normalized_key for marker in SENSITIVE_KEY_MARKERS):
                sanitized[str(key)] = "[redacted]"
                continue
            sanitized[str(key)] = sanitize_event_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_event_payload(item) for item in value]
    if isinstance(value, str):
        return _truncate(value)
    return value


def generate_context_id() -> str:
    return str(uuid4())


def normalize_context_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if not candidate or len(candidate) > 128:
        return generate_context_id()
    lowered = candidate.lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return generate_context_id()
    return candidate


def current_context_id() -> str | None:
    return _context_id.get()


def set_current_event_context(
    *,
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, Token[str | None]]:
    tokens: dict[str, Token[str | None]] = {}
    if context_id is not None:
        tokens["context_id"] = _context_id.set(normalize_context_id(context_id))
    if user_id is not None:
        tokens["user_id"] = _user_id.set(user_id)
    if product_key is not None:
        tokens["product_key"] = _product_key.set(product_key)
    if workflow_id is not None:
        tokens["workflow_id"] = _workflow_id.set(workflow_id)
    if org_id is not None:
        tokens["org_id"] = _org_id.set(org_id)
    return tokens


def reset_current_event_context(tokens: Mapping[str, Token[str | None]]) -> None:
    resetters = {
        "context_id": _context_id,
        "user_id": _user_id,
        "product_key": _product_key,
        "workflow_id": _workflow_id,
        "org_id": _org_id,
    }
    for key, token in tokens.items():
        resetters[key].reset(token)


def emit_event(
    *,
    event_type: str,
    module: EventModule = "system",
    action: str,
    source: EventSource = "backend",
    status: EventStatus = "success",
    context_id: str | None = None,
    user_id: str | None = None,
    product_key: str | None = None,
    workflow_id: str | None = None,
    org_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EmittedAuditEvent:
    effective_context_id = normalize_context_id(context_id or _context_id.get())
    event = AuditEvent(
        event_type=event_type,
        module=module,
        action=action,
        context_id=effective_context_id,
        user_id=user_id if user_id is not None else _user_id.get(),
        product_key=(
            product_key if product_key is not None else _product_key.get()
        ),
        workflow_id=(
            workflow_id if workflow_id is not None else _workflow_id.get()
        ),
        source=source,
        status=status,
        latency_ms=max(latency_ms, 0),
        payload=sanitize_event_payload(dict(payload or {})),
        metadata=sanitize_event_payload(dict(metadata or {})),
    )
    result = DEFAULT_EVENT_EMITTER.emit(event, org_id=org_id)
    return EmittedAuditEvent(
        **event.model_dump(mode="python"),
        persisted=result.persisted,
        queued=result.queued,
        success=result.success,
        error=result.error,
    )


def classify_module_from_path(path: str) -> EventModule:
    normalized = path.lower()
    if "/module-switch" in normalized or "/emergency-kill-switch" in normalized:
        return "C13"
    if any(
        marker in normalized
        for marker in (
            "/external-dependencies",
            "/dependency",
            "/ai-execution-bindings",
            "/model-locks",
            "/capability-bindings",
            "/module-allocations",
            "/execution-prompts",
        )
    ):
        return "C14"
    if any(
        marker in normalized
        for marker in (
            "/workflow",
            "/webhook-gateway",
            "/payload-standardization",
            "/callback-handler",
            "/result-normalization",
            "/failure-handling",
            "/n8n-test",
        )
    ):
        return "C15"
    if "/security" in normalized or "/control-plane" in normalized:
        return "C16"
    if "/products" in normalized or "/product" in normalized:
        return "Pxx"
    return "system"


def record_workflow_event(
    *,
    event_type: str,
    action: str,
    context_id: str,
    workflow_id: str | None,
    module_key: str | None = None,
    status: EventStatus = "success",
    source: EventSource = "n8n",
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=event_type,
        module="C15",
        action=action,
        source=source,
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={"module": module_key, **dict(payload or {})},
        metadata=metadata,
    )


def record_llm_request(
    *,
    provider: str,
    model: str,
    context_id: str | None = None,
    prompt_input: Any = None,
    workflow_id: str | None = None,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.request",
        module=module,
        action="llm.request",
        source="ai",
        status="pending",
        context_id=context_id,
        workflow_id=workflow_id,
        payload={
            "provider": provider,
            "model": model,
            "prompt_input": prompt_input,
        },
        metadata=metadata,
    )


def record_llm_response(
    *,
    provider: str,
    model: str,
    status: EventStatus,
    context_id: str | None = None,
    prompt_output: Any = None,
    token_usage: Mapping[str, Any] | None = None,
    workflow_id: str | None = None,
    latency_ms: float = 0,
    module: EventModule = "C14",
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type="ai.llm.response",
        module=module,
        action="llm.response",
        source="ai",
        status=status,
        context_id=context_id,
        workflow_id=workflow_id,
        latency_ms=latency_ms,
        payload={
            "provider": provider,
            "model": model,
            "prompt_output": prompt_output,
            "token_usage": dict(token_usage or {}),
        },
        metadata=metadata,
    )


def record_file_operation(
    *,
    action: str,
    storage_provider: str,
    storage_ref: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"file.{action}",
        module="system",
        action=f"file.{action}",
        source="system",
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={
            "storage_provider": storage_provider,
            "storage_ref": storage_ref,
            **dict(payload or {}),
        },
        metadata=metadata,
    )


def record_filebrowser_operation(
    *,
    action: str,
    path: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="FileBrowser",
        storage_ref=path,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload=payload,
        metadata=metadata,
    )


def record_minio_operation(
    *,
    action: str,
    object_key: str | None = None,
    bucket: str | None = None,
    status: EventStatus = "success",
    context_id: str | None = None,
    latency_ms: float = 0,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return record_file_operation(
        action=action,
        storage_provider="MinIO",
        storage_ref=object_key,
        status=status,
        context_id=context_id,
        latency_ms=latency_ms,
        payload={"bucket": bucket, **dict(payload or {})},
        metadata=metadata,
    )


def record_product_knowledge_event(
    *,
    action: str,
    status: EventStatus = "success",
    context_id: str | None = None,
    product_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuditEvent:
    return emit_event(
        event_type=f"product_knowledge.{action}",
        module="Pxx",
        action=f"product_knowledge.{action}",
        source="system",
        status=status,
        context_id=context_id,
        product_key=product_key,
        payload=payload,
        metadata=metadata,
    )


def get_event_buffer_snapshot() -> list[AuditEvent]:
    return DEFAULT_EVENT_EMITTER.snapshot()


def clear_event_buffer() -> None:
    DEFAULT_EVENT_EMITTER.clear()


def get_event_emitter_stats() -> dict[str, int]:
    return DEFAULT_EVENT_EMITTER.stats()
