from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import Base
from ..models.observability import (
    AnomalyEventRecord,
    AuditLogRecord,
    EventStreamRecord,
    ReplayJobRecord,
    StorageEventRecord,
)
from ..schemas.event_collector import AuditEvent
from ..schemas.execution_trace import ExecutionTrace
from ..schemas.storage_layer import (
    HOT_RETENTION_DAYS,
    STORAGE_INDEX_FIELDS,
    WARM_RETENTION_DAYS,
    C17CToC17DStorageMigrationStrategy,
    EventRaw,
    HotWarmColdDataFlow,
    QueryPerformanceStrategy,
    StorageAdapterInterfaceDesign,
    StorageArchiveResult,
    StorageArchitectureDesign,
    StorageBackend,
    StorageBackendDesign,
    StorageDataModelDesign,
    StorageIndexingStrategy,
    StorageLayerCompletionStatus,
    StorageRecordEnvelope,
    StorageRetentionPolicy,
    StorageTier,
    StorageTimeRange,
    StorageWritePathDesign,
    StorageWriteResult,
    StorageQueryResult,
    utc_now,
)
from ..schemas.structured_logs import LogEntry
from .event_collector import normalize_context_id, sanitize_event_payload
from .execution_trace import execution_trace_to_db_record
from .structured_logs import log_entry_to_db_record


class StorageAdapter(Protocol):
    def write_log(self, log: LogEntry) -> StorageWriteResult:
        ...

    def write_trace(self, trace: ExecutionTrace) -> StorageWriteResult:
        ...

    def write_event_raw(self, raw_event: EventRaw | AuditEvent) -> StorageWriteResult:
        ...

    def append_event(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
        *,
        org_id: str | None = None,
    ) -> StorageWriteResult:
        ...

    def query_event(
        self,
        *,
        event_id: str | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def query_by_context_id(
        self,
        context_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def query_by_trace_id(
        self,
        trace_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def query_by_time_range(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        ...

    def archive_to_cold_storage(
        self,
        *,
        before: datetime | None = None,
        batch_size: int | None = None,
    ) -> StorageArchiveResult:
        ...


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return sanitize_event_payload(dict(value))
    return {}


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _timestamp_value(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return utc_now()
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return utc_now()


def _first_present(
    sources: tuple[Mapping[str, Any], ...],
    keys: tuple[str, ...],
) -> Any:
    for source in sources:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _status_value(value: Any) -> str:
    text = (_string_value(value) or "pending").lower().replace("-", "_")
    if text in {"success", "failed", "pending", "partial"}:
        return text
    if text in {"complete", "completed", "ok", "succeeded"}:
        return "success"
    if text in {"error", "errored", "failure", "rejected", "denied"}:
        return "failed"
    return "pending"


def _trace_timestamp(trace: ExecutionTrace) -> datetime:
    if not trace.chain:
        return utc_now()
    return min(step.timestamp for step in trace.chain)


def _trace_modules(trace: ExecutionTrace) -> list[str]:
    return sorted({step.module for step in trace.chain}) or ["system"]


def _chain_value(trace: ExecutionTrace, key: str) -> str | None:
    for step in trace.chain:
        for source in (step.input, step.output):
            value = _string_value(source.get(key))
            if value is not None:
                return value
    return None


def _archive_object_key(record: StorageRecordEnvelope) -> str:
    stamp = record.timestamp.strftime("%Y/%m/%d")
    entity = record.entity_type.lower()
    return f"c17d/{entity}/{stamp}/{record.context_id}/{record.record_id}.jsonl.gz"


def ensure_observability_tables() -> None:
    from ..db.session import engine

    Base.metadata.create_all(
        bind=engine,
        tables=[
            EventStreamRecord.__table__,
            AuditLogRecord.__table__,
            ReplayJobRecord.__table__,
            AnomalyEventRecord.__table__,
            StorageEventRecord.__table__,
        ],
        checkfirst=True,
    )


def resolve_storage_tier(
    timestamp: datetime,
    *,
    now: datetime | None = None,
) -> StorageTier:
    current = _timestamp_value(now) if now is not None else utc_now()
    observed_at = _timestamp_value(timestamp)
    age_days = max((current - observed_at).total_seconds() / 86400, 0)
    if age_days <= HOT_RETENTION_DAYS:
        return "L1_hot"
    if age_days <= WARM_RETENTION_DAYS:
        return "L2_warm"
    return "L3_cold"


def backend_targets_for_tier(tier: StorageTier) -> tuple[StorageBackend, ...]:
    if tier == "L1_hot":
        return ("postgresql", "redis")
    if tier == "L2_warm":
        return ("postgresql",)
    return ("s3_object_storage", "postgresql")


def normalize_event_raw(raw_event: EventRaw | AuditEvent | Mapping[str, Any]) -> EventRaw:
    if isinstance(raw_event, EventRaw):
        return raw_event
    if isinstance(raw_event, AuditEvent):
        raw = raw_event.model_dump(mode="python")
    elif isinstance(raw_event, Mapping):
        raw = dict(raw_event)
    else:
        raise TypeError("C17D raw event storage accepts EventRaw, AuditEvent, or mapping.")

    payload = _dict_value(raw.get("payload"))
    metadata = _dict_value(raw.get("metadata"))
    context_id = normalize_context_id(
        _string_value(
            _first_present(
                (raw, payload, metadata),
                (
                    "context_id",
                    "contextId",
                    "trace_id",
                    "traceId",
                    "correlation_id",
                    "correlationId",
                    "request_id",
                    "requestId",
                ),
            )
        )
    )
    trace_id = _string_value(
        _first_present((raw, payload, metadata), ("trace_id", "traceId"))
    )
    event_type = _string_value(raw.get("event_type")) or "unknown.event"
    return EventRaw(
        event_id=_string_value(raw.get("event_id")) or event_type,
        timestamp=_timestamp_value(raw.get("timestamp")),
        context_id=context_id,
        trace_id=normalize_context_id(trace_id) if trace_id is not None else context_id,
        product_key=_string_value(
            _first_present((raw, payload, metadata), ("product_key", "productKey"))
        ),
        user_id=_string_value(
            _first_present((raw, payload, metadata), ("user_id", "userId"))
        ),
        workflow_id=_string_value(
            _first_present((raw, payload, metadata), ("workflow_id", "workflowId"))
        ),
        module=_string_value(raw.get("module")) or "system",
        event_type=event_type,
        action=_string_value(raw.get("action")) or event_type,
        source=_string_value(raw.get("source")) or "system",
        status=_status_value(raw.get("status")),  # type: ignore[arg-type]
        payload=payload,
        metadata=metadata,
    )


def _write_result(record: StorageRecordEnvelope) -> StorageWriteResult:
    return StorageWriteResult(
        record_id=record.record_id,
        entity_type=record.entity_type,
        tier=record.tier,
        backend_targets=record.backend_targets,
        context_id=record.context_id,
        trace_id=record.trace_id,
        event_id=record.event_id,
        archive_object_key=record.archive_object_key,
    )


def storage_record_from_log_entry(
    log: LogEntry,
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    if not isinstance(log, LogEntry):
        raise TypeError("C17D write_log accepts only C17B LogEntry.")

    record = log_entry_to_db_record(log)
    trace_id = (
        _string_value(log.request.get("trace_id"))
        or _string_value(log.request.get("traceId"))
        or _string_value(log.response.get("trace_id"))
        or _string_value(log.response.get("traceId"))
        or log.entity.request_id
        or log.context_id
    )
    tier = resolve_storage_tier(log.timestamp, now=now)
    return StorageRecordEnvelope(
        entity_type="LogEntry",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=log.context_id,
        trace_id=trace_id,
        event_id=log.event_id,
        product_key=log.entity.product_key,
        user_id=log.entity.user_id,
        module=log.module,
        event_type=log.event_type,
        timestamp=log.timestamp,
        status=log.status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


def storage_record_from_execution_trace(
    trace: ExecutionTrace,
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    if not isinstance(trace, ExecutionTrace):
        raise TypeError("C17D write_trace accepts only C17C ExecutionTrace.")

    record = execution_trace_to_db_record(trace)
    timestamp = _trace_timestamp(trace)
    tier = resolve_storage_tier(timestamp, now=now)
    modules = _trace_modules(trace)
    return StorageRecordEnvelope(
        entity_type="ExecutionTrace",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=trace.context_id,
        trace_id=trace.trace_id,
        event_id=trace.root_event_id,
        product_key=_chain_value(trace, "product_key"),
        user_id=_chain_value(trace, "user_id"),
        module=modules[0],
        event_type="execution.trace",
        timestamp=timestamp,
        status=trace.final_status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


def storage_record_from_event_raw(
    raw_event: EventRaw | AuditEvent | Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> StorageRecordEnvelope:
    raw = normalize_event_raw(raw_event)
    record = raw.model_dump(mode="json")
    tier = resolve_storage_tier(raw.timestamp, now=now)
    return StorageRecordEnvelope(
        entity_type="EventRaw",
        tier=tier,
        backend_targets=backend_targets_for_tier(tier),
        context_id=raw.context_id,
        trace_id=raw.trace_id or raw.context_id,
        event_id=raw.event_id,
        product_key=raw.product_key,
        user_id=raw.user_id,
        module=raw.module,
        event_type=raw.event_type,
        timestamp=raw.timestamp,
        status=raw.status,
        payload=record,
        compressed=tier == "L3_cold",
        archive_object_key=None,
    )


class InMemoryStorageAdapter:
    """Side-effect-free adapter used for C17D design validation tests."""

    def __init__(self, *, now: datetime | None = None) -> None:
        self._records: list[StorageRecordEnvelope] = []
        self._now = _timestamp_value(now) if now is not None else None

    @property
    def records(self) -> tuple[StorageRecordEnvelope, ...]:
        return tuple(self._records)

    def write_log(self, log: LogEntry) -> StorageWriteResult:
        record = storage_record_from_log_entry(log, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def write_trace(self, trace: ExecutionTrace) -> StorageWriteResult:
        record = storage_record_from_execution_trace(trace, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def write_event_raw(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
    ) -> StorageWriteResult:
        record = storage_record_from_event_raw(raw_event, now=self._now)
        self._records.append(record)
        return _write_result(record)

    def append_event(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
        *,
        org_id: str | None = None,
    ) -> StorageWriteResult:
        del org_id
        return self.write_event_raw(raw_event)

    def query_event(
        self,
        *,
        event_id: str | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        limit: int | None = None,
    ) -> StorageQueryResult:
        del org_id
        return self._query(
            lambda record: (
                (event_id is None or record.event_id == event_id)
                and (module_id is None or record.module == module_id)
                and (context_id is None or record.context_id == context_id)
                and (trace_id is None or record.trace_id == trace_id)
            ),
            indexes_used=("idx_c17d_event_id", "idx_c17d_module_event_type"),
            limit=limit,
        )

    def query_by_context_id(
        self,
        context_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        normalized = normalize_context_id(context_id)
        return self._query(
            lambda record: record.context_id == normalized,
            indexes_used=("idx_c17d_context_id",),
            limit=limit,
        )

    def query_by_trace_id(
        self,
        trace_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        normalized = normalize_context_id(trace_id)
        return self._query(
            lambda record: record.trace_id == normalized,
            indexes_used=("idx_c17d_trace_id",),
            limit=limit,
        )

    def query_by_time_range(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query(
            lambda record: (
                (time_range.start_at is None or record.timestamp >= time_range.start_at)
                and (time_range.end_at is None or record.timestamp <= time_range.end_at)
            ),
            indexes_used=("idx_c17d_timestamp",),
            limit=limit,
        )

    def archive_to_cold_storage(
        self,
        *,
        before: datetime | None = None,
        batch_size: int | None = None,
    ) -> StorageArchiveResult:
        current = self._now or utc_now()
        cutoff = _timestamp_value(before) if before is not None else (
            current - timedelta(days=WARM_RETENTION_DAYS)
        )
        candidates = [
            record
            for record in self._records
            if record.tier != "L3_cold" and record.timestamp < cutoff
        ]
        selected = candidates[:batch_size] if batch_size is not None else candidates

        keys: list[str] = []
        for record in selected:
            object_key = record.archive_object_key or _archive_object_key(record)
            record.tier = "L3_cold"
            record.backend_targets = backend_targets_for_tier("L3_cold")
            record.compressed = True
            record.archive_object_key = object_key
            keys.append(object_key)

        return StorageArchiveResult(
            candidate_count=len(candidates),
            archived_count=len(selected),
            archive_object_keys=tuple(keys),
        )

    def _query(
        self,
        predicate: Any,
        *,
        indexes_used: tuple[str, ...],
        limit: int | None,
    ) -> StorageQueryResult:
        matched = [record for record in self._records if predicate(record)]
        matched.sort(key=lambda record: record.timestamp, reverse=True)
        total_count = len(matched)
        if limit is not None:
            matched = matched[: max(limit, 0)]
        searched_tiers = tuple(dict.fromkeys(record.tier for record in matched))
        if not searched_tiers:
            searched_tiers = ("L1_hot", "L2_warm", "L3_cold")
        return StorageQueryResult(
            records=tuple(matched),
            total_count=total_count,
            searched_tiers=searched_tiers,
            indexes_used=indexes_used,
        )


def _metadata_for_record(record: StorageRecordEnvelope) -> dict[str, Any]:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    if record.entity_type == "EventRaw":
        return _dict_value(payload.get("metadata"))
    if record.entity_type == "LogEntry":
        return _dict_value(payload.get("metadata"))
    return {}


def _action_for_record(record: StorageRecordEnvelope) -> str:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    if record.entity_type == "EventRaw":
        return _string_value(payload.get("action")) or record.event_type
    if record.entity_type == "LogEntry":
        return _string_value(payload.get("action")) or record.event_type
    return "execution.trace"


def _source_for_record(record: StorageRecordEnvelope) -> str:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    if record.entity_type in {"EventRaw", "LogEntry"}:
        return _string_value(payload.get("source")) or "system"
    return "trace"


def _workflow_id_for_record(record: StorageRecordEnvelope) -> str | None:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    if record.entity_type == "EventRaw":
        return _string_value(payload.get("workflow_id"))
    if record.entity_type == "LogEntry":
        entity = payload.get("entity")
        if isinstance(entity, Mapping):
            return _string_value(entity.get("workflow_id"))
    return None


def _latency_for_record(record: StorageRecordEnvelope) -> float:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    value = payload.get("total_latency_ms" if record.entity_type == "ExecutionTrace" else "latency_ms")
    try:
        return max(float(value), 0)
    except (TypeError, ValueError):
        return 0


def _record_to_event_stream_row(
    record: StorageRecordEnvelope,
    *,
    org_id: str,
) -> EventStreamRecord:
    return EventStreamRecord(
        org_id=org_id,
        record_id=record.record_id,
        entity_type=record.entity_type,
        event_id=record.event_id,
        context_id=record.context_id,
        trace_id=record.trace_id,
        product_key=record.product_key,
        user_id=record.user_id,
        workflow_id=_workflow_id_for_record(record),
        module_id=record.module,
        event_type=record.event_type,
        action=_action_for_record(record),
        source=_source_for_record(record),
        status=record.status,
        latency_ms=_latency_for_record(record),
        timestamp=record.timestamp,
        storage_tier=record.tier,
        backend_targets=list(record.backend_targets),
        payload=_json_safe(record.payload),
        metadata_json=_json_safe(_metadata_for_record(record)),
        compressed=record.compressed,
        archive_object_key=record.archive_object_key,
        processing_status="stored",
    )


def _record_to_storage_event_row(
    record: StorageRecordEnvelope,
    *,
    org_id: str,
    operation: str,
    status: str,
    payload: Mapping[str, Any] | None = None,
) -> StorageEventRecord:
    return StorageEventRecord(
        org_id=org_id,
        storage_event_id=f"storage-event-{uuid4()}",
        record_id=record.record_id,
        operation=operation,
        entity_type=record.entity_type,
        context_id=record.context_id,
        trace_id=record.trace_id,
        event_id=record.event_id,
        module_id=record.module,
        storage_tier=record.tier,
        backend_targets=list(record.backend_targets),
        status=status,
        payload=_json_safe(dict(payload or {})),
        occurred_at=utc_now(),
    )


def storage_record_from_event_stream_row(
    row: EventStreamRecord,
) -> StorageRecordEnvelope:
    return StorageRecordEnvelope(
        record_id=row.record_id,
        entity_type=row.entity_type,  # type: ignore[arg-type]
        tier=row.storage_tier,  # type: ignore[arg-type]
        backend_targets=tuple(row.backend_targets),  # type: ignore[arg-type]
        context_id=row.context_id,
        trace_id=row.trace_id,
        event_id=row.event_id,
        product_key=row.product_key,
        user_id=row.user_id,
        module=row.module_id,
        event_type=row.event_type,
        timestamp=row.timestamp,
        status=row.status,  # type: ignore[arg-type]
        payload=dict(row.payload),
        compressed=row.compressed,
        archive_object_key=row.archive_object_key,
    )


class DBStorageAdapter:
    """DB-backed C17D adapter using event_streams as the durable record source."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        now: datetime | None = None,
        org_id: str | None = None,
    ) -> None:
        ensure_observability_tables()
        self._db = db
        self._now = _timestamp_value(now) if now is not None else None
        self._org_id = org_id

    @property
    def records(self) -> tuple[StorageRecordEnvelope, ...]:
        return self._query_rows(limit=None).records

    def write_log(self, log: LogEntry) -> StorageWriteResult:
        record = storage_record_from_log_entry(log, now=self._now)
        self._append_record(record)
        return _write_result(record)

    def write_trace(self, trace: ExecutionTrace) -> StorageWriteResult:
        record = storage_record_from_execution_trace(trace, now=self._now)
        self._append_record(record)
        return _write_result(record)

    def write_event_raw(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
    ) -> StorageWriteResult:
        return self.append_event(raw_event)

    def append_event(
        self,
        raw_event: EventRaw | AuditEvent | Mapping[str, Any],
        *,
        org_id: str | None = None,
    ) -> StorageWriteResult:
        record = storage_record_from_event_raw(raw_event, now=self._now)
        self._append_record(record, org_id=org_id)
        return _write_result(record)

    def query_event(
        self,
        *,
        event_id: str | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query_rows(
            event_id=event_id,
            org_id=org_id,
            module_id=module_id,
            context_id=context_id,
            trace_id=trace_id,
            limit=limit,
            indexes_used=("idx_c17d_event_id", "idx_c17d_module_event_type"),
        )

    def query_by_context_id(
        self,
        context_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query_rows(
            context_id=normalize_context_id(context_id),
            limit=limit,
            indexes_used=("idx_c17d_context_id",),
        )

    def query_by_trace_id(
        self,
        trace_id: str,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query_rows(
            trace_id=normalize_context_id(trace_id),
            limit=limit,
            indexes_used=("idx_c17d_trace_id",),
        )

    def query_by_time_range(
        self,
        time_range: StorageTimeRange,
        *,
        limit: int | None = None,
    ) -> StorageQueryResult:
        return self._query_rows(
            start_at=time_range.start_at,
            end_at=time_range.end_at,
            limit=limit,
            indexes_used=("idx_c17d_timestamp",),
        )

    def archive_to_cold_storage(
        self,
        *,
        before: datetime | None = None,
        batch_size: int | None = None,
    ) -> StorageArchiveResult:
        current = self._now or utc_now()
        cutoff = _timestamp_value(before) if before is not None else (
            current - timedelta(days=WARM_RETENTION_DAYS)
        )
        with self._session() as db:
            statement = (
                select(EventStreamRecord)
                .where(
                    EventStreamRecord.storage_tier != "L3_cold",
                    EventStreamRecord.timestamp < cutoff,
                )
                .order_by(EventStreamRecord.timestamp)
            )
            if self._org_id is not None:
                statement = statement.where(EventStreamRecord.org_id == self._org_id)
            if batch_size is not None:
                statement = statement.limit(max(batch_size, 0))
            rows = list(db.scalars(statement))
            keys: list[str] = []
            for row in rows:
                record = storage_record_from_event_stream_row(row)
                previous_tier = row.storage_tier
                object_key = row.archive_object_key or _archive_object_key(record)
                row.storage_tier = "L3_cold"
                row.backend_targets = list(backend_targets_for_tier("L3_cold"))
                row.compressed = True
                row.archive_object_key = object_key
                db.add(
                    _record_to_storage_event_row(
                        storage_record_from_event_stream_row(row),
                        org_id=row.org_id,
                        operation="archive_to_cold_storage",
                        status="archived",
                        payload={
                            "archive_object_key": object_key,
                            "previous_tier": previous_tier,
                            "batch_size": batch_size,
                        },
                    )
                )
                keys.append(object_key)
            self._commit(db)
        return StorageArchiveResult(
            candidate_count=len(rows),
            archived_count=len(rows),
            archive_object_keys=tuple(keys),
        )

    def _append_record(
        self,
        record: StorageRecordEnvelope,
        *,
        org_id: str | None = None,
    ) -> None:
        resolved_org_id = self._resolve_org_id(org_id)
        row = _record_to_event_stream_row(record, org_id=resolved_org_id)
        with self._session() as db:
            db.add(row)
            db.add(
                _record_to_storage_event_row(
                    record,
                    org_id=resolved_org_id,
                    operation="write",
                    status="stored",
                    payload={"storage_tier": record.tier},
                )
            )
            self._commit(db)

    def _query_rows(
        self,
        *,
        event_id: str | None = None,
        org_id: str | None = None,
        module_id: str | None = None,
        context_id: str | None = None,
        trace_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
        indexes_used: tuple[str, ...] = ("idx_c17d_timestamp",),
    ) -> StorageQueryResult:
        with self._session() as db:
            statement = select(EventStreamRecord)
            if event_id is not None:
                statement = statement.where(EventStreamRecord.event_id == event_id)
            effective_org_id = org_id or self._org_id
            if effective_org_id is not None:
                statement = statement.where(EventStreamRecord.org_id == effective_org_id)
            if module_id is not None:
                statement = statement.where(EventStreamRecord.module_id == module_id)
            if context_id is not None:
                statement = statement.where(EventStreamRecord.context_id == context_id)
            if trace_id is not None:
                statement = statement.where(EventStreamRecord.trace_id == trace_id)
            if start_at is not None:
                statement = statement.where(EventStreamRecord.timestamp >= start_at)
            if end_at is not None:
                statement = statement.where(EventStreamRecord.timestamp <= end_at)
            statement = statement.order_by(
                EventStreamRecord.timestamp.desc(),
                EventStreamRecord.id.desc(),
            )
            rows = list(db.scalars(statement))
            total_count = len(rows)
            if limit is not None:
                rows = rows[: max(limit, 0)]
            records = tuple(storage_record_from_event_stream_row(row) for row in rows)
        searched_tiers = tuple(dict.fromkeys(record.tier for record in records))
        if not searched_tiers:
            searched_tiers = ("L1_hot", "L2_warm", "L3_cold")
        return StorageQueryResult(
            records=records,
            total_count=total_count,
            searched_tiers=searched_tiers,
            indexes_used=indexes_used,
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

    def _resolve_org_id(self, explicit_org_id: str | None = None) -> str:
        for value in (explicit_org_id, self._org_id):
            if isinstance(value, str) and value.strip():
                return value.strip()[:40]
        try:
            from .data_isolation import current_org_data_isolation_context

            context = current_org_data_isolation_context()
        except Exception:
            context = None
        if context is not None and context.org_id:
            return context.org_id[:40]
        return "platform"


def get_storage_architecture_design() -> StorageArchitectureDesign:
    return StorageArchitectureDesign()


def get_storage_data_model_design() -> StorageDataModelDesign:
    return StorageDataModelDesign()


def get_storage_adapter_interface_design() -> StorageAdapterInterfaceDesign:
    return StorageAdapterInterfaceDesign()


def get_storage_backend_design() -> StorageBackendDesign:
    return StorageBackendDesign()


def get_storage_indexing_strategy() -> StorageIndexingStrategy:
    return StorageIndexingStrategy()


def get_storage_retention_policy() -> StorageRetentionPolicy:
    return StorageRetentionPolicy()


def get_storage_write_path_design() -> StorageWritePathDesign:
    return StorageWritePathDesign()


def get_hot_warm_cold_data_flow() -> HotWarmColdDataFlow:
    return HotWarmColdDataFlow()


def get_c17c_to_c17d_storage_migration_strategy() -> (
    C17CToC17DStorageMigrationStrategy
):
    return C17CToC17DStorageMigrationStrategy()


def get_query_performance_strategy() -> QueryPerformanceStrategy:
    return QueryPerformanceStrategy()


def get_storage_layer_completion_status() -> StorageLayerCompletionStatus:
    return StorageLayerCompletionStatus()
